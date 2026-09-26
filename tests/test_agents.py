"""The agent loop and its guards, driven by a scripted client - no network, no key."""
import json
import unittest
from types import SimpleNamespace

from ews import run as engine, settings
from ews.agents import news as news_agent
from ews.agents import definition
from ews.agents.definition import AgentSpec, DefinitionError
from ews.agents.runtime import AgentError, Tool, attempt, run_agent
from ews.llm import FallbackLLM, _Cache, keyword_grade, strict_resolve
from ews.loader import Loader


def _call(name, args, n=0):
    return SimpleNamespace(type="tool_use", id=f"t{n}-{name}", name=name, input=args)


def _resp(*blocks, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


class ScriptedLLM:
    """Stands in for ClaudeLLM. `script(system, messages)` returns the next response."""
    name = "scripted"
    agentic = True
    api_errors = ()

    def __init__(self, script):
        self.script = script
        self.cache = _Cache(False)
        self.calls = self.degraded = 0
        self.requests = []

    def create(self, *, model, effort, system, tools, messages, max_tokens):
        self.calls += 1
        self.requests.append({"model": model, "effort": effort, "max_tokens": max_tokens,
                              "tools": [t["name"] for t in tools], "messages": list(messages)})
        return self.script(system, messages)


def _results(messages):
    """Tool results of the last round, parsed."""
    last = messages[-1]["content"]
    if not isinstance(last, list):
        return []
    out = []
    for r in last:
        try:
            out.append(json.loads(r["content"]))
        except (TypeError, ValueError):
            out.append(r["content"])
    return out


def policy(system, messages):
    """A well-behaved agent: investigate once, then submit what the data supports."""
    rounds = sum(1 for m in messages if m["role"] == "assistant")
    task = messages[0]["content"]
    if system.startswith("You are the News"):
        art = json.loads(task.split("\n", 1)[1])
        if rounds == 0:
            return _resp(_call("search_entities", {"name": art["mentioned_entity_as_written"]}))
        cands = [c for c in _results(messages)[0] if "id" in c]
        hit = strict_resolve(art["mentioned_entity_as_written"], cands)
        if hit is None:
            return _resp(_call("submit_assessment", {"kind": "none", "entity_id": "",
                                                     "severity": 0, "category": "none",
                                                     "reason": "no exact match"}))
        g = keyword_grade(art)
        return _resp(_call("submit_assessment", {"kind": hit["kind"], "entity_id": hit["id"],
                                                 "severity": g["severity"],
                                                 "category": g["category"], "reason": "match"}))
    if system.startswith("You are the Payment"):
        if rounds == 0:
            return _resp(_call("get_open_invoices", {}))
        open_ = [i for i in _results(messages)[0] if "invoice_id" in i]
        worst = open_[0] if open_ else {"days_past_due": 0, "invoice_id": ""}
        return _resp(_call("submit_payment_review", {
            "worst_dpd": worst["days_past_due"], "worst_invoice_id": worst["invoice_id"],
            "trend": "stable", "summary": "Reviewed.", "concerns": []}))
    if system.startswith("You are the Risk Adjudicator"):
        if rounds == 0:
            return _resp(_call("get_evidence", {"kind": "all"}))
        return _resp(_call("submit_review", {"assessment": "agree",
                                             "rationale": "The evidence supports the band.",
                                             "concerns": []}))
    if system.startswith("You are the Case File"):
        if rounds == 0:
            return _resp(_call("get_verdict", {}), _call("get_limits", {}))
        v = _results(messages)[0]
        return _resp(_call("submit_case_file", _case_file(
            f"The buyer scores {v['score']} and sits in {v['band']}.")))
    raise AssertionError("unknown agent")


def _case_file(narrative: str, **over) -> dict:
    return {"narrative": narrative, "bottom_line": "Act on the recommendation.",
            "payment_note": "Reviewed.", "news_note": "Reviewed.",
            "lifts_it": ["Settle the overdue balance."],
            "worsens_it": ["Further overdue days."], **over}


ECHO = Tool("echo", {"x": {"type": "string"}}, lambda x: {"echo": x})
SPEC = AgentSpec(name="t", title="T", description="test",
                 tools={"echo": "echo it", "submit_v": "submit"}, system="s",
                 path=definition.AGENTS_DIR / "t.md", enabled=True, model="m",
                 effort="low", max_turns=12, max_tokens=1000,
                 guardrails={"required_before_submit": []})


def _submit(accept=lambda v: v):
    return Tool("submit_v", {"v": {"type": "string"}}, lambda v: accept(v))


def _run(llm, submit=None):
    return run_agent(llm, spec=SPEC, task="go", tools=[ECHO, submit or _submit()],
                     cache_payload={})


class Loop(unittest.TestCase):
    def test_tool_result_is_fed_back_then_submit_ends_the_run(self):
        steps = iter([_resp(_call("echo", {"x": "hi"})), _resp(_call("submit_v", {"v": "done"}))])
        llm = ScriptedLLM(lambda s, m: next(steps))
        out = _run(llm)
        self.assertEqual(out["result"], "done")
        self.assertEqual(out["turns"], 2)
        self.assertEqual([t["tool"] for t in out["trace"]], ["echo", "submit_v"])
        fed_back = llm.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(json.loads(fed_back["content"]), {"echo": "hi"})

    def test_rejected_submission_is_returned_to_the_agent(self):
        def accept(v):
            if v != "good":
                raise ValueError("try again")
            return v
        steps = iter([_resp(_call("submit_v", {"v": "bad"})),
                      _resp(_call("submit_v", {"v": "good"}, 1))])
        llm = ScriptedLLM(lambda s, m: next(steps))
        out = _run(llm, _submit(accept))
        self.assertEqual(out["result"], "good")
        err = llm.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(err["is_error"])
        self.assertIn("try again", err["content"])

    def test_agent_that_never_submits_falls_back_to_rules(self):
        llm = ScriptedLLM(lambda s, m: _resp(stop="end_turn"))
        with self.assertRaises(AgentError):
            _run(llm)
        out = attempt(llm, lambda: "rules", spec=SPEC, task="go",
                      tools=[ECHO, _submit()], cache_payload={})
        self.assertEqual((out["mode"], out["result"]), ("rules-after-error", "rules"))

    def test_refusal_falls_back(self):
        llm = ScriptedLLM(lambda s, m: _resp(stop="refusal"))
        with self.assertRaises(AgentError):
            _run(llm)

    def test_no_claude_means_rules_without_a_call(self):
        out = attempt(FallbackLLM(cache=False), lambda: "rules", spec=SPEC, task="go",
                      tools=[ECHO, _submit()], cache_payload={})
        self.assertEqual(out["mode"], "rules")


class Definitions(unittest.TestCase):
    def test_every_agent_loads_from_its_md_file(self):
        for name in ("payment", "news", "adjudicator", "casefile"):
            sp = definition.load(name)
            self.assertTrue(sp.system.startswith("You are the"), name)
            self.assertTrue(sp.model.startswith("claude-"), name)
            self.assertTrue(sp.submit.startswith("submit_"), name)

    def test_placeholders_come_from_config(self):
        sp = definition.load("adjudicator")
        self.assertIn("0.65 x payment score", sp.system)
        self.assertNotIn("{", sp.system)

    def test_only_listed_tools_are_offered_in_file_order(self):
        llm = ScriptedLLM(lambda s, m: _resp(_call("submit_v", {"v": "x"})))
        extra = Tool("unlisted", {}, lambda: "never offered")
        _run_with = run_agent(llm, spec=SPEC, task="go", tools=[_submit(), extra, ECHO],
                              cache_payload={})
        self.assertEqual(_run_with["result"], "x")
        self.assertEqual(llm.requests[0]["tools"], ["echo", "submit_v"])

    def test_listing_an_unimplemented_tool_fails_loudly(self):
        with self.assertRaises(DefinitionError):
            attempt(FallbackLLM(cache=False), lambda: "rules", spec=SPEC, task="go",
                    tools=[_submit()], cache_payload={})

    def test_malformed_files_are_rejected(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        head = "---\nname: x\ntitle: X\ndescription: d\nmodel: m\nmax_turns: 3\ntools:\n"
        cases = {
            "no frontmatter": "just a prompt",
            "no submit tool": head + "  - echo: e\n---\nbody",
            "bad placeholder": head + "  - submit_x: s\n---\nuse {nope}",
        }
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(definition, "AGENTS_DIR", Path(d)):
                for label, text in cases.items():
                    (Path(d) / "x.md").write_text(text, encoding="utf-8")
                    with self.assertRaises(DefinitionError, msg=label):
                        definition.load("x")


class Settings(unittest.TestCase):
    """ews/settings.py: model, effort, limits and guardrails per agent."""

    def _with(self, name, **changes):
        import copy
        from unittest import mock
        agents = copy.deepcopy(settings.AGENTS)
        for key, value in changes.items():
            if key in agents[name]["guardrails"]:
                agents[name]["guardrails"][key] = value
            else:
                agents[name][key] = value
        return mock.patch.object(settings, "AGENTS", agents)

    def test_model_effort_and_limits_reach_the_request(self):
        with self._with("adjudicator", model="claude-sonnet-5", effort="low", max_tokens=4000):
            sp = definition.load("adjudicator")
        llm = ScriptedLLM(policy)
        run_agent(llm, spec=sp, task="Review", cache_payload={}, tools=[
            Tool("get_score_breakdown", {}, lambda: {}),
            Tool("get_evidence", {"kind": {"type": "string"}}, lambda kind: []),
            Tool("get_article", {"article_id": {"type": "string"}}, lambda article_id: {}),
            Tool("submit_review", {"assessment": {}, "rationale": {}, "concerns": {}},
                 lambda **a: a)])
        req = llm.requests[0]
        self.assertEqual((req["model"], req["effort"], req["max_tokens"]),
                         ("claude-sonnet-5", "low", 4000))

    def test_bad_values_stop_the_run(self):
        bad = [("payment", {"effort": "extreme"}), ("news", {"model": "gpt-4"}),
               ("news", {"allowed_severities": [0, 2]}), ("payment", {"max_turns": 0}),
               ("casefile", {"run_for_bands": ["Red"]}), ("payment", {"enabled": "yes"}),
               ("payment", {"required_before_submit": ["not_a_tool"]})]
        for name, change in bad:
            with self._with(name, **change), self.assertRaises(settings.SettingsError, msg=change):
                definition.load(name)

    def test_unknown_keys_are_rejected(self):
        with self._with("payment", temprature=0.5), self.assertRaises(settings.SettingsError):
            definition.load("payment")

    def test_disabled_agent_uses_rules_without_a_call(self):
        # counts come from the data, so adding a buyer or an article cannot break this
        n_buyers = len(Loader().buyers())
        n_articles = len(Loader().news())
        llm = ScriptedLLM(policy)
        with self._with("payment", enabled=False):
            out = engine.run(llm=llm)
        self.assertEqual(out["agent_runs"]["payment"], {"disabled": n_buyers})
        self.assertEqual(out["agent_runs"]["news"], {"agent": n_articles})

    def test_submitting_before_the_required_tools_is_sent_back(self):
        spec = AgentSpec(**{**SPEC.__dict__, "guardrails": {"required_before_submit": ["echo"]}})
        steps = iter([_resp(_call("submit_v", {"v": "early"})),
                      _resp(_call("echo", {"x": "a"}, 1)),
                      _resp(_call("submit_v", {"v": "late"}, 2))])
        llm = ScriptedLLM(lambda s, m: next(steps))
        out = run_agent(llm, spec=spec, task="go", tools=[ECHO, _submit()], cache_payload={})
        self.assertEqual(out["result"], "late")
        self.assertIn("call echo before submitting", out["trace"][0]["error"])

    def test_news_agent_cannot_submit_an_id_it_never_looked_up(self):
        desk = news_agent.NewsDesk(Loader())
        guard = settings.agent("news")["guardrails"]
        with self.assertRaises(ValueError):
            desk.submit("buyer", "BUY002", 5, "wage_delay", "guessed", guard=guard, seen=set())
        ok = desk.submit("buyer", "BUY002", 5, "wage_delay", "looked up", guard=guard,
                         seen={"BUY002"})
        self.assertEqual(ok["id"], "BUY002")

    def test_narrowed_severities_are_enforced(self):
        desk = news_agent.NewsDesk(Loader())
        guard = {"entity_must_be_looked_up": False, "allowed_severities": [0, 5]}
        with self.assertRaises(ValueError):
            desk.submit("buyer", "BUY002", 4, "vendor_payment_delay", "x", guard=guard)


class Guards(unittest.TestCase):
    def setUp(self):
        self.desk = news_agent.NewsDesk(Loader())

    def test_news_agent_cannot_submit_an_unregistered_entity(self):
        with self.assertRaises(ValueError):
            self.desk.submit("buyer", "BUY999", 5, "wage_delay", "made up")
        with self.assertRaises(ValueError):
            self.desk.submit("parent", "BUY002", 5, "wage_delay", "wrong kind")

    def test_news_agent_severity_must_be_on_the_ladder(self):
        with self.assertRaises(ValueError):
            self.desk.submit("buyer", "BUY002", 2, "other", "off the ladder")

    def test_payment_agent_must_match_the_ledger(self):
        from ews.agents.payment import Ledger
        ld = Loader()
        ledger = Ledger("BUY002", ld.invoices(), ld.credit_limits())
        with self.assertRaises(ValueError):
            ledger.submit(ledger.worst_dpd + 5, ledger.open[0]["invoice_id"], "stable", "", [])
        ok = ledger.submit(ledger.worst_dpd, ledger.open[0]["invoice_id"], "stable", "x", [])
        self.assertEqual(ok["trend"], "stable")


class EndToEnd(unittest.TestCase):
    def test_agents_run_everywhere_and_never_move_the_score(self):
        rules = engine.run(llm=FallbackLLM(cache=False))
        agents = engine.run(llm=ScriptedLLM(policy))
        for name, modes in agents["agent_runs"].items():
            self.assertEqual(set(modes), {"agent"}, f"{name}: {modes}")
        score = {r["buyer_id"]: (r["verdict"]["score"], r["verdict"]["band"]) for r in rules["buyers"]}
        for r in agents["buyers"]:
            self.assertEqual((r["verdict"]["score"], r["verdict"]["band"]), score[r["buyer_id"]])
        flagged = [r for r in agents["buyers"] if r["verdict"]["band"] != "Healthy"]
        self.assertTrue(flagged)
        self.assertTrue(all(r["case_file"]["source"] == "llm" for r in flagged))

    def test_invented_figure_in_a_case_file_is_sent_back(self):
        def script(system, messages):
            if not system.startswith("You are the Case File"):
                return policy(system, messages)
            rounds = sum(1 for m in messages if m["role"] == "assistant")
            if rounds == 0:
                return _resp(_call("get_verdict", {}), _call("get_limits", {}))
            if rounds == 1:
                return _resp(_call("submit_case_file", _case_file("It scores 99.9 today."), 1))
            v = json.loads(messages[2]["content"][0]["content"])
            return _resp(_call("submit_case_file",
                               _case_file(f"It scores {v['score']} today."), 2))

        out = engine.run(llm=ScriptedLLM(script))
        cf = next(r["case_file"] for r in out["buyers"] if r["verdict"]["band"] != "Healthy")
        self.assertEqual(cf["source"], "llm")
        rejected = [t for t in cf["agent"]["trace"] if "error" in t]
        self.assertTrue(rejected and "99.9" in rejected[0]["error"])

    def test_case_file_has_fields_and_narrative_on_both_paths(self):
        for llm in (FallbackLLM(cache=False), ScriptedLLM(policy)):
            for r in engine.run(llm=llm)["buyers"]:
                cf, v = r["case_file"], r["verdict"]
                self.assertTrue(cf["narrative"].strip())
                f = cf["fields"]
                self.assertEqual((f["header"]["score"], f["header"]["band"]), (v["score"], v["band"]))
                self.assertEqual(f["score_trace"], v["trace"])
                self.assertEqual([l["revised_limit"] for l in f["limit_actions"]],
                                 [l["revised_limit"] for l in r["limits"]])
                self.assertEqual([d["points"] for d in f["drivers"]],
                                 [v["payment"]["weighted"], v["news"]["weighted"]])
                self.assertTrue(f["bottom_line"] and f["lifts_it"] and f["worsens_it"])

    def test_invented_figure_in_a_judgement_field_is_sent_back(self):
        def script(system, messages):
            if not system.startswith("You are the Case File"):
                return policy(system, messages)
            rounds = sum(1 for m in messages if m["role"] == "assistant")
            if rounds == 0:
                return _resp(_call("get_verdict", {}), _call("get_limits", {}))
            if rounds == 1:
                return _resp(_call("submit_case_file", _case_file(
                    "Fine.", worsens_it=["Moves up at 77.7 days."]), 1))
            return _resp(_call("submit_case_file", _case_file("Fine."), 2))

        out = engine.run(llm=ScriptedLLM(script))
        cf = next(r["case_file"] for r in out["buyers"] if r["verdict"]["band"] != "Healthy")
        self.assertEqual(cf["source"], "llm")
        self.assertEqual(cf["fields"]["worsens_it"], ["Further overdue days."])
        rejected = [t for t in cf["agent"]["trace"] if "error" in t]
        self.assertTrue(rejected and "77.7" in rejected[0]["error"])


class Outlook(unittest.TestCase):
    def test_dpd_trigger_reaches_the_next_band(self):
        from ews.casefile import outlook
        from ews.config import W_NEWS, W_PAYMENT, band, payment_score
        for r in engine.run(llm=FallbackLLM(cache=False))["buyers"]:
            v = r["verdict"]
            o = outlook(v)
            if o["dpd_for_next_band"] is None:
                continue
            news = v["news"]["raw"]
            at = o["dpd_for_next_band"]
            self.assertEqual(band(W_PAYMENT * payment_score(at) + W_NEWS * news), o["next_band"])
            if at > 0:
                self.assertNotEqual(band(W_PAYMENT * payment_score(at - 1) + W_NEWS * news),
                                    o["next_band"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class CallBudget(unittest.TestCase):
    """The run-wide spend cap, tested on the real client with its transport stubbed."""

    def _client(self, budget):
        from ews.llm import ClaudeLLM
        llm = ClaudeLLM.__new__(ClaudeLLM)          # skip __init__; no SDK, no key
        llm.calls = llm.degraded = 0
        llm.disabled = False
        llm.usage = {}
        llm.cache = _Cache(False)
        llm.client = type("C", (), {"messages": type("M", (), {
            "create": staticmethod(lambda **kw: "ok")})()})()
        settings.MAX_MODEL_CALLS = budget
        return llm

    def setUp(self):
        self._original = settings.MAX_MODEL_CALLS

    def tearDown(self):
        settings.MAX_MODEL_CALLS = self._original

    def test_calls_under_the_budget_go_through(self):
        llm = self._client(3)
        for _ in range(3):
            llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        self.assertEqual(llm.calls, 3)
        self.assertFalse(llm.disabled)

    def test_the_call_over_the_budget_raises_and_disables(self):
        llm = self._client(2)
        llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        with self.assertRaises(AgentError):
            llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        self.assertTrue(llm.disabled, "budget must switch the client off, not just fail once")
        self.assertEqual(llm.calls, 2, "the refused call must not be billed")

    def test_a_disabled_client_short_circuits_before_any_request(self):
        llm = self._client(1)
        llm.disabled = True
        with self.assertRaises(AgentError):
            run_agent(llm, spec=SPEC, task="go", tools=[ECHO, _submit()], cache_payload={})
        self.assertEqual(llm.calls, 0, "a disabled client must not reach the network")


class UsageAccounting(unittest.TestCase):
    """A call budget is a crude proxy for spend; this measures the real thing."""

    def _client(self):
        from ews.llm import ClaudeLLM
        from ews.llm import _Cache as C
        llm = ClaudeLLM.__new__(ClaudeLLM)
        llm.calls = llm.degraded = 0
        llm.disabled = False
        llm.usage = {}
        llm.cache = C(False)

        class U:
            input_tokens, output_tokens, cache_read_input_tokens = 1000, 200, 0

        class R:
            usage = U()
        msgs = type("M", (), {"create": staticmethod(lambda **kw: R())})()
        # opus-5 goes through the beta endpoint for refusal fallback, so stub both
        llm.client = type("C", (), {"messages": msgs,
                                    "beta": type("B", (), {"messages": msgs})()})()
        return llm

    def setUp(self):
        self._tok, self._calls = settings.MAX_MODEL_TOKENS, settings.MAX_MODEL_CALLS

    def tearDown(self):
        settings.MAX_MODEL_TOKENS, settings.MAX_MODEL_CALLS = self._tok, self._calls

    def test_tokens_are_recorded_per_model(self):
        llm = self._client()
        llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        llm.create(model="claude-opus-5", effort="low", messages=[], max_tokens=16)
        self.assertEqual(llm.usage["claude-sonnet-5"]["input"], 1000)
        self.assertEqual(llm.usage["claude-opus-5"]["output"], 200)
        self.assertEqual(llm.total_tokens(), 2400)

    def test_cost_uses_the_published_price_for_each_model(self):
        llm = self._client()
        llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        sp = llm.spend()
        # 1000 in at $2/MTok + 200 out at $10/MTok
        self.assertAlmostEqual(sp["by_model"]["claude-sonnet-5"]["usd"], 0.004, places=4)

    def test_an_unpriced_model_is_never_reported_as_cheap(self):
        llm = self._client()
        llm.create(model="claude-something-new", effort="low", messages=[], max_tokens=16)
        cheapest = min(p[0] for p in settings.PRICING.values())
        self.assertGreater(llm.spend()["total_usd"], 1000 / 1e6 * cheapest)

    def test_the_token_budget_disables_the_client(self):
        from ews.agents.runtime import AgentError
        llm = self._client()
        settings.MAX_MODEL_TOKENS = 1000          # one call spends 1200
        llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        with self.assertRaises(AgentError):
            llm.create(model="claude-sonnet-5", effort="low", messages=[], max_tokens=16)
        self.assertTrue(llm.disabled)
