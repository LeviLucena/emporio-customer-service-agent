"""Agent tools (function calling).

Every tool returns plain JSON-serialisable dicts. Anything involving money, dates or policy
thresholds is computed here, deterministically, instead of being left to the LLM.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .data import Product, Repository, brl, normalize

KNOWLEDGE_FILE = Path(__file__).resolve().parent.parent / "knowledge" / "store_policies.md"
STORE_TZ = timezone(timedelta(hours=-4))  # America/Campo_Grande (no DST since 2019)
MAX_RESULTS = 8

POLICY_TOPICS = ["about", "hours", "payment", "installments", "returns", "shipping",
                 "promotions", "service_guidelines", "warranty", "privacy"]


@dataclass
class Clock:
    """Injectable clock so demos/tests can pin 'today' (the dataset ends in March 2026)."""
    override: datetime | None = None

    def now(self) -> datetime:
        return self.override or datetime.now(STORE_TZ)

    def today(self) -> date:
        return self.now().date()


def _opening_window(weekday: int) -> tuple[int, int] | None:
    """Opening window in minutes since midnight (manual §2); Monday=0."""
    return (9 * 60, 18 * 60) if weekday <= 4 else (9 * 60, 13 * 60) if weekday == 5 else None


def _load_policies() -> dict[str, str]:
    text = KNOWLEDGE_FILE.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    for m in re.finditer(r"<!-- topic: (\w+) -->\n(.*?)(?=\n<!-- topic:|\Z)", text, flags=re.S):
        sections[m.group(1)] = m.group(2).strip()
    return sections


def _product_view(p: Product, detail: bool = False) -> dict:
    d: dict[str, Any] = {
        "product_id": p.product_id, "name": p.name, "category": p.category,
        "list_price": brl(p.price), "availability": p.availability,
    }
    if p.promo_price is not None:
        d["promotion"] = {"name": p.active_promotion, "discount_percent": p.active_discount_pct,
                          "original_price": brl(p.price), "promotional_price": brl(p.promo_price)}
        d["pix_discount"] = "not applicable (PIX 5% does not stack on promotional prices)"
    else:
        d["pix_price"] = brl(round(p.price * 0.95, 2))
    if p.sellable and p.stock <= 3:
        d["stock_note"] = f"only {p.stock} unit(s) left"
    if detail:
        d["description"] = p.description
        d["specs"] = p.specs
        if p.expired_promotions:
            d["expired_promotions"] = {"items": p.expired_promotions,
                                      "note": "ENDED - never offer these; say they are over and quote the current price"}
    return d


# ---- tools ------------------------------------------------------------------------
class Toolbox:
    def __init__(self, repo: Repository | None = None, clock: Clock | None = None,
                 handoff_file: Path | str = "handoffs.jsonl") -> None:
        self.repo = repo or Repository()
        self.clock = clock or Clock()
        self.handoff_file = Path(handoff_file)
        self._policies = _load_policies()
        self._dispatch: dict[str, Callable[..., dict]] = {
            "search_products": self.search_products,
            "get_product_details": self.get_product_details,
            "get_payment_options": self.get_payment_options,
            "get_store_policy": self.get_store_policy,
            "get_order_status": self.get_order_status,
            "check_return_eligibility": self.check_return_eligibility,
            "handoff_to_human": self.handoff_to_human,
        }

    def call(self, name: str, arguments: dict | str | None) -> str:
        """Execute a tool call coming from the model; always returns a JSON string."""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                return json.dumps({"error": "arguments were not valid JSON"})
        fn = self._dispatch.get(name)
        if fn is None:
            return json.dumps({"error": f"unknown tool '{name}'", "available": list(self._dispatch)})
        try:
            return json.dumps(fn(**(arguments or {})), ensure_ascii=False)
        except TypeError as exc:  # wrong/missing arguments from the model
            return json.dumps({"error": f"invalid arguments: {exc}"})

    # -- catalog --
    def search_products(self, query: str = "", category: str = "", min_price: float | None = None,
                        max_price: float | None = None, include_unavailable: bool = False) -> dict:
        # LLMs often send 0 for "not provided": a price bound of 0 is meaningless, treat it as unset.
        min_price = min_price if min_price and min_price > 0 else None
        max_price = max_price if max_price and max_price > 0 else None
        results = self.repo.search(query, category, min_price, max_price, include_unavailable)
        out: dict[str, Any] = {"total_matches": len(results),
                               "products": [_product_view(p) for p in results[:MAX_RESULTS]]}
        if len(results) > MAX_RESULTS:
            out["note"] = (f"{len(results)} matches in total but only the {MAX_RESULTS} cheapest are listed; tell the "
                           "customer the real total and ask how to narrow the search")
        if not results:
            cat_id = self.repo.category_id_for(category) if category else None
            if cat_id is not None and not any(p.category_id == cat_id for p in self.repo.products.values()):
                out["note"] = ("this category exists but has no products registered in the system right now; "
                               "do not invent items - offer to forward to the team")
            else:
                out["note"] = ("no matching sellable product. Do NOT suggest products from memory: retry with "
                               "broader terms, call get_product_details(name=...) if a specific model was asked "
                               "(it also reports unavailable items), or offer a human handoff")
        return out

    def get_product_details(self, product_id: int | None = None, name: str = "") -> dict:
        product = self.repo.products.get(int(product_id)) if product_id not in (None, "") else None
        if product is None and name:
            found = self.repo.search(name, include_unavailable=True)
            product = found[0] if found else None
        if product is None:
            return {"error": "product not found", "hint": "use search_products to look for it"}
        out = _product_view(product, detail=True)
        if not product.sellable:
            out["alternatives"] = [_product_view(p) for p in self.repo.similar(product)]
            if product.availability == "coming_soon":
                out["note"] = "not on sale yet - do not confirm availability or take orders"
        return out

    # -- payments --
    def get_payment_options(self, amount: float | None = None, product_id: int | None = None) -> dict:
        promo = False
        if product_id not in (None, "", 0):
            p = self.repo.products.get(int(product_id))
            if p is None:
                return {"error": "product not found"}
            amount, promo = p.effective_price, p.promo_price is not None
        if amount is None:
            return {"error": "provide a positive amount or a product_id"}
        amount = round(float(amount), 2)
        if amount <= 0:
            return {"error": "provide a positive amount or a product_id"}

        def min_installment(n: int) -> float:  # manual §3.1
            return 0.0 if n == 1 else 50.0 if n <= 3 else 80.0 if n <= 6 else 100.0

        max_n = max((n for n in range(1, 13) if n == 1 or amount / n >= min_installment(n)), default=1)
        options = [{"method": "PIX", "total": brl(amount if promo else round(amount * 0.95, 2)),
                    "note": "no extra discount: price is already promotional" if promo else "5% discount"},
                   {"method": "debit card", "total": brl(amount), "note": "single payment"},
                   {"method": "boleto", "total": brl(amount), "note": "single payment, clears in up to 3 business days"},
                   {"method": "credit card", "total": brl(amount), "max_installments": max_n,
                    "installment_value": brl(round(amount / max_n, 2)), "note": "no interest"}]
        return {"amount": brl(amount), "options": options,
                "combine_payment_methods_allowed": amount > 2000,
                "free_shipping_metropolitan_area": amount > 500}

    # -- policies --
    def get_store_policy(self, topic: str) -> dict:
        topic = normalize(topic).replace(" ", "_")
        if topic not in self._policies:
            return {"error": f"unknown topic '{topic}'", "valid_topics": POLICY_TOPICS}
        out: dict[str, Any] = {"topic": topic, "policy_text": self._policies[topic]}
        if topic == "hours":
            now = self.clock.now()
            out["current_time"] = now.strftime("%A %Y-%m-%d %H:%M (Campo Grande)")
            hm = now.hour * 60 + now.minute
            window = _opening_window(now.weekday())
            out["open_now"] = bool(window and window[0] <= hm < window[1])
            if not out["open_now"]:
                for ahead in range(8):  # next regular opening (holidays are not considered)
                    day = now + timedelta(days=ahead)
                    w = _opening_window(day.weekday())
                    if w and (ahead > 0 or hm < w[0]):
                        out["next_opening"] = f"{day.strftime('%A %Y-%m-%d')} at 09:00"
                        break
            out["note"] = "national holidays are closed even on weekdays; not checked automatically"
        return out

    # -- orders --
    def _authorise(self, order_id: int, identifier: str):
        """Orders are only disclosed to the account holder (LGPD): e-mail or phone must match."""
        order = self.repo.orders.get(int(order_id)) if str(order_id).strip().isdigit() else None
        # E-mails are not unique in the data (customers 11 and 43): accept any matching record that owns the order.
        customer = next((c for c in self.repo.find_customers(identifier)
                         if order is not None and c.customer_id == order.customer_id), None)
        if order is None or customer is None:
            # Same message for "no such order" and "wrong owner": do not leak which orders exist.
            return None, None, {"error": "could not verify this order for the information provided",
                                "hint": "ask the customer for the order number and the e-mail or phone used on the purchase"}
        return order, customer, None

    def get_order_status(self, order_id: int, customer_identifier: str) -> dict:
        order, customer, err = self._authorise(order_id, customer_identifier)
        if err:
            return err
        meaning = {"pending": "awaiting payment confirmation", "confirmed": "payment confirmed, being prepared",
                   "shipped": "dispatched, on its way", "delivered": "delivered", "cancelled": "cancelled"}
        out: dict[str, Any] = {
            "order_id": order.order_id, "customer_first_name": customer.name.split()[0],
            "order_date": order.order_date, "status": order.status,
            "status_meaning": meaning.get(order.status, order.status), "total": brl(order.total),
            "payment_method": order.payment_method,
            "items": [{"product": self.repo.products[pid].name, "quantity": q} for pid, q in order.items
                      if pid in self.repo.products],
        }
        if order.tracking_code:
            out["tracking_code"] = order.tracking_code
        if order.estimated_delivery:
            out["estimated_delivery"] = order.estimated_delivery
        if order.notes:
            out["notes"] = order.notes
        return out

    def check_return_eligibility(self, order_id: int, customer_identifier: str, reason: str = "unspecified") -> dict:
        order, customer, err = self._authorise(order_id, customer_identifier)
        if err:
            return err
        reason = {"arrependimento": "regret", "desistencia": "regret", "defeito": "defect",
                  "preferencia": "preference", "troca": "preference"}.get(normalize(reason), reason)
        today = self.clock.today()
        base: dict[str, Any] = {"order_id": order.order_id, "order_status": order.status, "today": today.isoformat()}
        if order.status == "cancelled":
            return {**base, "eligible": False, "explanation": "order was cancelled; nothing to return",
                    "notes": order.notes}
        if order.status != "delivered":
            return {**base, "eligible": None,
                    "explanation": "order has not been delivered yet, so return windows have not started "
                                   "(they count from receipt). Cancellation before delivery is not covered by "
                                   "the manual: hand off to the team.",
                    "next_step": "handoff_to_human if the customer wants to cancel"}

        # The dataset has no receipt date: estimated_delivery is the best proxy (documented assumption).
        received = date.fromisoformat(order.estimated_delivery or order.order_date)
        purchased = date.fromisoformat(order.order_date)
        since_receipt, since_purchase = (today - received).days, (today - purchased).days

        def window(kind: str, start: date, days: int, rule: str) -> dict:
            deadline = start + timedelta(days=days)
            return {"eligible": today <= deadline, "deadline": deadline.isoformat(),
                    "days_left": (deadline - today).days, "rule": rule}

        options = {
            "regret": window("regret", received, 7, "7 calendar days after receipt, no justification; original "
                             "packaging, unused, all accessories; refund to original payment method in up to 10 "
                             "business days; return shipping paid by the store (manual 4.1)"),
            "defect": window("defect", purchased, 30, "manufacturing defect: exchange within 30 calendar days of "
                             "purchase (manual 4.2); misuse/drops/humidity/unauthorised changes not covered"),
            "preference": window("preference", received, 7, "7 days, subject to stock of the desired item, perfect "
                                 "condition, original packaging; price difference charged/refunded (manual 4.3)"),
        }
        legal_end = received + timedelta(days=90)
        result = {**base, "eligible_overall": any(o["eligible"] for o in options.values()),
                  "receipt_date_used": received.isoformat(), "receipt_date_is_estimate": True,
                  "days_since_receipt": since_receipt, "days_since_purchase": since_purchase,
                  "options": options,
                  "legal_warranty": {"active": today <= legal_end, "until": legal_end.isoformat(),
                                     "rule": "90 days against manufacturing defects (manual 8.1); after the "
                                             "30-day exchange window, defects go through the manufacturer "
                                             "warranty and the store can mediate (manual 4.2)"},
                  "ineligible_items_reminder": ["custom setup/special adjustments", "final-sale liquidation items",
                                                "wind-instrument mouthpieces"],
                  "next_step": "the store team confirms and processes the return: use handoff_to_human"}
        if reason in options:
            result["requested_reason"] = reason
            result["requested_reason_eligible"] = options[reason]["eligible"]
        return result

    # -- escalation --
    def handoff_to_human(self, reason: str, summary: str, customer_contact: str = "") -> dict:
        ticket = f"EM-{self.clock.now().strftime('%Y%m%d%H%M%S')}"
        record = {"ticket": ticket, "created_at": self.clock.now().isoformat(), "reason": reason,
                  "summary": summary, "customer_contact": customer_contact}
        with open(self.handoff_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ticket": ticket, "status": "registered",
                "sla": "the team replies within 24 business hours"}


# ---- JSON schemas sent to the model (OpenAI/Ollama function-calling format) ---------
def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []}}}


TOOL_SCHEMAS = [
    _fn("search_products",
        "Search the instrument catalog. Use for any question about what is available, models, prices or "
        "price ranges. Prices returned already include active promotions. By default only sellable items.",
        {"query": {"type": "string", "description": "free text: brand, model, type, e.g. 'nylon', 'Yamaha'"},
         "category": {"type": "string", "description": "e.g. 'violão', 'guitarra', 'baixo', 'bateria', 'teclado', 'ukulele'"},
         "min_price": {"type": "number", "description": "BRL"},
         "max_price": {"type": "number", "description": "BRL, applied to the effective (promotional) price"},
         "include_unavailable": {"type": "boolean", "description": "also list out-of-stock/discontinued items"}}),
    _fn("get_product_details",
        "Full details, availability and alternatives for ONE product, by product_id or (partial) name. "
        "Use for 'how much is X', 'do you have X in stock', specs.",
        {"product_id": {"type": "integer"}, "name": {"type": "string", "description": "e.g. 'Takamine GD20'"}}),
    _fn("get_payment_options",
        "Compute payment methods, PIX price and the maximum interest-free installments for a product or amount.",
        {"product_id": {"type": "integer"}, "amount": {"type": "number", "description": "BRL, if no product_id"}}),
    _fn("get_store_policy",
        "Official store policy text. Use for: opening hours/open now (hours), address/phone/who we are (about), "
        "payment methods (payment), installment rules (installments), returns/exchanges/regret (returns), "
        "delivery/shipping fees (shipping), promotion rules (promotions), warranty (warranty), data privacy (privacy).",
        {"topic": {"type": "string", "enum": POLICY_TOPICS}}, ["topic"]),
    _fn("get_order_status",
        "Status, items, tracking and delivery estimate of an order. Requires the order number AND the e-mail or "
        "phone registered on the purchase (identity check). Never guess these values.",
        {"order_id": {"type": "integer"},
         "customer_identifier": {"type": "string", "description": "e-mail or phone given by the customer"}},
        ["order_id", "customer_identifier"]),
    _fn("check_return_eligibility",
        "Decide whether an order can be returned/exchanged under the policy (regret 7 days, defect 30 days, "
        "preference 7 days), with exact deadlines. Same identity requirements as get_order_status.",
        {"order_id": {"type": "integer"}, "customer_identifier": {"type": "string"},
         "reason": {"type": "string", "enum": ["regret", "defect", "preference", "unspecified"]}},
        ["order_id", "customer_identifier"]),
    _fn("handoff_to_human",
        "Register a ticket for the human team: complaints, return/cancellation requests to be processed, "
        "anything the policies do not cover or the customer asks for a person.",
        {"reason": {"type": "string", "description": "complaint | return_request | cancellation | other"},
         "summary": {"type": "string", "description": "self-contained summary of the case"},
         "customer_contact": {"type": "string", "description": "e-mail/phone if the customer provided it"}},
        ["reason", "summary"]),
]
