"""Local multi-page dashboard. Home > Client > Buyer, plus the live demo panel.

    python -m dashboard.server        then open http://localhost:8000
"""
from __future__ import annotations

import html
import json
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ews import run as engine
from ews.agents import definition

HERE = Path(__file__).resolve().parent
BANNER = "HACKATHON PROTOTYPE &middot; SYNTHETIC DATA"

DEMO_STEPS = [
    "Chandra Mills appoints new plant head (severity 0)",
    "Indus Crest scales back operations (severity 3)",
    "Vendors say Lakshya has fallen behind on payments (severity 4)",
    "Workers at Oakhurst protest over delayed wages (severity 5)",
    "Udaan LOGISTICS wage protest - a decoy, must be refused",
    "Workers at Udaan TRADERS protest over delayed wages (severity 5)",
    "Northpoint parent in restructuring talks - fans out to two subsidiaries",
]
SWAP_STEP = "Payment data updates: Udaan moves from 25 to 40 days past due"

STATE = {"step": 0, "swap": False}
_CACHE: dict[tuple[int, bool], dict] = {}


def snapshot() -> dict:
    key = (STATE["step"], STATE["swap"])
    if key not in _CACHE:
        _CACHE[key] = engine.run(demo_steps=key[0], swap_invoices=key[1])
    return _CACHE[key]


# ---------------------------------------------------------------- helpers
def e(x) -> str:
    return html.escape(str(x))


def money(v: float) -> str:
    v = float(v)
    if abs(v) >= 1e7:
        return f"&#8377;{v/1e7:,.2f} Cr"
    if abs(v) >= 1e5:
        return f"&#8377;{v/1e5:,.1f} L"
    return f"&#8377;{v:,.0f}"


def band_pill(band: str) -> str:
    cls = {"High Risk": "high", "Watch": "watch", "Healthy": "healthy"}[band]
    return f'<span class="pill {cls}">{e(band)}</span>'


def action_pill(action: str) -> str:
    return f'<span class="pill {action.lower()}">{e(action)}</span>'


def gauge(score: float, band: str) -> str:
    """Semicircle dial, 0-100, with tick marks at the band lines (D8)."""
    import math
    from ews.config import BAND_HIGH, BAND_WATCH

    cx, cy, r = 150, 150, 110

    def pt(s: float, rad: float = r) -> tuple[float, float]:
        a = math.pi * (1 - s / 100)
        return cx + rad * math.cos(a), cy - rad * math.sin(a)

    cls = {"High Risk": "high", "Watch": "watch", "Healthy": "healthy"}[band]
    s = max(0.0, min(100.0, float(score)))
    x, y = pt(s)
    fill = (f'<path class="g-fill {cls}" d="M {cx-r} {cy} A {r} {r} 0 0 1 {x:.1f} {y:.1f}"/>'
            if s > 0 else "")
    ticks = ""
    for t in (BAND_WATCH, BAND_HIGH):
        (x1, y1), (x2, y2), (lx, ly) = pt(t, r - 26), pt(t, r + 26), pt(t, r + 40)
        ticks += (f'<line class="g-tick" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'
                  f'<text class="g-lab" x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle">{t:g}</text>')
    legend = "".join(f'<span><i class="dot {c}"></i>{k} <em>{rng}</em></span>' for k, c, rng in [
        ("Healthy", "healthy", f"0&ndash;{BAND_WATCH:g}"),
        ("Watch", "watch", f"{BAND_WATCH:g}&ndash;{BAND_HIGH:g}"),
        ("High Risk", "high", f"{BAND_HIGH:g}&ndash;100")])
    return f"""<div class="gauge">
<svg viewBox="0 0 300 208" role="img" aria-label="Risk score {s:g} of 100, {e(band)}">
<path class="g-track" d="M {cx-r} {cy} A {r} {r} 0 0 1 {cx+r} {cy}"/>
{fill}{ticks}
<circle class="g-hub" cx="{cx}" cy="{cy}" r="52"/>
<text class="g-num" x="{cx}" y="{cy+12}" text-anchor="middle">{s:g}</text>
<text class="g-end" x="{cx-r}" y="{cy+20}" text-anchor="middle">0</text>
<text class="g-end" x="{cx+r}" y="{cy+20}" text-anchor="middle">100</text>
</svg>
<div class="g-current">Current: <b class="{cls}">{e(band)}</b></div>
<div class="g-legend">{legend}</div></div>"""


def mini_gauge(score: float, band: str) -> str:
    """Table-sized version of gauge(): the same dial, number underneath."""
    import math
    from ews.config import BAND_HIGH, BAND_WATCH

    cx, cy, r = 40, 38, 30
    cls = {"High Risk": "high", "Watch": "watch", "Healthy": "healthy"}[band]
    s = max(0.0, min(100.0, float(score)))

    def pt(v: float, rad: float = r) -> tuple[float, float]:
        a = math.pi * (1 - v / 100)
        return cx + rad * math.cos(a), cy - rad * math.sin(a)

    x, y = pt(s)
    fill = (f'<path class="g-fill {cls}" d="M {cx-r} {cy} A {r} {r} 0 0 1 {x:.1f} {y:.1f}"/>'
            if s > 0 else "")
    ticks = "".join(
        '<line class="g-tick" x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}"/>'.format(
            *pt(t, r - 8), *pt(t, r + 8)) for t in (BAND_WATCH, BAND_HIGH))
    return (f'<svg class="mini-gauge" viewBox="0 0 80 46" role="img" '
            f'aria-label="Risk score {s:g} of 100, {e(band)}">'
            f'<path class="g-track" d="M {cx-r} {cy} A {r} {r} 0 0 1 {cx+r} {cy}"/>'
            f'{fill}{ticks}<text class="g-num" x="{cx}" y="{cy+1}" text-anchor="middle">{s:g}</text>'
            f'</svg>')


def page(title: str, body: str, theme: str = "") -> bytes:
    attr = f' data-theme="{e(theme)}"' if theme else ""
    return f"""<!doctype html>
<html lang="en"{attr}><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>[PROTOTYPE] {e(title)} &middot; Synthetic Data</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/theme.css">
</head><body>
<div class="banner">{BANNER}</div>
<div class="wrap">{body}
<footer>
  <b>{BANNER}</b><br>
  Every buyer, insurer, invoice and news article here is fabricated. No real counterparty appears.
  Not reviewed by Risk or Compliance, and not a product.<br>
  Design tokens copied from TCS-Frontend; insurers without a published variation fall back to
  the default theme. Built {date.today().isoformat()}.
</footer>
</div></body></html>""".encode()


def crumbs(*parts) -> str:
    out = []
    for label, href in parts:
        out.append(f'<a href="{href}">{e(label)}</a>' if href else e(label))
    return f'<div class="crumb">{" &rsaquo; ".join(out)}</div>'


def demo_panel() -> str:
    rows = []
    for i, text in enumerate(DEMO_STEPS, 1):
        cls = "done" if i <= STATE["step"] else ("next" if i == STATE["step"] + 1 else "")
        mark = "&#10003;" if i <= STATE["step"] else f"{i}."
        rows.append(f'<div class="step {cls}">{mark} {e(text)}</div>')
    swap_cls = "done" if STATE["swap"] else ("next" if STATE["step"] == 7 else "")
    rows.append(f'<div class="step {swap_cls}">'
                f'{"&#10003;" if STATE["swap"] else "8."} {e(SWAP_STEP)}</div>')

    if STATE["step"] < 7:
        nxt = f'<a class="btn" href="/demo/next">Publish article {STATE["step"]+1}</a>'
    elif not STATE["swap"]:
        nxt = '<a class="btn" href="/demo/next">Update payment data</a>'
    else:
        nxt = '<span class="overline">demo complete</span>'
    return (f'<div class="demo"><h4>Live demo &mdash; step {STATE["step"] + (1 if STATE["swap"] else 0)} of 8</h4>'
            f'<p class="body2" style="color:var(--theme-neutral-500);margin:.25rem 0 .75rem">'
            f'Each step appends one article or updates payment data, then re-runs the engine.</p>'
            f'{"".join(rows)}<div style="margin-top:.9rem;display:flex;gap:.5rem">'
            f'{nxt}<a class="btn ghost" href="/demo/reset">Reset</a></div></div>')


# ---------------------------------------------------------------- pages
def action_counts(data: dict, cid: str) -> dict[str, int]:
    counts = {"FREEZE": 0, "REDUCE": 0}
    for r in data["buyers"]:
        for l in r["limits"]:
            if l["client_id"] == cid and l["action"] in counts:
                counts[l["action"]] += 1
    return counts


def home() -> bytes:
    data = snapshot()
    cards = []
    for c in data["clients"]:
        b = c["bands"]
        acts = action_counts(data, c["client_id"])
        bands = " ".join(f'{band_pill(k)} <b>{b.get(k, 0)}</b>'
                         for k in ("High Risk", "Watch", "Healthy"))
        cards.append(f"""<a class="card" href="/client/{e(c['client_id'])}">
<h4>{e(c['client_name'])}</h4>
<div class="overline">{e(c['city'])}</div>
<div class="metric"><span>Buyers</span><b>{c['buyers']}</b></div>
<div class="metric"><span>Bands</span><span class="bands">{bands}</span></div>
<div class="metric"><span>Expected loss</span><b>{money(c['expected_loss'])}</b></div>
<div class="metric"><span>Actions pending</span><b>{c['actions_pending']}
<span class="overline">({acts['FREEZE']} FREEZE + {acts['REDUCE']} REDUCE)</span></b></div></a>""")

    return page("Buyer Early Warning", f"""
{crumbs(("Home", None))}
<h1>Buyer Early Warning</h1>
<p class="sub">As of {e(data['as_of'])} &middot; scoring engine: {e(data['llm'])}
&middot; {len(data['buyers'])} buyers across {len(data['clients'])} insurers
&middot; <a href="/demo">Live demo &rsaquo;</a></p>
<div class="cards">{"".join(cards)}</div>""")


def demo_page() -> bytes:
    data = snapshot()
    flagged = [r for r in data["buyers"] if r["verdict"]["band"] != "Healthy"]
    rows = "".join(
        f'<tr><td><a href="/buyer/{e(r["buyer_id"])}">{e(r["short_name"])}</a></td>'
        f'<td class="num">{r["verdict"]["score"]}</td><td>{band_pill(r["verdict"]["band"])}</td>'
        f'<td class="num">{r["verdict"]["payment"]["dpd"]}</td>'
        f'<td>{e(r["verdict"]["news"]["headline"] or "-")}</td></tr>'
        for r in flagged)
    brief = (f'<h2>Today&rsquo;s brief</h2><table><thead><tr><th>Buyer</th>'
             f'<th class="num">Score</th><th>Band</th><th class="num">DPD</th>'
             f'<th>Strongest news</th></tr></thead><tbody>{rows}</tbody></table>'
             if flagged else '<h2>Today&rsquo;s brief</h2><div class="panel">Nothing flagged.</div>')

    refused = "".join(
        f'<tr><td>{e(x["data"]["mention"])}</td><td>{e(x["data"]["headline"])}</td>'
        f'<td><span class="pill refused">refused</span></td></tr>'
        for x in data["refusals"])
    ref_block = (f'<h2>Articles refused by entity resolution</h2><table><thead><tr>'
                 f'<th>Named in the article</th><th>Headline</th><th></th></tr></thead>'
                 f'<tbody>{refused}</tbody></table>') if refused else ""

    return page("Live demo", f"""
{crumbs(("Home", "/"), ("Live demo", None))}
<h1>Live demo</h1>
<p class="sub">As of {e(data['as_of'])} &middot; scoring engine: {e(data['llm'])}</p>
{demo_panel()}
{brief}
{ref_block}""")


def client_page(cid: str) -> bytes:
    data = snapshot()
    client = next((c for c in data["clients"] if c["client_id"] == cid), None)
    if client is None:
        return page("Not found", "<h1>Unknown insurer</h1>")
    mine = [r for r in data["buyers"] if any(l["client_id"] == cid for l in r["limits"])]
    mine.sort(key=lambda r: -sum(l["expected_loss_before"] for l in r["limits"]
                                 if l["client_id"] == cid))
    rows = []
    for r in mine:
        line = next(l for l in r["limits"] if l["client_id"] == cid)
        v = r["verdict"]
        news = v["news"]
        label = "&mdash;" if not news["severity"] else (
            f'sev {news["severity"]} {e(news["category"])}'
            + (" (parent)" if news["via_parent"] else ""))
        rank = {"High Risk": 0, "Watch": 1, "Healthy": 2}[v["band"]]
        act_rank = {"FREEZE": 0, "REDUCE": 1}.get(line["action"], 2)
        rows.append(
            f'<tr data-band="{e(v["band"])}">'
            f'<td data-v="{e(r["short_name"].lower())}"><a href="/buyer/{e(r["buyer_id"])}">{e(r["short_name"])}</a><br>'
            f'<span class="overline">{e(r["sector"])}</span></td>'
            f'<td class="num" data-v="{v["score"]}">{mini_gauge(v["score"], v["band"])}</td>'
            f'<td class="num" data-v="{v["payment"]["raw"]}">{v["payment"]["raw"]}</td>'
            f'<td class="num" data-v="{v["news"]["raw"]}">{v["news"]["raw"]}</td>'
            f'<td data-v="{rank}">{band_pill(v["band"])}</td>'
            f'<td class="num" data-v="{v["payment"]["dpd"]}">{v["payment"]["dpd"]}</td>'
            f'<td data-v="{news["severity"] or 0}">{label}</td>'
            f'<td class="num" data-v="{line["expected_loss_before"]}">{money(line["expected_loss_before"])}</td>'
            f'<td data-v="{act_rank}">{action_pill(line["action"])}</td></tr>')

    b = client["bands"]
    chips = "".join(
        f'<button class="chip{" on" if k == "All" else ""}" data-band="{k}">{k} '
        f'<span>{client["buyers"] if k == "All" else b.get(k, 0)}</span></button>'
        for k in ("All", "High Risk", "Watch", "Healthy"))
    # numeric columns sort highest-first on the first click; text columns A-Z
    heads = "".join(
        f'<th class="sortable{" num" if num and i != 6 else ""}{" desc" if i == 7 else ""}" '
        f'data-col="{i}" data-num="{int(num)}">{label}</th>'
        for i, (label, num) in enumerate([
            ("Buyer", False), ("Risk Score", True), ("Payment Score", True),
            ("News Score", True), ("Band", False), ("DPD", True),
            ("Worst news", True), ("Expected loss", True), ("Recommended action", False)]))

    return page(client["client_name"], f"""
{crumbs(("Home", "/"), (client["client_name"], None))}
<h1>{e(client["client_name"])}</h1>
<p class="sub">{client['buyers']} buyers &middot; {money(client['expected_loss'])} expected loss
&middot; {client['actions_pending']} actions pending. This insurer sees only its own buyers.</p>
<div class="chips">{chips}</div>
<table id="buyers"><thead><tr>{heads}</tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<script>
(() => {{
  const tbody = document.querySelector('#buyers tbody');
  const heads = document.querySelectorAll('#buyers th.sortable');
  heads.forEach(th => th.addEventListener('click', () => {{
    const col = +th.dataset.col, num = th.dataset.num === '1';
    const wasDesc = th.classList.contains('desc'), wasAsc = th.classList.contains('asc');
    const desc = wasAsc || wasDesc ? !wasDesc : num;
    heads.forEach(h => h.classList.remove('asc', 'desc'));
    th.classList.add(desc ? 'desc' : 'asc');
    const key = tr => {{ const v = tr.children[col].dataset.v; return num ? +v : v; }};
    [...tbody.rows].sort((a, b) => {{
      const x = key(a), y = key(b), c = x < y ? -1 : x > y ? 1 : 0;
      return desc ? -c : c;
    }}).forEach(tr => tbody.appendChild(tr));
  }}));
  document.querySelectorAll('.chip').forEach(chip => chip.addEventListener('click', () => {{
    document.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c === chip));
    const band = chip.dataset.band;
    [...tbody.rows].forEach(tr => tr.hidden = band !== 'All' && tr.dataset.band !== band);
  }}));
}})();
</script>""", theme=cid)


MODE_LABEL = {"agent": "Claude agent", "rules": "rule-based",
              "rules-after-error": "fell back to rules", "disabled": "off in settings.py"}
ASSESS_LABEL = {"agree": "agrees", "agree_with_caveats": "agrees, with caveats",
                "challenge": "challenges the band"}


def mode_pill(run: dict | None) -> str:
    if not run:
        return '<span class="pill maintain">not run</span>'
    cls = {"agent": "agent", "rules": "maintain", "rules-after-error": "reduce",
           "disabled": "maintain"}[run["mode"]]
    extra = ""
    if run["mode"] == "agent":
        extra = f' &middot; {run["turns"]} turn{"s" if run["turns"] != 1 else ""}' + (
            " &middot; replayed from cache" if run["cached"] else "")
    return (f'<span class="pill {cls}">{MODE_LABEL[run["mode"]]}</span>'
            f'<span class="overline">{extra}</span>')


def trace_list(run: dict | None) -> str:
    if not run:
        return ""
    if run.get("error"):
        return f'<p class="overline">Error: {e(run["error"])}</p>'
    if not run["trace"]:
        return ""
    items = []
    for t in run["trace"]:
        args = ", ".join(f"{k}={json.dumps(val)}" for k, val in t["input"].items())
        body = (f'<span class="err">rejected: {e(t["error"])}</span>' if "error" in t else
                f'<span class="res">{e(t.get("result", ""))}</span>' if "result" in t else
                '<span class="res">submitted</span>')
        items.append(f'<li><code>{e(t["tool"])}({e(args)})</code>{body}</li>')
    return f'<ol class="agent-trace">{"".join(items)}</ol>'


def review_block(rv: dict | None) -> str:
    if not rv:
        return ""
    cls = {"agree": "healthy", "agree_with_caveats": "watch", "challenge": "high"}[rv["assessment"]]
    concerns = "".join(f'<li><b>{e(c["source_id"])}</b> &mdash; {e(c["issue"])}</li>'
                       for c in rv["concerns"])
    return (f'<h3>Adjudicator review</h3><p><span class="pill {cls}">'
            f'{ASSESS_LABEL[rv["assessment"]]}</span> {mode_pill(rv["agent"])}</p>'
            f'<p class="body2">{e(rv["rationale"])}</p>'
            + (f'<ul class="body2">{concerns}</ul>' if concerns else "")
            + '<p class="overline">The review cannot change the score; a challenge goes to '
              'the underwriter alongside it.</p>')


def agents_tab(r: dict, data: dict) -> str:
    v = r["verdict"]
    pay = next((x for x in r["evidence"] if x["kind"] == "payment_review"), None)
    news = [x for x in r["evidence"] if x["kind"] in ("news", "parent")]
    refused = [x for x in data["refusals"]
               if r["short_name"].split()[0].upper() in x["data"]["mention"].upper()]
    cf = r["case_file"]

    specs = {n: definition.load(n) for n in ("payment", "news", "adjudicator", "casefile")}

    def card(n: int, name: str, run: dict | None, conclusion: str, suffix: str = "",
             role: str | None = None) -> str:
        sp = specs[name]
        return (f'<div class="panel agent-card"><h3>{n} &middot; {e(sp.title)}{suffix}</h3>'
                f'<p class="overline">{e(role or sp.description)}</p>'
                f'<p class="overline">{e(sp.model)} &middot; effort {e(sp.effort)} &middot; '
                f'agents/{e(sp.path.name)} &middot; ews/settings.py</p><p>{mode_pill(run)}</p>'
                f'<p class="body2">{conclusion}</p>{trace_list(run)}</div>')

    out = [card(1, "payment", pay["data"]["agent"] if pay else None,
                (f'Trend: <b>{e(pay["data"]["trend"].replace("_", " "))}</b>. {e(pay["data"]["summary"])}'
                 + "".join(f"<br>&bull; {e(c)}" for c in pay["data"]["concerns"])) if pay
                else "No invoices for this buyer.")]
    if news or refused:
        for x in news + refused:
            d = x["data"]
            if x["kind"] == "resolution":
                concl = f'Refused &ldquo;{e(d["mention"])}&rdquo;: {e(d.get("reason", ""))}'
            else:
                concl = (f'Matched to {e(d["entity"])}{" (parent)" if d["via_parent"] else ""}, '
                         f'severity {d.get("parent_severity", d["severity"])} '
                         f'({e(d["category"])}). {e(d.get("reason", ""))}')
            out.append(card(2, "news", d.get("agent"), concl,
                            suffix=f' &mdash; {e(x["source"])}', role=d["headline"]))
    else:
        out.append(card(2, "news", None, "No article was matched to this buyer."))
    rv = v.get("review")
    out.append(card(3, "adjudicator", rv["agent"] if rv else None,
                    (f'{ASSESS_LABEL[rv["assessment"]].capitalize()}. {e(rv["rationale"])}'
                     if rv else "Nothing to review.")))
    out.append(card(4, "casefile", cf.get("agent"),
                    "Written by the agent." if cf["source"] == "llm" else
                    ("Healthy buyers get the template." if v["band"] == "Healthy"
                     else "Template rendered.")))
    return "".join(out)


def buyer_page(bid: str, tab: str) -> bytes:
    data = snapshot()
    r = next((x for x in data["buyers"] if x["buyer_id"] == bid), None)
    if r is None:
        return page("Not found", "<h1>Unknown buyer</h1>")
    v, cid = r["verdict"], (r["limits"][0]["client_id"] if r["limits"] else "")
    client_name = r["limits"][0]["client_name"] if r["limits"] else "&mdash;"

    tabs = "".join(
        f'<a class="{"on" if tab==t else ""}" href="/buyer/{e(bid)}?tab={t}">{label}</a>'
        for t, label in [("case", "Case File"), ("score", "Score"), ("limit", "Limit"),
                         ("payments", "Payments"), ("news", "News"), ("agents", "Agents")])

    if tab == "case":
        cf = r["case_file"]
        paras = "".join(f"<p>{e(p)}</p>" for p in cf["text"].split("\n\n") if p.strip())
        note = (f'<p class="overline">Written by {"the Case File agent" if cf["source"]=="llm" else "template"}'
                + (f'; model output discarded &mdash; unverifiable figures {cf["rejected_numbers"]}'
                   if cf["rejected_numbers"] else "") + "</p>")
        inner = f'<div class="panel case">{paras}{note}</div>'

    elif tab == "score":
        n = v["news"]
        src = ("&mdash;" if not n["severity"] else
               f'{e(n["headline"])}<br><span class="overline">{e(n["article_id"])} &middot; '
               f'{n["age_days"]} days old &middot; severity {n["severity"]}'
               + (f' &middot; via parent {e(n["parent_name"])}' if n["via_parent"] else "") + "</span>")
        inner = f"""<div class="panel">
{gauge(v['score'], v['band'])}
<div class="trace">{e(v['trace'])}</div>
<h3>Payment &mdash; weight 0.65</h3><dl class="kv">
<dt>Worst open invoice</dt><dd>{v['payment']['dpd']} days past due</dd>
<dt>Payment score</dt><dd>{v['payment']['raw']}</dd>
<dt>Contribution</dt><dd>{v['payment']['weighted']}</dd></dl>
<h3>News &mdash; weight 0.35</h3><dl class="kv">
<dt>Strongest article</dt><dd>{src}</dd>
<dt>News score after decay</dt><dd>{n['raw']}</dd>
<dt>Contribution</dt><dd>{n['weighted']}</dd></dl>
<h3>Probability of default</h3><dl class="kv">
<dt>PD from score</dt><dd>{v['pd']*100:.1f}%</dd></dl>
{review_block(v.get("review"))}</div>"""

    elif tab == "limit":
        if not r["limits"]:
            inner = '<div class="panel">No credit limit lines.</div>'
        else:
            rows = "".join(
                f'<tr><td>{e(l["client_name"])}</td><td class="num">{money(l["current_limit"])}</td>'
                f'<td class="num">{money(l["owed"])}</td><td class="num">{money(l["revised_limit"])}</td>'
                f'<td>{action_pill(l["action"])}<br><span class="overline">{e(l["reason"])}</span></td>'
                f'<td class="num">{money(l["expected_loss_before"])} &rarr; {money(l["expected_loss_after"])}</td>'
                f'</tr>' for l in r["limits"])
            inner = (f'<table><thead><tr><th>Insurer</th><th class="num">Current limit</th>'
                     f'<th class="num">Owed</th><th class="num">Revised</th><th>Action</th>'
                     f'<th class="num">Expected loss</th></tr></thead><tbody>{rows}</tbody></table>'
                     f'<p class="overline">Every recommendation awaits an underwriter. '
                     f'Limits are never raised and never cut below what is already owed.</p>')

    elif tab == "payments":
        ev = [x for x in r["evidence"] if x["kind"] == "payment"]
        rows = "".join(
            f'<tr><td>{e(x["data"]["client_id"])}</td><td class="num">{x["data"]["open_count"]}</td>'
            f'<td class="num">{money(x["data"]["owed"])}</td>'
            f'<td class="num">{x["data"]["dpd"]}</td><td>{e(x["source"])}<br>'
            f'<span class="overline">due {e(x["date"])}</span></td></tr>' for x in ev)
        inner = (f'<table><thead><tr><th>Insurer</th><th class="num">Open invoices</th>'
                 f'<th class="num">Owed</th><th class="num">Worst DPD</th><th>Worst invoice</th>'
                 f'</tr></thead><tbody>{rows}</tbody></table>'
                 if rows else '<div class="panel">No open invoices.</div>')

    elif tab == "agents":
        inner = agents_tab(r, data)

    else:  # news
        ev = [x for x in r["evidence"] if x["kind"] in ("news", "parent")]
        ev.sort(key=lambda x: x["date"], reverse=True)
        rows = "".join(
            f'<tr><td>{e(x["date"])}</td><td>{e(x["data"]["headline"])}<br>'
            f'<span class="overline">{e(x["data"]["publication"])} &middot; matched to '
            f'{e(x["data"]["entity"])}{" (parent)" if x["data"]["via_parent"] else ""}</span></td>'
            f'<td class="num">{x["data"]["severity"]}</td>'
            f'<td class="num">{x["data"]["age_days"]}d</td>'
            f'<td class="num">{x["data"]["base"]:.0f} &rarr; {x["data"]["decayed"]:.1f}</td></tr>'
            for x in ev)
        refused = "".join(
            f'<tr><td>{e(x["date"])}</td><td>{e(x["data"]["headline"])}<br>'
            f'<span class="overline">named {e(x["data"]["mention"])}</span></td>'
            f'<td colspan="3"><span class="pill refused">refused</span></td></tr>'
            for x in data["refusals"]
            if r["short_name"].split()[0].upper() in x["data"]["mention"].upper())
        inner = (f'<table><thead><tr><th>Date</th><th>Article</th><th class="num">Severity</th>'
                 f'<th class="num">Age</th><th class="num">Base &rarr; decayed</th></tr></thead>'
                 f'<tbody>{rows}{refused}</tbody></table>'
                 if rows or refused else '<div class="panel">No news matched to this buyer.</div>')

    return page(r["buyer_name"], f"""
{crumbs(("Home", "/"), (client_name, f"/client/{cid}"), (r["short_name"], None))}
<h1>{e(r["buyer_name"])}</h1>
<p class="sub">{e(r["sector"])} &middot; {e(r["city"])} &middot; score {v['score']} {band_pill(v['band'])}</p>
<div class="tabs">{tabs}</div>{inner}""", theme=cid)


# ---------------------------------------------------------------- routing
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # quiet
        pass

    def _send(self, body: bytes, ctype="text/html; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):                 # noqa: N802
        url = urllib.parse.urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = urllib.parse.parse_qs(url.query)

        if url.path == "/theme.css":
            return self._send((HERE / "theme.css").read_bytes(), "text/css; charset=utf-8")
        if url.path == "/":
            return self._send(home())
        if url.path == "/demo":
            return self._send(demo_page())
        if parts[:1] == ["client"] and len(parts) == 2:
            return self._send(client_page(parts[1]))
        if parts[:1] == ["buyer"] and len(parts) == 2:
            return self._send(buyer_page(parts[1], query.get("tab", ["case"])[0]))
        if url.path == "/demo/next":
            if STATE["step"] < 7:
                STATE["step"] += 1
            elif not STATE["swap"]:
                STATE["swap"] = True
            return self._redirect("/demo")
        if url.path == "/demo/reset":
            STATE.update(step=0, swap=False)
            return self._redirect("/demo")
        if url.path == "/api/run":
            return self._send(json.dumps(snapshot(), indent=2).encode(), "application/json")
        self._send(page("Not found", "<h1>Not found</h1>"), code=404)


def main(port: int = 8000) -> None:
    print("warming the engine...")
    snapshot()
    print(f"dashboard on http://localhost:{port}  (Ctrl-C to stop)")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
