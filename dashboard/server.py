"""Local multi-page dashboard. Home > Client > Buyer, plus the live input sandbox.

    python -m dashboard.server        then open http://localhost:8000
"""
from __future__ import annotations

import html
import json
import re
import threading
import traceback
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ews import run as engine
from ews.agents import definition
from ews import fetch_news
from ews.config import AS_OF, CURRENCY, DATASET, W_NEWS
from ews.loader import DATA_DIR, DataError, Loader

HERE = Path(__file__).resolve().parent
LIVE_BOOK = DATASET != "synthetic"          # real companies, news fetched from outside
if LIVE_BOOK:
    # The companies are real and the ledger is not: the footer says so on every page, so
    # no screenshot of a real company's payments can be taken for its actual record.
    BANNER = "Tinubu Product Prototype"
    TITLE_TAG = "Tinubu Product Prototype"
    DISCLAIMER = ("The companies are real and the news is fetched from public sources (SEC EDGAR, "
                  "trusted publishers via Google News), linked on each buyer&rsquo;s News tab. The "
                  "insurer&rsquo;s book on them &mdash; credit limits, invoices and payments &mdash; "
                  "is illustrative: no real trade-credit ledger sits behind it, and no payment "
                  "figure here describes how any of these companies actually pays.")
else:
    BANNER = "Tinubu Product Prototype"
    TITLE_TAG = "Tinubu Product Prototype"
    DISCLAIMER = ("Every buyer, insurer, invoice and news article in this view is sample data. "
                  "No real counterparty appears.")
SYMBOL = {"EUR": "&euro;", "USD": "$"}[CURRENCY]
TABS = ("case", "score", "limit", "payments", "news", "agents")

_CACHE: dict[tuple[str, str], dict] = {}
FETCH: dict = {"last": None}
_LOCK = threading.Lock()

# ---------------------------------------------------------------- live sandbox
# Input nobody prepared: a story typed in the room, an invoice aged by hand. It goes
# through exactly the same engine.run() as the shipped dataset - there is no second
# code path for it, which is the only reason showing it proves anything.
LIVE: dict = {"articles": [], "dpd": {}, "last": None}


def engine_date(shown: date) -> date:
    """Live stories are typed on today's calendar and scored on the snapshot's.

    The engine is pinned to AS_OF: every news age, every score and every cached agent
    run depends on it, so moving it would re-score the whole book. Instead a story
    dated today reaches the engine as published on AS_OF, and one dated a week ago as
    a week before it - the age, and so the score, is what it would be had the
    snapshot been taken today. Only the date shown on screen is the typed one.
    """
    return shown - (date.today() - AS_OF)


def shown_date(source: str, engine: str) -> str:
    """The date to display for an article: the typed one for a live story."""
    art = next((a for a in LIVE["articles"] if a["article_id"] == source), None)
    return art.get("shown_date", engine) if art else engine
_LIVE_CACHE: dict[str, dict] = {}


def live_active() -> bool:
    return bool(LIVE["articles"] or LIVE["dpd"])


def moves_between(before: dict, after: dict) -> list[dict]:
    """Every buyer whose score changed, biggest move first."""
    was = {r["buyer_id"]: r["verdict"] for r in before["buyers"]}
    out = []
    for r in after["buyers"]:
        b = was.get(r["buyer_id"])
        if b is None or b["score"] == r["verdict"]["score"]:
            continue
        v = r["verdict"]
        out.append({"buyer_id": r["buyer_id"], "name": r["short_name"],
                    "from_score": b["score"], "to_score": v["score"],
                    "from_band": b["band"], "to_band": v["band"],
                    "delta": round(v["score"] - b["score"], 1),
                    "crossed": b["band"] != v["band"]})
    return sorted(out, key=lambda m: -abs(m["delta"]))


def snapshot() -> dict:
    """The one run every page renders from.

    Sandbox input changes this run rather than living beside it: an earlier version
    kept two snapshots, so a buyer opened from /live showed the sandbox score while the
    insurer page behind it still showed the shipped one. Two views of the same buyer
    disagreeing mid-demo is worse than any feature they bought.

    While sandbox input is in play the adjudicator and the Case File agent run fresh
    only for the buyers that input touched; every other buyer replays its cached
    commentary. Scores are identical either way; they come from the formula, not from
    an agent.
    """
    live = live_active()
    key = (json.dumps(LIVE["articles"], sort_keys=True), json.dumps(LIVE["dpd"], sort_keys=True))
    with _LOCK:  # one engine run at a time now that requests are threaded
        if key not in _CACHE:
            _CACHE[key] = engine.run(
                extra_articles=LIVE["articles"] or None, dpd_overrides=LIVE["dpd"] or None,
                commentary="changed" if live else True)
        return _CACHE[key]


# ---------------------------------------------------------------- helpers
def e(x) -> str:
    return html.escape(str(x))


def money(v: float) -> str:
    v = float(v)
    if abs(v) >= 1e6:
        return f"{SYMBOL}{v/1e6:,.2f}M"
    if abs(v) >= 1e3:
        return f"{SYMBOL}{v/1e3:,.0f}k"
    return f"{SYMBOL}{v:,.0f}"


def band_pill(band: str) -> str:
    cls = {"High Risk": "high", "Watch": "watch", "Healthy": "healthy"}[band]
    return f'<span class="pill {cls}">{e(band)}</span>'


def action_pill(action: str) -> str:
    return f'<span class="pill {action.lower()}">{e(action)}</span>'


def news_cell(news: dict) -> str:
    """Severity badge + the category as a two-word title; headline on hover."""
    sev = news["severity"]
    if not sev:
        return '<span class="muted">&mdash;</span>'
    cls = "high" if sev >= 4 else "watch" if sev == 3 else "maintain"
    title = news["category"].replace("_", " ").capitalize()
    parent = ' <span class="overline">via parent</span>' if news["via_parent"] else ""
    headline = news.get("headline") or ""
    return (f'<span class="newscell" title="{e(headline)}"><span class="pill {cls}">Sev {sev}</span> '
            f'<strong>{e(title)}</strong>{parent}</span>')


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


BRAND_MARK = ('<svg viewBox="0 0 16 16" fill="none" stroke="#fff" stroke-width="1.8" '
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<path d="M1.5 9h3l2-5 3 8 2-4h3"/></svg>')


def page(title: str, body: str, theme: str = "", nav: str = "home") -> bytes:
    attr = f' data-theme="{e(theme)}"' if theme else ""

    def on(key: str) -> str:
        return ' class="on"' if key == nav else ""
    return f"""<!doctype html>
<html lang="en"{attr}><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} &middot; {TITLE_TAG}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/theme.css">
</head><body>
<header class="head"><div class="banner">{BANNER}</div>
<nav class="topbar"><div class="topbar-in">
<a class="brand" href="/"><span class="brand-mark">{BRAND_MARK}</span>Buyer Early Warning and Limit Review</a>
<div class="topnav"><a href="/"{on("home")}>Insurers</a><a href="/live"{on("live")}>Live input</a><a href="/next">Architecture</a></div>
</div></nav></header>
<div class="wrap">{body}
<footer>
  <b>{BANNER}</b><br>
  {DISCLAIMER}
</footer>
</div></body></html>""".encode()


def crumbs(*parts) -> str:
    out = []
    for label, href in parts:
        # the href is built from ids that come from CSV: escape it like any other input
        out.append(f'<a href="{e(href)}">{e(label)}</a>' if href else e(label))
    return f'<div class="crumb">{" &rsaquo; ".join(out)}</div>'


def live_banner() -> str:
    """Shown on every page while sandbox input is in play, so no screen can imply the
    numbers on it are the shipped dataset's."""
    if not live_active():
        return ""
    bits = []
    if LIVE["articles"]:
        bits.append(f'{len(LIVE["articles"])} published '
                    f'{"story" if len(LIVE["articles"]) == 1 else "stories"}')
    if LIVE["dpd"]:
        bits.append(f'{len(LIVE["dpd"])} ledger '
                    f'{"edit" if len(LIVE["dpd"]) == 1 else "edits"}')
    what = ("<b>Hypothetical scenario in play</b> &mdash; the typed stories are not real news. "
            if LIVE_BOOK else "<b>Live input in play</b> &mdash; ")
    return (f'<div class="panel result">{what}'
            f'{" and ".join(bits)} on top of the shipped dataset. Every page reflects it. '
            'The adjudicator and the Case File agent re-review the buyers it touched; '
            'every other buyer keeps its cached review. <a href="/live">Live input &rsaquo;</a></div>')


# ---------------------------------------------------------------- pages
def home() -> bytes:
    data = snapshot()
    cards = []
    for c in data["clients"]:
        b = c["bands"]
        counts = "".join(f'<span><i class="dot {cls}"></i>{k} <b>{b.get(k, 0)}</b></span>'
                         for k, cls in (("High Risk", "high"), ("Watch", "watch"),
                                        ("Healthy", "healthy")))
        cards.append(f"""<a class="card" href="/client/{e(c['client_id'])}">
<h4>{e(c['client_name'])}</h4>
<div class="overline">{e(c['city'])}</div>
<span class="go">&rarr;</span>
<div class="metric"><span>Buyers</span><b>{c['buyers']}</b></div>
<div class="legend">{counts}</div></a>""")

    bands = {k: sum(1 for r in data["buyers"] if r["verdict"]["band"] == k)
             for k in ("High Risk", "Watch", "Healthy")}

    def stat(figure, label, dot=""):
        mark = f'<span class="dot {dot}"></span>' if dot else ""
        return (f'<div class="stat"><div class="figure">{figure}</div>'
                f'<div class="statlabel">{mark}{label}</div></div>')

    tiles = [stat(len(data["buyers"]), "Buyers watched"),
             stat(bands["High Risk"], "High risk", dot="high"),
             stat(bands["Watch"], "Watch", dot="watch")]

    n = len(data["clients"])
    return page("Buyer Early Warning and Limit Review", f"""
{live_banner()}
<div class="hero">
<p class="masthead">Buyer Early Warning and Limit Review</p>
<h1>Today&rsquo;s risk across {"every insurer" if n > 1 else "the book"}</h1>
<p class="lede">Each covered buyer gets a daily risk score from how late it pays
(65%) and what the news says about it (35%). News is graded severity 1&ndash;5
(20 to 100 points) and fades with age. Open an insurer to see its
High Risk and Watch buyers, each with a recommended limit action &mdash; freeze or
reduce &mdash; while there is still limit to cut.</p>
<div class="statrow">{"".join(tiles)}</div>
<p class="meta">{n} insurer{"s" if n != 1 else ""}</p>
</div>
{sources_panel()}
<h2>Insurers</h2>
<div class="cards">{"".join(cards)}</div>""")


def sources_panel() -> str:
    """Where the news comes from, when it was last fetched, and a button to refresh it."""
    if not LIVE_BOOK:
        return ""
    log = fetch_news.last_fetch()
    feeds, publishers = fetch_news.load_sources(DATA_DIR)
    names = {"sec_edgar": "SEC EDGAR Form 8-K filings", "google_news": "Google News"}
    feed_txt = " &middot; ".join(names.get(f, f) for f in sorted(feeds))
    when = (f'Last fetched {e(log["fetched_at"].replace("T", " ").replace("+00:00", " UTC"))} '
            f'&middot; {log["articles"]} articles from the last {log["days"]} days'
            if log else "Not fetched yet")
    errs = "".join(f'<br><span class="overline">{e(x)}</span>' for x in (log or {}).get("errors", []))
    flash = (f'<p class="body2"><b>{e(FETCH["last"])}</b></p>' if FETCH.get("last") else "")
    return f"""<div class="panel">
<h3>News sources</h3>
<p class="body2">{feed_txt}. Press stories are kept only from: {e(", ".join(publishers))}.</p>
<p class="overline">{when}{errs}</p>{flash}
<form method="post" action="/news/fetch" style="margin-top:.6rem" onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='Fetching\u2026'">
<button class="btn" type="submit">Fetch latest news &amp; re-score</button></form></div>"""


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
        label = news_cell(news)
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

    actions_note = (f" &middot; {client['actions_pending']} limit action"
                    f"{'s' if client['actions_pending'] != 1 else ''} available"
                    if client["actions_pending"] else "")
    return page(client["client_name"], f"""
{crumbs(("Home", "/"), (client["client_name"], None))}
{live_banner()}
<h1>{e(client["client_name"])}</h1>
<p class="sub">{client['buyers']} buyers &middot; {money(client['expected_loss'])} expected loss
{actions_note}. This insurer sees only its own buyers.</p>
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
        extra = f' &middot; {run["turns"]} turn{"s" if run["turns"] != 1 else ""}'
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
              'the risk underwriter alongside it.</p>')


def score_card(score: float, band: str) -> str:
    """Band and score side by side over a 0-100 scale split at the band lines."""
    from ews.config import BAND_HIGH, BAND_WATCH
    cls = {"High Risk": "high", "Watch": "watch", "Healthy": "healthy"}[band]
    pos = max(0.0, min(100.0, float(score)))
    segs = "".join(
        f'<span class="seg {c}{" on" if c == cls else ""}" style="width:{hi-lo:g}%"></span>'
        for c, lo, hi in [("healthy", 0, BAND_WATCH), ("watch", BAND_WATCH, BAND_HIGH),
                          ("high", BAND_HIGH, 100)])
    ticks = "".join(f'<span style="left:{t:g}%">{t:g}</span>' for t in (0, BAND_WATCH, BAND_HIGH, 100))
    return (f'<div class="cf-card {cls}">'
            f'<div class="cf-stat"><span class="cf-label">Risk band</span>'
            f'<span class="cf-band"><i></i>{e(band)}</span></div>'
            f'<div class="cf-stat"><span class="cf-label">Risk score</span>'
            f'<span class="cf-score">{score}<small>/100</small></span></div>'
            f'<div class="cf-scale"><div class="cf-track">{segs}'
            f'<span class="cf-marker" style="left:{pos:g}%"></span></div>'
            f'<div class="cf-ticks">{ticks}</div></div></div>')


def bottom_line(text: str) -> str:
    points = re.split(r'(?<=[.!?])\s+(?=[A-Z"])', text.strip())
    return '<ul class="bottom-line">' + "".join(f"<li>{e(x)}</li>" for x in points if x) + "</ul>"


def first_sentence(text: str) -> str:
    return re.split(r'(?<=[.!?])\s+(?=[A-Z"])', text.strip(), maxsplit=1)[0]


def adjudicator_view(r: dict) -> str:
    """The Risk Adjudicator's verdict on the band, one point per concern."""
    rv = r["verdict"].get("review")
    if not rv:
        return ""
    cls = {"agree": "healthy", "agree_with_caveats": "watch", "challenge": "high"}[rv["assessment"]]
    points = "".join(f'<li>{e(first_sentence(c["issue"]))} <span class="overline">'
                     f'{e(c["source_id"])}</span></li>' for c in rv["concerns"])
    return (f'<h3>Adjudicator&rsquo;s view</h3>'
            f'<p class="cf-verdict"><span class="pill {cls}">{ASSESS_LABEL[rv["assessment"]]}</span></p>'
            + (f'<ul class="body2">{points}</ul>' if points else
               f'<p class="body2">{e(first_sentence(rv["rationale"]))}</p>'))


def case_tab(r: dict) -> str:
    """Band and score up top, then the action, the evidence, the review, a short narrative."""
    cf = r["case_file"]
    f = cf["fields"]
    h = f["header"]
    head = score_card(h["score"], h["band"])

    rows = "".join(
        f'<tr><td>{e(l["client_name"])}</td><td class="num">{money(l["current_limit"])}</td>'
        f'<td class="num">{money(l["owed"])}</td><td class="num">{money(l["revised_limit"])}</td>'
        f'<td class="num">{money(l["change"])}</td>'
        f'<td>{action_pill(l["action"])}<br><span class="overline">{e(l["reason"])}</span></td></tr>'
        for l in f["limit_actions"])
    limits = (f'<table><thead><tr><th>Insurer</th><th class="num">Current limit</th>'
              f'<th class="num">Owed</th><th class="num">Revised</th><th class="num">Change</th>'
              f'<th>Action</th></tr></thead><tbody>{rows}</tbody></table>'
              if rows else '<p class="body2">No credit limit lines.</p>')

    evidence = "".join(
        f'<tr><td>{e(x["id"])}</td><td>{e(x["kind"].replace("_", " "))}</td>'
        f'<td>{e(shown_date(x["id"], x["date"]))}</td><td>{e(x["detail"])}</td></tr>' for x in f["evidence"])
    evidence = (f'<table><thead><tr><th>Id</th><th>Kind</th><th>Date</th><th>Detail</th>'
                f'</tr></thead><tbody>{evidence}</tbody></table>' if evidence else
                '<p class="body2">No evidence recorded.</p>')

    # Short by default: the opening paragraph; the rest one click away, so the
    # cached agent text is shown unchanged rather than regenerated.
    paras = [p for p in cf["narrative"].split("\n\n") if p.strip()]
    narrative = "".join(f"<p>{e(p)}</p>" for p in paras[:1])
    if len(paras) > 1:
        narrative += ('<details class="cf-more"><summary>Full narrative</summary>'
                      + "".join(f"<p>{e(p)}</p>" for p in paras[1:]) + "</details>")
    note = (f'<p class="overline">Judgement and narrative written by '
            f'{"the Case File agent" if cf["source"]=="llm" else "template"}; header, '
            f'limits and evidence filled from the engine'
            + (f'; model output discarded &mdash; unverifiable figures {cf["rejected_numbers"]}'
               if cf["rejected_numbers"] else "") + "</p>")
    return (f'<div class="panel case">{head}{bottom_line(f["bottom_line"])}'
            f'<h3>Recommended limit action</h3>{limits}'
            f'<h3>Evidence</h3>{evidence}'
            f'{adjudicator_view(r)}'
            f'<h3>Narrative</h3>{narrative}{note}</div>')


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
    live = live_active()
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
        inner = case_tab(r)

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
<h3>News &mdash; weight {W_NEWS:g}</h3><dl class="kv">
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
                     f'<p class="overline">Every recommendation awaits a risk underwriter. '
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
        urls = {a["article_id"]: a.get("url") for a in Loader().news()}
        ev = [x for x in r["evidence"] if x["kind"] in ("news", "parent")]
        ev.sort(key=lambda x: x["date"], reverse=True)
        rows = "".join(
            f'<tr><td>{e(shown_date(x["source"], x["date"]))}</td><td>{_headline(x["data"]["headline"], urls.get(x["source"]))}<br>'
            f'<span class="overline">{e(x["data"]["publication"])} &middot; matched to '
            f'{e(x["data"]["entity"])}{" (parent)" if x["data"]["via_parent"] else ""}</span></td>'
            f'<td class="num">{x["data"]["severity"]}</td>'
            f'<td class="num">{x["data"]["age_days"]}d</td>'
            f'<td class="num">{x["data"]["base"]:.0f} &rarr; {x["data"]["decayed"]:.1f}</td></tr>'
            for x in ev)
        refused = "".join(
            f'<tr><td>{e(shown_date(x["source"], x["date"]))}</td><td>{e(x["data"]["headline"])}<br>'
            f'<span class="overline">named {e(x["data"]["mention"])}</span></td>'
            f'<td colspan="3"><span class="pill refused">refused</span></td></tr>'
            for x in data["refusals"]
            if r["short_name"].split()[0].upper() in x["data"]["mention"].upper())
        inner = (f'<table><thead><tr><th>Date</th><th>Article</th><th class="num">Severity</th>'
                 f'<th class="num">Age</th><th class="num">Base &rarr; decayed</th></tr></thead>'
                 f'<tbody>{rows}{refused}</tbody></table>'
                 if rows or refused else '<div class="panel">No news matched to this buyer.</div>')

    banner = live_banner()
    return page(r["buyer_name"], f"""
{crumbs(("Home", "/"), (client_name, f"/client/{cid}"), (r["short_name"], None))}
{banner}
<h1>{e(r["buyer_name"])}</h1>
<p class="sub">{e(r["sector"])} &middot; {e(r["city"])} &middot; score {v['score']} {band_pill(v['band'])}</p>
<div class="tabs">{tabs}</div>{inner}""", theme=cid)


def _headline(text: str, url: str | None) -> str:
    """A fetched story links to its source; a shipped or typed one has nowhere to go."""
    if url and url.startswith("https://"):
        return f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(text)}</a>'
    return e(text)


# ---------------------------------------------------------------- live page
def _article_trace(data: dict, article_id: str) -> tuple[str, str]:
    """What the news agent concluded about one article, and how it got there."""
    for r in data["buyers"]:
        for ev in r["evidence"]:
            if ev["source"] == article_id and ev["kind"] in ("news", "parent"):
                d = ev["data"]
                via = f' via its parent {e(d["entity"])}' if d["via_parent"] else ""
                return (f'<span class="pill high">matched</span> '
                        f'<b>{e(d["entity"])}</b>{via} &middot; severity '
                        f'{d.get("parent_severity", d["severity"])} ({e(d["category"])})'
                        f'<br><span class="body2">{e(d.get("reason", ""))}</span>',
                        trace_list(d.get("agent")))
    for x in data["refusals"]:
        if x["source"] == article_id:
            d = x["data"]
            return (f'<span class="pill refused">refused</span> nothing scored &mdash; no '
                    f'covered company matched &ldquo;{e(d["mention"])}&rdquo;'
                    f'<br><span class="body2">{e(d.get("reason", ""))}</span>',
                    trace_list(d.get("agent")))
    return ('<span class="pill maintain">no entity matched</span>', "")


def result_panel() -> str:
    last = LIVE["last"]
    if not last:
        return ""
    if last.get("error"):
        return (f'<div class="panel result"><h3>Rejected</h3>'
                f'<p class="body2">{e(last["error"])}</p>'
                f'<p class="overline">Nothing changed. The dataset is only ever '
                f'written to through a check that can say no.</p></div>')

    rows = "".join(
        f'<div class="move {"crossed" if m["crossed"] else ""}">'
        f'<a href="/buyer/{e(m["buyer_id"])}"><b>{e(m["name"])}</b></a>'
        f'<span class="from">{m["from_score"]} {band_pill(m["from_band"])}</span>'
        f'<span class="arrow">&rarr;</span>'
        f'<span class="to">{m["to_score"]} {band_pill(m["to_band"])}</span>'
        f'<span class="overline">{m["delta"]:+.1f}</span></div>' for m in last["moves"])
    if not rows:
        rows = ('<p class="body2">No score moved. That is a result, not a failure &mdash; '
                'the engine read it and it changed nothing.</p>')

    trace = ""
    if last.get("verdict"):
        concl, calls = last["verdict"]
        trace = (f'<h3>What the News agent decided</h3><p>{concl}</p>'
                 f'{calls or "<p class=\'overline\'>Rule-based path &mdash; no tool calls.</p>"}')
    return (f'<div class="panel result"><h3>{e(last["title"])}</h3>{rows}{trace}</div>')


def live_inputs_block() -> str:
    if not LIVE["articles"] and not LIVE["dpd"]:
        return ('<p class="overline">Nothing added yet &mdash; the engine is running on the '
                'shipped dataset exactly as it ships.</p>')
    arts = "".join(
        f'<tr><td>{e(a["article_id"])}</td><td>{e(a.get("shown_date", a["published_date"]))}</td>'
        f'<td>{e(a["mentioned_entity_as_written"])}</td><td>{e(a["headline"])}</td></tr>'
        for a in LIVE["articles"])
    arts = (f'<table><thead><tr><th>Id</th><th>Date</th><th>Company named</th>'
            f'<th>Headline</th></tr></thead><tbody>{arts}</tbody></table>' if arts else "")
    names = Loader().buyers_by_id()
    dpd = "".join(
        f'<tr><td>{e(names[b]["short_name"]) if b in names else e(b)}</td>'
        f'<td class="num">{d} days past due</td></tr>' for b, d in sorted(LIVE["dpd"].items()))
    dpd = (f'<table><thead><tr><th>Buyer</th><th class="num">Worst open invoice</th>'
           f'</tr></thead><tbody>{dpd}</tbody></table>' if dpd else "")
    return arts + dpd


def live_page() -> bytes:
    data = snapshot()
    buyers = sorted(Loader().buyers(), key=lambda b: b["short_name"])
    options = "".join(
        f'<option value="{e(b["buyer_id"])}">{e(b["short_name"])} &mdash; {e(b["sector"])}, '
        f'{e(b["city"])}</option>' for b in buyers)

    # Registered names, click-to-fill. Typing "Nordkrans Steel Traders AB" correctly in
    # front of a room is a risk with no upside; the field stays free text, so a name that
    # is not on this list still goes through exactly as typed.
    chips = "".join(f'<button type="button" class="chip namechip" '
                    f'data-name="{e(b["buyer_name"])}">{e(b["short_name"])}</button>'
                    for b in buyers)

    flagged = [r for r in data["buyers"] if r["verdict"]["band"] != "Healthy"]
    rows = "".join(
        f'<tr><td><a href="/buyer/{e(r["buyer_id"])}">{e(r["short_name"])}</a></td>'
        f'<td class="num">{r["verdict"]["score"]}</td><td>{band_pill(r["verdict"]["band"])}</td>'
        f'<td class="num">{r["verdict"]["payment"]["dpd"]}</td>'
        f'<td>{news_cell(r["verdict"]["news"])}</td></tr>' for r in flagged)

    return page("Live input", nav="live", body=f"""
{crumbs(("Home", "/"), ("Live input", None))}
<h1>Live input</h1>
<p class="sub">Type a story that has never been seen, or age an invoice by hand. Both go
through the same engine as the shipped data &mdash; there is no separate path for them.
The dataset is a snapshot of {e(AS_OF.isoformat())}; a story dated today is scored as if it
broke that day. The News agent runs live on what you type, then the adjudicator and the
Case File agent re-review every buyer your input touched, so a publish or a ledger edit
takes about a minute with Claude connected.</p>

{result_panel()}

<div class="live-grid">
<form class="panel live-form" method="post" action="/live/story">
  <h3>Publish a story</h3>
  <label>Company as the article names it <span class="overline">optional</span>
    <input name="mention" id="mention" placeholder="leave blank and the agent reads it out of the body"
           autocomplete="off"></label>
  <div class="namechips">{chips}</div>
  <p class="overline">Click to fill, or type anything, or <b>leave it empty</b> &mdash; the
  agent reads the body and finds the company itself. To see a refusal, keep the first word
  and change the business: &ldquo;Larsson <b>Dental Group</b> AB&rdquo; is not
  &ldquo;Larsson <b>Distributors</b> AB&rdquo;.</p>
  <label>Headline
    <input name="headline" required placeholder="Workers protest over delayed wages"
           autocomplete="off"></label>
  <label>Body <span class="overline">what the agent actually reads</span>
    <textarea name="body" rows="3" required
      placeholder="Staff staged a protest over three months of delayed wages, unions said."></textarea></label>
  <label>Published <input type="date" name="date" value="{e(date.today().isoformat())}"
           max="{e(date.today().isoformat())}"></label>
  <button class="btn" type="submit">Publish &amp; re-run</button>
  <p class="overline">The News agent searches the registry, checks sector and city, and
  decides. A name it cannot place is refused.</p>
</form>

<form class="panel live-form" method="post" action="/live/ledger">
  <h3>Age an invoice</h3>
  <label>Buyer<select name="buyer_id">{options}</select></label>
  <label>Worst open invoice is now
    <input type="number" name="dpd" min="0" max="365" value="45" required> days past due</label>
  <button class="btn" type="submit">Update ledger &amp; re-run</button>
  <p class="overline">Payment carries 65% of the score, news 35%. Bands: Healthy below
  20, Watch 20-50, High Risk 50+. A fresh severity 3-5 story alone reaches Watch; news
  alone never reaches High Risk - that takes the ledger too.</p>
</form>
</div>

<h2>What has been added</h2>
{live_inputs_block()}
<p style="margin:.9rem 0"><a class="btn ghost" href="/live/reset">Reset to the shipped
dataset</a></p>

<h2>Flagged right now</h2>
{f'<table><thead><tr><th>Buyer</th><th class="num">Score</th><th>Band</th>'
 f'<th class="num">DPD</th><th>Worst news</th></tr></thead><tbody>{rows}</tbody></table>'
 if rows else '<div class="panel">Nothing flagged.</div>'}

<script>
document.querySelectorAll('.namechip').forEach(c => c.addEventListener('click', () => {{
  const m = document.getElementById('mention');
  m.value = c.dataset.name; m.focus();
}}));
document.querySelectorAll('form.live-form').forEach(f => f.addEventListener('submit', () => {{
  const b = f.querySelector('button');
  b.disabled = true;
  b.textContent = 'The agents are re-reviewing\u2026 about a minute';
}}));
</script>""")


# ---------------------------------------------------------------- live actions
def _apply(title: str, mutate) -> None:
    """Run one live action: snapshot before, mutate, re-run, record what moved.

    Anything the engine refuses leaves LIVE untouched and the reason on the page -
    a bad input must never be able to take the demo down mid-sentence.
    """
    before = snapshot()
    keep = (list(LIVE["articles"]), dict(LIVE["dpd"]))
    try:
        new_id = mutate()
        after = snapshot()
    except (DataError, ValueError, KeyError) as exc:
        LIVE["articles"], LIVE["dpd"] = keep
        LIVE["last"] = {"title": title, "error": str(exc), "moves": []}
        return
    LIVE["last"] = {"title": title, "moves": moves_between(before, after),
                    "verdict": _article_trace(after, new_id) if new_id else None}


def add_story(form: dict) -> None:
    mention = (form.get("mention", [""])[0] or "").strip()
    headline = (form.get("headline", [""])[0] or "").strip()
    body = (form.get("body", [""])[0] or "").strip()
    when = (form.get("date", [""])[0] or date.today().isoformat()).strip()

    def mutate() -> str:
        # the company is optional: the agent finds it in the body. Offline the
        # rule-based resolver needs it and will refuse - which is the honest answer.
        if not (headline and body):
            raise ValueError("a headline and a body are required")
        try:
            published = date.fromisoformat(when)
        except ValueError as exc:
            raise ValueError(f"cannot read {when!r} as a date") from exc
        if published > date.today():
            raise ValueError(
                f"a story dated {published.isoformat()} is in the future - the engine "
                f"refuses news it could not have seen. Pick today or an earlier date.")
        aid = f"LIVE{len(LIVE['articles']) + 1:02d}"
        LIVE["articles"].append({
            "article_id": aid, "published_date": engine_date(published).isoformat(),
            "shown_date": published.isoformat(),
            # on a book of real companies a typed story is a what-if, and every page
            # it reaches must say so - a screenshot must not read as real news
            "publication": "HYPOTHETICAL - typed in the room" if LIVE_BOOK else "Live input",
            "headline": (f"[HYPOTHETICAL] {headline}" if LIVE_BOOK else headline), "body": body,
            "mentioned_entity_as_written": mention})
        return aid

    _apply(f"Published: {headline}", mutate)


def set_dpd(form: dict) -> None:
    bid = (form.get("buyer_id", [""])[0] or "").strip()
    raw = (form.get("dpd", [""])[0] or "").strip()

    def mutate() -> str:
        if bid not in Loader().buyers_by_id():
            raise ValueError(f"no buyer {bid!r}")
        try:
            LIVE["dpd"][bid] = int(raw)
        except ValueError as exc:
            raise ValueError(f"days past due must be a whole number, got {raw!r}") from exc
        Loader(dpd_overrides=LIVE["dpd"]).invoices()      # validate before re-running
        return ""

    name = Loader().buyers_by_id().get(bid, {}).get("short_name", bid)
    _apply(f"Ledger updated: {name} now {raw} days past due", mutate)


def refresh_news() -> None:
    """Fetch from the trusted sources, then re-score. A failed fetch keeps the old file."""
    try:
        rep = fetch_news.fetch(quiet=True)
    except (SystemExit, OSError, ValueError) as exc:
        FETCH["last"] = f"Fetch failed - the previous news is still in use: {exc}"
        return
    with _LOCK:
        _CACHE.clear()
    FETCH["last"] = (f"Fetched {rep['articles']} articles"
                     + (f"; {len(rep['errors'])} source error(s)" if rep["errors"] else "")
                     + ". Scores below are re-run on them.")


def next_page() -> bytes:
    """Static: it is a slide, not a view of the data - only the banner follows the book."""
    html_ = (HERE / "next.html").read_text()
    return (html_.replace("{{BANNER}}", BANNER).replace("{{DISCLAIMER}}", DISCLAIMER)
            .replace("{{TITLE_TAG}}", TITLE_TAG)).encode()


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

    def do_POST(self):                # noqa: N802
        try:
            length = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            path = urllib.parse.urlparse(self.path).path
            if path == "/live/story":
                add_story(form)
            elif path == "/live/ledger":
                set_dpd(form)
            elif path == "/news/fetch" and LIVE_BOOK:
                refresh_news()
                return self._redirect("/")
            else:
                return self._send(page("Not found", "<h1>Not found</h1>"), code=404)
            self._redirect("/live")                  # POST-redirect-GET: no re-submit
        except Exception as exc:                                   # noqa: BLE001
            traceback.print_exc()
            self._send(page("Error", f"<h1>Something went wrong</h1>"
                                     f'<div class="panel"><code>{e(exc)}</code></div>'), code=500)

    def do_GET(self):                 # noqa: N802
        try:
            self._route()
        except Exception as exc:                                   # noqa: BLE001
            # a traceback in the browser is the worst thing that can happen mid-demo
            traceback.print_exc()
            self._send(page("Error", f"<h1>Something went wrong</h1>"
                                     f'<div class="panel"><code>{e(exc)}</code></div>'), code=500)

    def _route(self):
        url = urllib.parse.urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = urllib.parse.parse_qs(url.query)

        if url.path == "/theme.css":
            return self._send((HERE / "theme.css").read_bytes(), "text/css; charset=utf-8")
        if url.path == "/next":
            return self._send(next_page())
        if url.path == "/":
            return self._send(home())
        if url.path == "/live":
            return self._send(live_page())
        if url.path == "/live/reset":
            LIVE.update(articles=[], dpd={}, last=None)
            return self._redirect("/live")
        if parts[:1] == ["client"] and len(parts) == 2:
            body = client_page(parts[1])
            return self._send(body, code=404 if b"Unknown insurer" in body else 200)
        if parts[:1] == ["buyer"] and len(parts) == 2:
            tab = query.get("tab", ["case"])[0]
            body = buyer_page(parts[1], tab if tab in TABS else "case",
                              )
            return self._send(body, code=404 if b"Unknown buyer" in body else 200)
        if url.path == "/api/run":
            return self._send(json.dumps(snapshot(), indent=2).encode(), "application/json")
        self._send(page("Not found", "<h1>Not found</h1>"), code=404)


def main(port: int = 8000) -> None:
    print("warming the engine...")
    snapshot()
    print(f"dashboard on http://localhost:{port}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
