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
        self.assertEqual(mention_in("Week 11 fantasy intel: who to start", ["Intel"]), "")
        self.assertEqual(mention_in("INTEL CUTS 5% OF STAFF", ["Intel"]), "INTEL")
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


class FetchFunnel(unittest.TestCase):
    """A fetch says what it found, dropped and kept, and which stories are new."""

    RSS = (b"<rss><channel>"
           b"<item><title>Old story - Reuters</title><source>Reuters</source>"
           b"<link>https://x/old</link><pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>"
           b"<item><title>New story - Reuters</title><source>Reuters</source>"
           b"<link>https://x/new</link><pubDate>Tue, 17 Nov 2026 10:00:00 GMT</pubDate></item>"
           b"<item><title>Blog story - Some Blog</title><source>Some Blog</source>"
           b"<link>https://x/blog</link><pubDate>Tue, 17 Nov 2026 10:00:00 GMT</pubDate></item>"
           b"</channel></rss>")

    def test_the_funnel_and_the_new_stories(self):
        import hashlib
        import shutil
        import tempfile
        from datetime import date
        from pathlib import Path
        from unittest.mock import patch
        from ews import fetch_news
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "book"
            shutil.copytree(SBI, d)
            # Google News only: the SEC feed would need its own fixture
            with (d / "trusted_sources.csv").open(newline="") as fh:
                rows = list(csv.DictReader(fh))
            for r in rows:
                if r["name"] == "sec_edgar":
                    r["enabled"] = "N"
            with (d / "trusted_sources.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            old_id = "GN-" + hashlib.sha1(b"https://x/old").hexdigest()[:12]
            with (d / "news_articles.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerow({"article_id": old_id, "published_date": "2026-11-16",
                            "publication": "Reuters", "headline": "Old story", "body": "",
                            "mentioned_entity_as_written": "", "url": "https://x/old"})
            with patch.object(fetch_news, "_get", lambda url, **kw: self.RSS), \
                    patch.object(fetch_news, "AS_OF", date(2026, 11, 19)), \
                    patch.object(fetch_news, "DATASET", "sbi"):
                rep = fetch_news.fetch(days=180, per_buyer=12, data_dir=d, quiet=True)
        buyers = len(rep["buyers"])                       # every real buyer gets the same feed
        self.assertEqual(rep["funnel"], {
            "found": 3 * buyers, "untrusted_dropped": buyers, "outside_window_or_cap": 0,
            "duplicates": 2 * buyers - 2, "kept": 2, "carried": 0})
        self.assertEqual(rep["new"], ["GN-" + hashlib.sha1(b"https://x/new").hexdigest()[:12]])

    def test_a_story_the_feed_stops_returning_is_kept_until_it_ages_out(self):
        import shutil
        import tempfile
        from datetime import date
        from pathlib import Path
        from unittest.mock import patch
        from ews import fetch_news
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "book"
            shutil.copytree(SBI, d)
            with (d / "news_articles.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                for aid, day in (("GN-yesterday", "2026-11-10"), ("GN-ancient", "2026-01-01")):
                    w.writerow({"article_id": aid, "published_date": day,
                                "publication": "Reuters", "headline": aid, "body": "",
                                "mentioned_entity_as_written": "", "url": f"https://x/{aid}"})
            with patch.object(fetch_news, "_get", lambda url, **kw: self.RSS), \
                    patch.object(fetch_news, "AS_OF", date(2026, 11, 19)), \
                    patch.object(fetch_news, "DATASET", "sbi"):
                rep = fetch_news.fetch(days=180, per_buyer=12, data_dir=d, quiet=True)
                ids = {a["article_id"] for a in fetch_news.read_articles(d)}
        self.assertIn("GN-yesterday", ids)           # not returned today, still in the window
        self.assertNotIn("GN-ancient", ids)          # older than 180 days: gone
        self.assertEqual(rep["funnel"]["carried"], 1)
        self.assertEqual(rep["articles"], rep["funnel"]["kept"] + 1)
        self.assertNotIn("GN-yesterday", rep["new"])


class AutoRefresh(unittest.TestCase):
    """The on/off switch. The fetch itself is stubbed: no test reaches the network."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        import dashboard.server as S
        from ews import user_settings
        self.S, self.us = S, user_settings
        self._saved = (dict(S.AUTO), dict(S.FETCH), S.fetch_news.fetch, S.snapshot,
                       user_settings.PATH, S.rescore)
        self.tmp = tempfile.TemporaryDirectory()
        user_settings.PATH = Path(self.tmp.name) / "settings.json"   # never the real file
        S.snapshot = S.rescore = lambda: {}
        self.calls = []

        def fake_fetch(**kw):
            self.calls.append(kw)
            return {"articles": 7, "errors": []}
        S.fetch_news.fetch = fake_fetch

    def tearDown(self):
        auto, fetch, real_fetch, snap, path, rescore = self._saved
        self.S.rescore = rescore
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

    def test_the_button_answers_at_once_and_the_page_follows_the_fetch(self):
        """A fetch that brings new stories re-scores for minutes - longer than a browser
        waits. The button starts it in the background; the page says it is running and
        reloads itself until it is done."""
        import threading
        release = threading.Event()

        def slow_rescore():
            release.wait(5)
            return {}
        self.S.rescore = slow_rescore
        self.S.start_fetch()
        self.assertTrue(self.S.AUTO["running"])
        self.assertIn("fetching and re-scoring now", self.S.auto_switch())
        self.assertIn("location.reload(), 5000", self.S.auto_switch())
        self.S.start_fetch()                                   # a second click
        self.assertIn("already running", self.S.FETCH["last"])
        release.set()
        for t in threading.enumerate():
            if t.name == "manual-fetch":
                t.join(5)
        self.assertFalse(self.S.AUTO["running"])
        self.assertEqual(len(self.calls), 1)
        self.assertIn("Scores are re-run", self.S.FETCH["last"])

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


class FetchResultPanel(unittest.TestCase):
    """After a fetch the page shows its funnel, each new story's outcome, and what moved."""

    def test_a_fetch_reports_like_a_typed_story(self):
        from unittest.mock import patch
        import dashboard.server as S
        story = {"article_id": "GN-1", "published_date": "2026-11-21", "publication": "Reuters",
                 "headline": "Intel announces job cuts", "body": "", "url": "https://x/1",
                 "mentioned_entity_as_written": "Intel"}
        buyer = {"buyer_id": "OS01", "short_name": "Intel", "evidence": [], "verdict":
                 {"score": 0.0, "band": "Healthy"}}
        after_buyer = {**buyer, "verdict": {"score": 28.0, "band": "Watch"},
                       "evidence": [{"source": "GN-1", "kind": "news", "data": {
                           "entity": "Intel Corporation", "severity": 4}}]}
        snaps = iter([{"buyers": [buyer], "refusals": []},
                      {"buyers": [after_buyer], "refusals": []}])
        rep = {"articles": 84, "errors": [], "days": 180, "new": ["GN-1"],
               "previous_fetch": "2026-11-20T12:35:39+00:00",
               "funnel": {"found": 425, "untrusted_dropped": 341, "outside_window_or_cap": 0,
                          "duplicates": 0, "kept": 84}}
        saved = dict(S.FETCH)
        try:
            with patch.object(S.fetch_news, "fetch", lambda **kw: rep), \
                    patch.object(S.fetch_news, "read_articles", lambda d: [story]), \
                    patch.object(S, "snapshot", lambda: next(snaps)), \
                    patch.object(S, "rescore", lambda: next(snaps)):
                S.refresh_news("Manual")
            html = S.fetch_result_panel()
        finally:
            S.FETCH.clear(); S.FETCH.update(saved)
        self.assertIn("425 found", html)
        self.assertIn("341 dropped", html)
        self.assertIn("<b>1 new</b> since the fetch at 2026-11-20 18:05 IST", html)
        self.assertIn("Intel announces job cuts", html)
        self.assertIn("<b>Intel Corporation</b> &middot; severity 4", html)
        self.assertIn("28.0", html)                      # the score that moved


class ResetRestoresTheNews(unittest.TestCase):
    """Reset puts the fetched news back as the dashboard started with it, so a
    rehearsal fetch does not use up the stories the demo's fetch should find."""

    def test_reset_undoes_a_fetch(self):
        import tempfile
        from pathlib import Path
        import dashboard.server as S
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "news_articles.csv").write_text("article_id\nOLD\n")
            saved = S.news_snapshot(d)
            (d / "news_articles.csv").write_text("article_id\nOLD\nNEW\n")   # a fetch
            (d / S.fetch_news.LOG).write_text("{}")                          # and its log
            self.assertTrue(S.restore_news(saved, d))
            self.assertEqual((d / "news_articles.csv").read_text(), "article_id\nOLD\n")
            self.assertFalse((d / S.fetch_news.LOG).exists())
            self.assertFalse(S.restore_news(saved, d))                       # nothing left

    def test_reset_keeps_the_fetched_news_and_its_result(self):
        from unittest.mock import patch
        import dashboard.server as S
        saved = dict(S.FETCH)
        try:
            S.FETCH.update(last="Manual fetch at 10:00 IST", result={"title": "x"})
            with patch.object(S, "LIVE_BOOK", True), \
                    patch.object(S, "restore_news", lambda saved, d: self.fail("news restored")):
                S.reset_live()
            self.assertEqual(S.FETCH["result"], {"title": "x"})
        finally:
            S.FETCH.clear(); S.FETCH.update(saved)

    def test_no_scenario_banner_on_the_live_book(self):
        """A typed story says HYPOTHETICAL wherever it appears, so the live-news book
        drops the banner that repeated it on every page; the synthetic book keeps its."""
        from unittest.mock import patch
        import dashboard.server as S
        keep = dict(S.LIVE)
        try:
            S.LIVE.update(articles=[{"article_id": "LIVE01"}], events=[], last=None)
            with patch.object(S, "LIVE_BOOK", True):
                self.assertEqual(S.live_banner(), "")
            with patch.object(S, "LIVE_BOOK", False):
                self.assertIn("Live input in play", S.live_banner())
        finally:
            S.LIVE.clear(); S.LIVE.update(keep)

    def test_reset_takes_out_only_the_score_only_inputs(self):
        import dashboard.server as S
        keep = dict(S.LIVE)
        try:
            S.LIVE.update(articles=[{"article_id": "LIVE01"},
                                    {"article_id": "LIVE02", "score_only": True}],
                          events=[{"event_id": "N-LIVE-01", "score_only": True},
                                  {"event_id": "N-LIVE-02"}],
                          last={"title": "x"})
            S.reset_live()
            self.assertEqual([a["article_id"] for a in S.LIVE["articles"]], ["LIVE01"])
            self.assertEqual([e["event_id"] for e in S.LIVE["events"]], ["N-LIVE-02"])
            self.assertIsNone(S.LIVE["last"])
        finally:
            S.LIVE.clear(); S.LIVE.update(keep)


class ClaudeForRealBuyersOnly(unittest.TestCase):
    """settings.REAL_BUYERS_ONLY: the agents run for the six real companies; the invented
    buyers and their illustrative stories get the rule-based answers."""

    def test_only_the_real_companies_reach_the_model(self):
        from unittest.mock import patch
        from ews import run as engine
        from ews.agents.runtime import AgentError
        from ews.llm import _Cache

        class ModelOffline:
            """Agentic, no cache, and fails any call that reaches the model."""
            name, agentic, disabled, degraded = "claude", True, False, 0
            api_errors = ()

            def __init__(self):
                self.cache = _Cache(False)

            def create(self, **_):
                raise AgentError("model called")

        from ews import config, settings
        # the book's own rates; config picks them by EWS_DATASET when it loads
        with patch.object(engine, "Loader", lambda **kw: Loader(SBI, **kw)), \
                patch.object(settings, "REAL_BUYERS_ONLY", True), \
                patch.dict(config.FX_TO_REPORTING, {"INR": 1.0, "USD": 93.3461}):
            out = engine.run(llm=ModelOffline())
        illustrative = {a["article_id"] for a in Loader(SBI).table("illustrative_articles")}
        reached = set()
        for r in out["buyers"]:
            runs = [e["data"]["agent"] for e in r["evidence"]
                    if e["kind"] == "payment_review"
                    or (e["kind"] == "news" and e["source"] in illustrative)]
            if r["verdict"]["review"]:
                runs.append(r["verdict"]["review"]["agent"])
            if r["verdict"]["band"] != "Healthy":
                runs.append(r["case_file"]["agent"])
            if any(run.get("error") == "model called" for run in runs):
                reached.add(r["buyer_id"])
            if not r["is_real"]:
                self.assertTrue(all(run["mode"] == "rules" for run in runs),
                                (r["short_name"], runs))
        real = {r["buyer_id"] for r in out["buyers"] if r["is_real"]}
        self.assertEqual(reached, real)


class ArticleText(unittest.TestCase):
    """Google News gives headlines only. A publisher's own feed gives its summary, and an
    8-K gives the company's own words; the agents read whichever text exists."""

    GN = (b"<rss><channel>"
          b"<item><title>Tata Motors cuts output at Pune plant - Business Standard</title>"
          b"<source>Business Standard</source><link>https://news.google.com/x/1</link>"
          b"<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>"
          b"</channel></rss>")
    FEED = (b"<rss><channel>"
            b"<item><title>Tata Motors cuts output at Pune plant</title>"
            b"<link>https://bs.example/1</link><pubDate>Mon, 16 Nov 2026 09:00:00 GMT</pubDate>"
            b"<description>Tata Motors will cut output by 20% for six weeks as dealer stocks "
            b"pile up, the company said.</description></item>"
            b"<item><title>Vodafone Idea misses a spectrum payment</title>"
            b"<link>https://bs.example/2</link><pubDate>Tue, 17 Nov 2026 09:00:00 GMT</pubDate>"
            b"<description>Vodafone Idea did not pay the instalment due on Monday.</description></item>"
            b"<item><title>Monsoon lifts tractor sales</title>"
            b"<link>https://bs.example/3</link><pubDate>Tue, 17 Nov 2026 09:00:00 GMT</pubDate>"
            b"<description>Rural demand recovered across the industry.</description></item>"
            b"</channel></rss>")

    def _fetch(self, stored=()):
        import shutil
        import tempfile
        from datetime import date
        from pathlib import Path
        from unittest.mock import patch
        from ews import fetch_news
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "book"
            shutil.copytree(SBI, d)
            with (d / "trusted_sources.csv").open(newline="") as fh:
                rows = list(csv.DictReader(fh))
            rows = [r for r in rows if r["type"] != "rss"] + [{
                "type": "rss", "name": "Business Standard", "enabled": "Y", "country": "IND",
                "notes": "", "url": "https://bs.example/rss"}]
            for r in rows:
                if r["name"] == "sec_edgar":
                    r["enabled"] = "N"
            with (d / "trusted_sources.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            with (d / "news_articles.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(stored)
            get = lambda url, **kw: self.FEED if "bs.example" in url else self.GN
            with patch.object(fetch_news, "_get", get), \
                    patch.object(fetch_news, "AS_OF", date(2026, 11, 19)), \
                    patch.object(fetch_news, "DATASET", "sbi"):
                rep = fetch_news.fetch(days=180, per_buyer=12, data_dir=d, quiet=True)
                return rep, {a["article_id"]: a for a in fetch_news.read_articles(d)}

    def test_a_headline_from_google_gets_the_publisher_s_summary(self):
        rep, arts = self._fetch()
        tata = [a for a in arts.values() if a["headline"].startswith("Tata Motors cuts")]
        self.assertEqual(len(tata), 1, "one story, not one per source")
        self.assertTrue(tata[0]["article_id"].startswith("GN-"))
        self.assertIn("20% for six weeks", tata[0]["body"])

    def test_a_feed_story_is_added_only_when_it_names_a_watched_company(self):
        rep, arts = self._fetch()
        heads = {a["headline"] for a in arts.values()}
        self.assertIn("Vodafone Idea misses a spectrum payment", heads)
        self.assertNotIn("Monsoon lifts tractor sales", heads)

    def test_a_stored_headline_keeps_its_id_when_text_arrives(self):
        stored = [{"article_id": "GN-stored", "published_date": "2026-11-16",
                   "publication": "Business Standard",
                   "headline": "Tata Motors cuts output at Pune plant",
                   "body": "Tata Motors cuts output at Pune plant",
                   "mentioned_entity_as_written": "Tata Motors", "url": "https://x/old"}]
        rep, arts = self._fetch(stored)
        self.assertIn("20% for six weeks", arts["GN-stored"]["body"])
        self.assertNotIn("GN-stored", rep["new"], "more text is not a new story")

    def test_an_8k_gives_the_company_s_own_words(self):
        from unittest.mock import patch
        from ews import fetch_news
        doc = (b"<html><body><p>Check the appropriate box ... emerging growth company</p>"
               b"<p>Item 5.02. Departure of Directors</p><p>On November 17, 2026, the Vice "
               b"Chair elected to retire.</p><p>Item 9.01 Financial Statements and Exhibits"
               b"</p><p>SIGNATURES</p></body></html>")
        with patch.object(fetch_news, "_get", lambda url, **kw: doc):
            text = fetch_news.filing_text("https://sec.example/doc.htm")
        self.assertTrue(text.startswith("Item 5.02"))
        self.assertIn("elected to retire", text)
        self.assertNotIn("9.01", text)

    def test_a_headline_that_recurs_is_a_different_story_on_a_different_day(self):
        from ews.fetch_news import same_story
        q = "The Boeing Company files Form 8-K: Results of Operations and Financial Condition"
        self.assertFalse(same_story({"headline": q, "published_date": "2026-07-28"},
                                    {"headline": q, "published_date": "2026-10-27"}))
        self.assertTrue(same_story({"headline": "Tata Motors cuts output", "published_date": "2026-11-16"},
                                   {"headline": "Tata Motors cuts output", "published_date": "2026-11-17"}))
