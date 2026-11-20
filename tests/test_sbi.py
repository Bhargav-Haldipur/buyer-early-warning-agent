"""The live-news book: real companies, fetched news, an illustrative ledger. All offline."""
import csv
import unittest

from ews.fetch_news import FIELDS, ITEMS_8K, mention_in
from ews.llm import FallbackLLM, keyword_grade, strict_resolve
from ews.loader import ROOT_DATA, Loader

SBI = ROOT_DATA / "sbi"


class Book(unittest.TestCase):
    def test_the_book_is_consistent(self):
        Loader(SBI).validate()

    def test_one_insurer_covers_every_buyer(self):
        lo = Loader(SBI)
        self.assertEqual([c["client_name"] for c in lo.clients()],
                         ["Trade Credit Insurer"])
        self.assertEqual({l["buyer_id"] for l in lo.credit_limits()},
                         {b["buyer_id"] for b in lo.buyers()})

    def test_nothing_in_the_ledger_is_seriously_late(self):
        """Illustrative payments must never invent distress at a real company.

        Checked at the source: days past due follow from the as-of date, so the shipped
        notifications age day by day until the book is re-seeded."""
        from ews import sbi_seed
        for b in sbi_seed.BUYERS:
            if b.get("real"):
                self.assertTrue(all(dpd < 30 for _, dpd, _ in b["open"]), b["short"])
        notes = Loader(SBI).table("notifiable_events")
        self.assertTrue(notes)
        self.assertEqual({n["NEV_REASON"] for n in notes}, {"OVERDUE_INVOICE"})

    def test_every_real_buyer_and_only_those_is_on_the_news_watchlist(self):
        with (SBI / "news_watchlist.csv").open() as fh:
            watch = {r["buyer_id"]: r for r in csv.DictReader(fh)}
        buyers = Loader(SBI).buyers()
        self.assertEqual(set(watch), {b["buyer_id"] for b in buyers if b["is_real"]})
        for b in buyers:
            if b["buyer_id"] in watch:
                self.assertEqual(watch[b["buyer_id"]]["country"], b["country"])
                if b["country"] == "USA":
                    self.assertTrue(watch[b["buyer_id"]]["cik"].isdigit(), b["short_name"])

    def test_the_grid_large_medium_small_by_india_and_overseas(self):
        from collections import Counter
        grid = Counter((b["size_band"], b["country"] == "IND") for b in Loader(SBI).buyers())
        self.assertEqual(set(grid.values()), {3})
        self.assertEqual(len(grid), 6)
        for b in Loader(SBI).buyers():
            self.assertEqual(b["is_real"], b["size_band"] == "large", b["short_name"])

    def test_indemnity_never_exceeds_80_per_cent(self):
        for p in Loader(SBI).table("policies"):
            self.assertLessEqual(float(p["INSURED_PERCENTAGE"]), 80, p["policy_id"])

    def test_a_real_company_is_never_flagged_on_its_invented_ledger(self):
        """Whatever moves a real company off Healthy must be real news."""
        from ews import sbi_seed
        from ews.config import W_PAYMENT, band, payment_score
        for b in sbi_seed.BUYERS:
            if b.get("real"):
                worst = max((dpd for _, dpd, _ in b["open"]), default=0)
                self.assertEqual(band(W_PAYMENT * payment_score(worst)), "Healthy", b["short"])

    def test_illustrative_stories_are_only_about_invented_companies(self):
        lo = Loader(SBI)
        names = {b["buyer_name"]: b for b in lo.buyers()}
        stories = lo.table("illustrative_articles")
        self.assertTrue(stories)
        for a in stories:
            self.assertEqual(a["publication"], "Illustrative")
            self.assertFalse(names[a["mentioned_entity_as_written"]]["is_real"], a["headline"])

    def test_fetched_news_has_the_columns_the_engine_reads(self):
        with (SBI / "news_articles.csv").open() as fh:
            self.assertEqual(tuple(csv.DictReader(fh).fieldnames), FIELDS)


class Routing(unittest.TestCase):
    """News is routed by the company's country: edition and trusted publishers."""

    def test_each_country_gets_its_google_news_edition(self):
        from ews.fetch_news import edition
        self.assertEqual(edition("IND"), ("en-IN", "IN", "IN:en"))
        self.assertEqual(edition("USA"), ("en-US", "US", "US:en"))
        self.assertEqual(edition("DEU"), edition("USA"), "no edition listed: the US one")

    def test_indian_publishers_are_trusted_only_for_indian_companies(self):
        from ews.fetch_news import publishers_for
        india, us = publishers_for(SBI, "IND"), publishers_for(SBI, "USA")
        self.assertIn("Business Standard", india)
        self.assertNotIn("Business Standard", us)
        self.assertIn("Reuters", india)
        self.assertIn("Reuters", us)

    def test_an_indian_company_is_searched_in_the_india_edition(self):
        from datetime import date
        from unittest.mock import patch
        from ews import fetch_news
        asked = []

        def fake_get(url, **kw):
            asked.append(url)
            return (b"<rss><channel><item><title>Tata Motors cuts output - Business Standard"
                    b"</title><source>Business Standard</source><link>https://x/1</link>"
                    b"<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>"
                    b"<item><title>Tata Motors cuts output - Some Blog</title>"
                    b"<source>Some Blog</source><link>https://x/2</link>"
                    b"<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>")
        with patch.object(fetch_news, "_get", fake_get), \
                patch.object(fetch_news, "AS_OF", date(2026, 11, 19)):
            kept, dropped = fetch_news.google_news(
                {"buyer_name": "Tata Motors Limited"},
                {"news_query": '"Tata Motors"', "aliases": "Tata Motors", "country": "IND"},
                date(2026, 10, 1), fetch_news.publishers_for(SBI, "IND"), 12)
        self.assertIn("hl=en-IN&gl=IN&ceid=IN:en", asked[0])
        self.assertEqual([a["publication"] for a in kept], ["Business Standard"])
        self.assertEqual(dropped, 1)

class Resolution(unittest.TestCase):
    def setUp(self):
        self.cands = [{"kind": "buyer", "id": b["buyer_id"], "name": b["buyer_name"]}
                      for b in Loader(SBI).buyers()]

    def test_us_legal_names_resolve_from_the_brand(self):
        for mention, want in [("Intel", "OS01"), ("The Boeing Company", "OS02"),
                              ("Ford Motor", "OS03"), ("Tata Motors", "IN01"),
                              ("Vodafone Idea", "IN03")]:
            self.assertEqual(strict_resolve(mention, self.cands)["id"], want, mention)

    def test_a_different_business_on_the_same_brand_is_refused(self):
        self.assertIsNone(strict_resolve("Ford Foundation", self.cands))

    def test_the_mention_is_only_what_the_headline_says(self):
        self.assertEqual(mention_in("Why Intel stock just dropped", ["Intel"]), "Intel")
        self.assertEqual(mention_in("Artificial intelligence spending booms", ["Intel"]), "")
        self.assertEqual(mention_in("Ford Motor reports results", ["Ford Motor", "Ford"]),
                         "Ford Motor")


class Grading(unittest.TestCase):
    def grade(self, text):
        return keyword_grade({"headline": text, "body": ""})

    def test_8k_items_that_mean_distress_grade_as_distress(self):
        self.assertEqual(self.grade(ITEMS_8K["1.03"])["severity"], 5)
        self.assertEqual(self.grade(ITEMS_8K["2.04"])["severity"], 5)
        self.assertEqual(self.grade(ITEMS_8K["4.02"])["severity"], 4)
        self.assertEqual(self.grade(ITEMS_8K["2.05"])["severity"], 2)
        self.assertEqual(self.grade(ITEMS_8K["2.06"])["severity"], 3)

    def test_routine_8k_items_grade_neutral(self):
        for item in ("2.02", "5.07", "7.01", "8.01", "1.01", "2.03"):
            self.assertEqual(self.grade(ITEMS_8K[item])["severity"], 0, item)

    def test_press_language(self):
        self.assertEqual(self.grade("Acme files for Chapter 11 protection")["severity"], 5)
        self.assertEqual(self.grade("Moody's cuts Acme credit rating to junk")["severity"], 4)
        self.assertEqual(self.grade("Boeing to cut 5% of commercial airplane workers")["severity"], 4)
        self.assertEqual(self.grade("Acme announces mass layoffs")["severity"], 4)
        self.assertEqual(self.grade("Nvidia says Jensen Huang won't return as CEO")["severity"], 4)
        self.assertEqual(self.grade("Microsoft offers buyouts to 60,000 employees")["severity"], 2)
        self.assertEqual(self.grade("Analyst downgrades Acme stock to hold")["severity"], 1)
        self.assertEqual(self.grade("Acme names new head of marketing")["severity"], 0)

    def test_fallback_refuses_a_story_that_names_no_covered_company(self):
        art = {"article_id": "X", "headline": "Outages hit banks", "body": "Outages hit banks",
               "mentioned_entity_as_written": ""}
        self.assertEqual(FallbackLLM(cache=False).resolve(art, self.cands())["kind"], "none")

    def cands(self):
        return [{"kind": "buyer", "id": b["buyer_id"], "name": b["buyer_name"]}
                for b in Loader(SBI).buyers()]


class AutoRefresh(unittest.TestCase):
    """The on/off switch. The fetch itself is stubbed: no test reaches the network."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        import dashboard.server as S
        from ews import user_settings
        self.S, self.us = S, user_settings
        self._saved = (dict(S.AUTO), dict(S.FETCH), S.fetch_news.fetch, S.snapshot,
                       user_settings.PATH)
        self.tmp = tempfile.TemporaryDirectory()
        user_settings.PATH = Path(self.tmp.name) / "settings.json"   # never the real file
        S.snapshot = lambda: {}
        self.calls = []

        def fake_fetch(**kw):
            self.calls.append(kw)
            return {"articles": 7, "errors": []}
        S.fetch_news.fetch = fake_fetch

    def tearDown(self):
        auto, fetch, real_fetch, snap, path = self._saved
        self.S.AUTO.clear(); self.S.AUTO.update(auto)
        self.S.FETCH.clear(); self.S.FETCH.update(fetch)
        self.S.fetch_news.fetch, self.S.snapshot = real_fetch, snap
        self.us.PATH = path
        self.tmp.cleanup()

    def test_the_shipped_settings_file_starts_off(self):
        self.assertFalse(self.us.load(self._saved[4])["news"]["auto_refresh"])

    def test_the_button_writes_the_settings_file(self):
        self.S.set_auto(True)
        self.assertTrue(self.us.load()["news"]["auto_refresh"])
        self.S.set_auto(False)
        self.assertFalse(self.us.load()["news"]["auto_refresh"])

    def test_editing_the_file_flips_the_switch_without_a_restart(self):
        import json
        self.S.sync_settings()
        self.assertFalse(self.S.AUTO["on"])
        self.us.PATH.write_text(json.dumps({"news": {"auto_refresh": True, "refresh_minutes": 5}}))
        self.S.sync_settings()
        self.assertTrue(self.S.AUTO["on"])
        self.assertEqual(self.S.AUTO["minutes"], 5)
        self.assertIsNotNone(self.S.AUTO["next"])

    def test_a_broken_file_keeps_the_last_good_settings(self):
        self.S.set_auto(True)
        self.us.PATH.write_text('{"news": {"auto_refresh": tru')
        self.S.sync_settings()
        self.assertTrue(self.S.AUTO["on"], "a typo must not switch it off")
        self.assertIn("not valid JSON", self.S.AUTO["error"])
        self.assertIn("not applied", self.S.auto_switch())

    def test_the_fetch_uses_the_file_s_lookback(self):
        import json
        self.us.PATH.write_text(json.dumps({"news": {"lookback_days": 30,
                                                     "stories_per_company": 5}}))
        self.S.sync_settings()
        self.S.refresh_news("Auto")
        self.assertEqual(self.calls[-1]["days"], 30)
        self.assertEqual(self.calls[-1]["per_buyer"], 5)

    def test_switching_on_schedules_a_fetch_now_and_off_cancels_it(self):
        import time
        self.S.set_auto(True)
        self.assertTrue(self.S.AUTO["on"])
        self.assertLessEqual(self.S.AUTO["next"], time.time())
        self.assertIn("Auto refresh: ON", self.S.auto_switch())
        self.S.set_auto(False)
        self.assertFalse(self.S.AUTO["on"])
        self.assertIsNone(self.S.AUTO["next"])
        self.assertIn("Auto refresh: OFF", self.S.auto_switch())

    def test_a_fetch_records_what_it_did(self):
        self.S.refresh_news("Auto")
        self.assertEqual(len(self.calls), 1)
        self.assertIn("Auto fetch at", self.S.FETCH["last"])
        self.assertFalse(self.S.AUTO["running"])

    def test_two_fetches_never_overlap(self):
        self.S._FETCH_LOCK.acquire()
        try:
            self.S.refresh_news("Auto")
        finally:
            self.S._FETCH_LOCK.release()
        self.assertEqual(self.calls, [])
        self.assertIn("already running", self.S.FETCH["last"])

    def test_a_failed_fetch_keeps_the_old_news(self):
        def broken(**kw):
            raise OSError("network down")
        self.S.fetch_news.fetch = broken
        self.S.refresh_news("Auto")
        self.assertIn("previous news is still in use", self.S.FETCH["last"])
        self.assertFalse(self.S.AUTO["running"])


class SettingsFile(unittest.TestCase):
    def check(self, news):
        from ews.user_settings import SettingsFileError, _validate
        with self.assertRaises(SettingsFileError, msg=news):
            _validate({"news": news})

    def test_bad_values_are_refused(self):
        self.check({"auto_refresh": "yes"})
        self.check({"refresh_minutes": 0})
        self.check({"refresh_minutes": True})
        self.check({"lookback_days": 1000})
        self.check({"auto_refrsh": True})           # a typo is an error, not ignored

    def test_missing_keys_take_the_defaults(self):
        from ews.user_settings import DEFAULTS, _validate
        self.assertEqual(_validate({}), DEFAULTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
