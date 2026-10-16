"""Deterministic tests for the data layer and tools (no LLM needed): python -m unittest"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emporio_agent.data import Repository, brl, tokenize  # noqa: E402
from emporio_agent.tools import STORE_TZ, Clock, Toolbox  # noqa: E402


def at(y, m, d, h=10, mi=0):
    return Clock(datetime(y, m, d, h, mi, tzinfo=STORE_TZ))


class ToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Repository()

    def tb(self, clock=None):
        return Toolbox(repo=self.repo, clock=clock or at(2026, 2, 20),
                       handoff_file=Path(tempfile.mkdtemp()) / "h.jsonl")

    def call(self, tb, tool, **kw):
        return json.loads(tb.call(tool, kw))

    # ---- data layer
    def test_text_normalisation_and_plurals(self):
        self.assertEqual(tokenize("Violões"), tokenize("violao"))
        self.assertEqual(brl(2199), "R$ 2.199,00")

    def test_only_active_promotions_are_loaded(self):
        self.assertEqual(self.repo.products[94].active_discount_pct, 8)   # is_active=1
        self.assertEqual(self.repo.products[93].active_discount_pct, 0)   # expired campaigns ignored
        self.assertEqual(self.repo.products[94].promo_price, 5519.08)

    # ---- catalog
    def test_budget_search_excludes_unsellable_and_respects_price(self):
        r = self.call(self.tb(), "search_products", category="violões", max_price=1000)
        ids = {p["product_id"] for p in r["products"]}
        self.assertNotIn(96, ids)    # stock 0
        self.assertNotIn(113, ids)   # discontinued
        for pid in ids:
            self.assertLessEqual(self.repo.products[pid].effective_price, 1000)
            self.assertEqual(self.repo.products[pid].category_id, 5)

    def test_price_lookup_by_name(self):
        r = self.call(self.tb(), "get_product_details", name="Takamine GD20")
        self.assertEqual(r["product_id"], 95)
        self.assertEqual(r["list_price"], "R$ 2.199,00")
        self.assertEqual(r["pix_price"], "R$ 2.089,05")

    def test_promo_shows_original_and_blocks_pix_discount(self):
        r = self.call(self.tb(), "get_product_details", product_id=94)
        self.assertEqual(r["promotion"]["original_price"], "R$ 5.999,00")
        self.assertEqual(r["promotion"]["promotional_price"], "R$ 5.519,08")
        self.assertNotIn("pix_price", r)

    def test_out_of_stock_returns_alternatives(self):
        r = self.call(self.tb(), "get_product_details", product_id=96)
        self.assertEqual(r["availability"], "out_of_stock")
        self.assertTrue(r["alternatives"])

    def test_coming_soon_is_not_sellable_even_with_stock(self):
        r = self.call(self.tb(), "get_product_details", product_id=130)
        self.assertEqual(r["availability"], "coming_soon")

    def test_empty_category_is_reported_not_invented(self):
        r = self.call(self.tb(), "search_products", category="saxofone sopro madeiras")
        self.assertEqual(r["total_matches"], 0)
        self.assertIn("note", r)

    def test_zero_price_bounds_mean_unset(self):
        # Regression: the LLM sends max_price=0 for "not provided"; it must not filter everything out.
        r = self.call(self.tb(), "search_products", query="Taylor 110e", category="Violões", max_price=0, min_price=0)
        self.assertEqual([p["product_id"] for p in r["products"]], [94])

    def test_expired_promotion_is_reported_as_ended(self):
        r = self.call(self.tb(), "get_product_details", name="Martin D-28 Dreadnought")
        self.assertNotIn("promotion", r)
        self.assertIn("Páscoa", " ".join(r["expired_promotions"]["items"]))

    # ---- payments
    def test_installment_rules(self):
        tb = self.tb()
        mx = lambda amt: self.call(tb, "get_payment_options", amount=amt)["options"][3]["max_installments"]  # noqa: E731
        self.assertEqual(mx(2199), 12)
        self.assertEqual(mx(400), 5)     # 5x = 80.00 ok, 6x = 66.67 < 80
        self.assertEqual(mx(159.9), 3)   # 3x = 53.30 >= 50, 4x = 39.97 < 80
        self.assertEqual(mx(60), 1)      # 2x = 30 < 50

    # ---- orders
    def test_order_requires_matching_identity(self):
        tb = self.tb()
        ok = self.call(tb, "get_order_status", order_id=7, customer_identifier="leticia.rocha@jmail.com")
        self.assertEqual(ok["status"], "delivered")
        self.assertIn("error", self.call(tb, "get_order_status", order_id=7, customer_identifier="x@y.com"))
        # another real customer's e-mail must not unlock the order
        self.assertIn("error", self.call(tb, "get_order_status", order_id=7,
                                         customer_identifier="lucas.mendes@jmail.com"))

    def test_phone_identification(self):
        r = self.call(self.tb(), "get_order_status", order_id=7, customer_identifier="67 99789-0123")
        self.assertEqual(r["order_id"], 7)

    def test_return_inside_regret_window(self):
        r = self.call(self.tb(at(2026, 2, 20)), "check_return_eligibility", order_id=7,
                      customer_identifier="leticia.rocha@jmail.com", reason="regret")
        self.assertTrue(r["options"]["regret"]["eligible"])
        self.assertEqual(r["options"]["regret"]["deadline"], "2026-02-24")
        self.assertTrue(r["receipt_date_is_estimate"])

    def test_return_outside_windows_but_legal_warranty_active(self):
        r = self.call(self.tb(at(2026, 2, 20)), "check_return_eligibility", order_id=6,
                      customer_identifier="gabriel.araujo@jmail.com", reason="regret")
        self.assertFalse(r["options"]["regret"]["eligible"])
        self.assertFalse(r["options"]["defect"]["eligible"])
        self.assertTrue(r["legal_warranty"]["active"])

    def test_undelivered_and_cancelled_orders(self):
        tb = self.tb()
        pending = self.call(tb, "check_return_eligibility", order_id=13, customer_identifier="fernanda.ribeiro@coldmail.com")
        self.assertIsNone(pending["eligible"])
        cancelled = self.call(tb, "check_return_eligibility", order_id=18, customer_identifier="gustavo.nunes@inlook.com")
        self.assertFalse(cancelled["eligible"])

    # ---- policies / misc
    def test_opening_hours_state(self):
        wed = self.call(self.tb(at(2026, 2, 18, 10)), "get_store_policy", topic="hours")
        sat_pm = self.call(self.tb(at(2026, 2, 21, 14)), "get_store_policy", topic="hours")
        sun = self.call(self.tb(at(2026, 2, 22, 11)), "get_store_policy", topic="hours")
        self.assertTrue(wed["open_now"])
        self.assertFalse(sat_pm["open_now"])
        self.assertFalse(sun["open_now"])

    def test_next_opening(self):
        sat_pm = self.call(self.tb(at(2026, 2, 21, 14)), "get_store_policy", topic="hours")
        self.assertTrue(sat_pm["next_opening"].startswith("Monday 2026-02-23"))
        early = self.call(self.tb(at(2026, 2, 18, 7)), "get_store_policy", topic="hours")
        self.assertTrue(early["next_opening"].startswith("Wednesday 2026-02-18"))

    def test_portuguese_reason_is_normalised(self):
        r = self.call(self.tb(), "check_return_eligibility", order_id=7,
                      customer_identifier="leticia.rocha@jmail.com", reason="arrependimento")
        self.assertEqual(r["requested_reason"], "regret")

    def test_all_policy_topics_resolve(self):
        from emporio_agent.tools import POLICY_TOPICS
        tb = self.tb()
        for topic in POLICY_TOPICS:
            self.assertIn("policy_text", self.call(tb, "get_store_policy", topic=topic), topic)

    def test_bad_tool_calls_do_not_crash(self):
        tb = self.tb()
        self.assertIn("error", json.loads(tb.call("nope", {})))
        self.assertIn("error", json.loads(tb.call("get_order_status", {"order_id": 1})))
        self.assertIn("error", json.loads(tb.call("search_products", "{not json")))

    def test_handoff_creates_ticket(self):
        tb = self.tb()
        r = self.call(tb, "handoff_to_human", reason="complaint", summary="late delivery")
        self.assertTrue(r["ticket"].startswith("EM-"))
        self.assertTrue(tb.handoff_file.exists())


if __name__ == "__main__":
    unittest.main()
