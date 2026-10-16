"""Data layer: loads the store CSVs, normalises them and exposes read-only queries.

Design notes
- Everything is held in memory (65 products, 20 orders): no database needed for a prototype.
- Text matching is accent- and case-insensitive with a tiny PT-BR stemmer, so "violões",
  "violao" and "Violões" all match.
- Business rules that must never depend on LLM arithmetic (promo price, availability) live here.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PREFIX = "desafio_tecnico_ai_eng - "


def normalize(text: str) -> str:
    """Lowercase and strip accents."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _stem(token: str) -> str:
    """Very small PT-BR stemmer: enough to match plurals ("violoes"/"violao", "baixos"/"baixo")."""
    if token.endswith("oes") or token.endswith("aes"):
        return token[:-3] + "ao"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", normalize(text))]


def brl(value: float) -> str:
    """Format as Brazilian currency: 2199 -> 'R$ 2.199,00'."""
    s = f"{value:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class Product:
    product_id: int
    name: str
    price: float
    category_id: int
    category: str
    description: str
    stock: int
    status: str  # active | discontinued | coming_soon
    specs: dict
    active_discount_pct: float = 0.0
    active_promotion: str | None = None
    _tokens: set[str] = field(default_factory=set, repr=False)

    @property
    def promo_price(self) -> float | None:
        if not self.active_discount_pct:
            return None
        return round(self.price * (1 - self.active_discount_pct / 100), 2)

    @property
    def effective_price(self) -> float:
        return self.promo_price if self.promo_price is not None else self.price

    @property
    def availability(self) -> str:
        """in_stock | out_of_stock | discontinued | coming_soon.

        A 'coming_soon' product is NOT sellable even when stock > 0 (see README: data decisions).
        """
        if self.status == "discontinued":
            return "discontinued"
        if self.status == "coming_soon":
            return "coming_soon"
        return "in_stock" if self.stock > 0 else "out_of_stock"

    @property
    def sellable(self) -> bool:
        return self.availability == "in_stock"


@dataclass
class Order:
    order_id: int
    customer_id: int
    order_date: str
    status: str
    total: float
    payment_method: str
    tracking_code: str
    estimated_delivery: str
    notes: str
    items: list[tuple[int, int]]  # (product_id, quantity)


@dataclass
class Customer:
    customer_id: int
    name: str
    phone: str
    email: str
    city: str


def _read(name: str) -> list[dict]:
    path = DATA_DIR / f"{_PREFIX}{name}.csv"
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Repository:
    def __init__(self) -> None:
        self.categories = {int(r["category_id"]): r["name"] for r in _read("categories")}
        self.customers = {
            int(r["customer_id"]): Customer(int(r["customer_id"]), r["name"].strip(), r["phone"].strip(),
                                            r["email"].strip().lower(), r["city"].strip())
            for r in _read("customers")
        }
        promos: dict[int, tuple[float, str]] = {}
        for r in _read("promotions"):
            if r["is_active"].strip() != "1":
                continue  # expired campaigns must never be quoted (manual §7.3)
            pid, pct = int(r["product_id"]), float(r["discount_percent"])
            # Promotions are not cumulative (manual §6.2): keep the single best active one.
            if pid not in promos or pct > promos[pid][0]:
                promos[pid] = (pct, r["description"])

        self.products: dict[int, Product] = {}
        for r in _read("products"):
            pid = int(r["product_id"])
            try:
                specs = json.loads(r["specs"]) if r["specs"] else {}
            except json.JSONDecodeError:
                specs = {}
            cat = self.categories.get(int(r["category_id"]), "")
            p = Product(pid, r["name"].strip(), float(r["price_brl"]), int(r["category_id"]), cat,
                        r["description"].strip(), int(r["stock_quantity"]), r["status"].strip(), specs)
            if pid in promos:
                p.active_discount_pct, p.active_promotion = promos[pid]
            blob = " ".join([p.name, p.description, cat, " ".join(str(v) for v in specs.values())])
            p._tokens = set(tokenize(blob))
            self.products[pid] = p

        items: dict[int, list[tuple[int, int]]] = {}
        for r in _read("order_items"):
            items.setdefault(int(r["order_id"]), []).append((int(r["product_id"]), int(r["quantity"])))
        self.orders = {
            int(r["order_id"]): Order(int(r["order_id"]), int(r["customer_id"]), r["order_date"], r["status"],
                                      float(r["total_brl"]), r["payment_method"], r["tracking_code"],
                                      r["estimated_delivery"], r["notes"], items.get(int(r["order_id"]), []))
            for r in _read("orders")
        }

    # ---- queries -----------------------------------------------------------------
    def category_id_for(self, text: str) -> int | None:
        """Map free text ("violão", "guitarras", "bateria") to a category id."""
        wanted = set(tokenize(text))
        if not wanted:
            return None
        best, best_score = None, 0
        for cid, name in self.categories.items():
            score = len(wanted & set(tokenize(name)))
            if score > best_score:
                best, best_score = cid, score
        return best

    def search(self, query: str = "", category: str = "", min_price: float | None = None,
               max_price: float | None = None, include_unavailable: bool = False) -> list[Product]:
        q_tokens = set(tokenize(query))
        cat_id = self.category_id_for(category) if category else None
        scored: list[tuple[float, Product]] = []
        for p in self.products.values():
            if cat_id is not None and p.category_id != cat_id:
                continue
            if not include_unavailable and not p.sellable:
                continue
            price = p.effective_price
            if min_price is not None and price < min_price:
                continue
            if max_price is not None and price > max_price:
                continue
            if q_tokens:
                hits = len(q_tokens & p._tokens)
                if hits == 0:
                    continue
                score = hits / len(q_tokens)
                if score < 0.5:  # at least half of the query terms must match
                    continue
                # Name matches weigh more than description matches.
                score += 0.5 * len(q_tokens & set(tokenize(p.name))) / len(q_tokens)
            else:
                score = 0.0
            scored.append((score, p))
        scored.sort(key=lambda sp: (-sp[0], sp[1].effective_price))
        return [p for _, p in scored]

    def similar(self, product: Product, limit: int = 3) -> list[Product]:
        """Sellable alternatives: same category, closest price first."""
        pool = [p for p in self.products.values()
                if p.product_id != product.product_id and p.category_id == product.category_id and p.sellable]
        pool.sort(key=lambda p: abs(p.effective_price - product.effective_price))
        return pool[:limit]

    def find_customer(self, identifier: str) -> Customer | None:
        """Resolve an e-mail or phone number (digits only compared) to a customer."""
        ident = (identifier or "").strip().lower()
        if not ident:
            return None
        digits = re.sub(r"\D", "", ident)
        for c in self.customers.values():
            if "@" in ident and c.email == ident:
                return c
            if len(digits) >= 8 and re.sub(r"\D", "", c.phone).endswith(digits[-9:]):
                return c
        return None
