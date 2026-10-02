"""Build the governance dashboard: one self-contained HTML file from real repo files only.

Usage: uv run python -m dashboard.build   -> writes dashboard/index.html (opens offline, no CDNs)
Sources: policy.yaml, results/evidence.json, evidence/history.jsonl, runtime/sample_events.jsonl,
runtime/events.jsonl (if present) and tests/generated/runtime_cases.yaml. Nothing is invented: when a
source is missing, the page says so instead of showing a number.
"""
import hashlib
import json
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

import yaml

from gate import waiver_problem
from runtime.to_tests import event_key

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "policy": ROOT / "policy.yaml",
    "evidence": ROOT / "results" / "evidence.json",
    "history": ROOT / "evidence" / "history.jsonl",
    "sample_events": ROOT / "runtime" / "sample_events.jsonl",
    "live_events": ROOT / "runtime" / "events.jsonl",
    "generated": ROOT / "tests" / "generated" / "runtime_cases.yaml",
}
OUT_PATH = ROOT / "dashboard" / "index.html"

ICONS = {"PASS": "✓", "PASSED": "✓", "FAIL": "✕", "BLOCKED": "✕", "WARN": "!", "WAIVED": "◐",
         "blocked": "✕", "flagged": "!", "logged": "i", "valid": "✓", "expired": "✕", "invalid": "✕"}
TONE = {"PASS": "pass", "PASSED": "pass", "valid": "pass", "FAIL": "fail", "BLOCKED": "fail", "blocked": "fail",
        "expired": "fail", "invalid": "fail", "WARN": "warn", "flagged": "warn", "WAIVED": "waived", "logged": "info"}
WAIVER_EXAMPLE = """waivers:
  - rule: R2_no_pii_leak            # high tier
    owner: <rule owner>
    approved_by: <a second person>  # required for high tier; not the owner
    reason: <why shipping with this failure is acceptable for now>
    expires: <YYYY-MM-DD>           # high tier: at most 14 days ahead"""


# ---------- loading ----------

def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def load(sources: dict) -> dict:
    policy_bytes = sources["policy"].read_bytes()
    events = [{**e, "_source": "sample"} for e in read_jsonl(sources["sample_events"])]
    events += [{**e, "_source": "live"} for e in read_jsonl(sources["live_events"])]
    generated = yaml.safe_load(sources["generated"].read_text()) if sources["generated"].exists() else None
    return {
        "policy": yaml.safe_load(policy_bytes),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "evidence": json.loads(sources["evidence"].read_text()) if sources["evidence"].exists() else None,
        "history": read_jsonl(sources["history"]),
        "events": sorted(events, key=lambda e: e["timestamp"], reverse=True),
        "generated": generated or [],
        "found": {name: path.exists() for name, path in sources.items()},
        "paths": {name: str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
                  for name, path in sources.items()},
    }


# ---------- small HTML helpers ----------

def badge(status: str, text: str | None = None) -> str:
    """Status is always shown as icon + word, never colour alone."""
    return (f'<span class="badge {TONE.get(status, "info")}"><span aria-hidden="true">{ICONS.get(status, "•")}</span> '
            f'{escape(text or status)}</span>')


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def bar(rate: float) -> str:
    return (f'<span class="bar" role="img" aria-label="{pct(rate)}"><span style="width:{rate * 100:.0f}%">'
            f'</span></span>')


def short(sha: str | None, n: int = 12) -> str:
    return escape((sha or "")[:n]) or "–"


def section(sid: str, title: str, body: str, intro: str = "") -> str:
    intro_html = f'<p class="intro">{intro}</p>' if intro else ""
    return f'<section id="{sid}"><h2>{escape(title)}</h2>{intro_html}{body}</section>'


def missing(what: str, how: str) -> str:
    return f'<p class="empty">No {escape(what)} yet. {how}</p>'


# ---------- sections ----------

def header(d: dict) -> str:
    ev, policy = d["evidence"], d["policy"]
    if not ev:
        status = '<p class="empty">No gate run found. Run the eval and <code>gate.py</code>, then rebuild.</p>'
        facts = []
    else:
        status = f'<div class="gate">{badge(ev["gate"], "Gate " + ev["gate"])}</div>'
        same = ev["policy_sha256"] == d["policy_sha256"]
        facts = [("Commit", short(ev["git_commit"], 7)),
                 ("Policy hash", short(ev["policy_sha256"]) + ("" if same else " ⚠ differs from current policy.yaml")),
                 ("Last run (UTC)", escape(ev["timestamp"].replace("T", " ").replace("+00:00", ""))),
                 ("Tests", str(len(ev.get("tests", []))))]
    facts = [("Systems", str(len(policy.get("systems") or []))), ("Rules", str(len(policy["rules"])))] + facts
    items = "".join(f'<div class="fact"><span class="k">{k}</span><span class="v">{v}</span></div>' for k, v in facts)
    return f'<header class="strip"><h1>AI Build Governance Kit</h1>{status}<div class="facts">{items}</div></header>'


def architecture() -> str:
    def box(x, y, w, title, sub, cls="node"):
        return (f'<g class="{cls}"><rect x="{x}" y="{y}" width="{w}" height="78" rx="10"/>'
                f'<text x="{x + w / 2}" y="{y + 32}" class="t1">{title}</text>'
                f'<text x="{x + w / 2}" y="{y + 58}" class="t2">{sub}</text></g>')

    def arrow(path, label="", lx=0, ly=0):
        text = f'<text x="{lx}" y="{ly}" class="t3">{label}</text>' if label else ""
        return f'<path d="{path}" class="edge" marker-end="url(#arrow)"/>{text}'

    svg = f"""<svg viewBox="0 0 1100 470" role="img" aria-labelledby="arch-title arch-desc" class="arch">
<title id="arch-title">How the kit works</title>
<desc id="arch-desc">policy.yaml feeds build-time tests, which go to a gate that decides by tier and writes evidence.
The same policy feeds a runtime guard, whose events become generated tests that flow back into the build-time tests.
Every step carries the system ID, rule ID and policy hash.</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
<path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>
<text x="270" y="22" class="lane">BUILD TIME (every pull request)</text>
<text x="270" y="282" class="lane">RUN TIME (every request)</text>
{box(20, 160, 180, "policy.yaml", "rules · tiers · systems", "node policy")}
{box(270, 40, 220, "Build-time tests", "per rule, against the apps")}
{box(560, 40, 220, "Gate by tier", "low warns · medium · high")}
{box(850, 40, 230, "Evidence", "evidence.json + history")}
{box(270, 300, 220, "Runtime guard", "same rules, per request")}
{box(560, 300, 220, "Events", "events.jsonl, PII redacted")}
{box(850, 300, 230, "Generated tests", "reviewed, then committed")}
{arrow("M200,185 C235,185 235,80 268,80")}
{arrow("M200,225 C235,225 235,340 268,340")}
{arrow("M490,79 L558,79")}
{arrow("M780,79 L848,79")}
{arrow("M490,339 L558,339")}
{arrow("M780,339 L848,339")}
{arrow("M965,300 L965,215 L380,215 L380,120", "feedback loop: a live catch becomes a CI test", 672, 206)}
<g class="shared"><rect x="20" y="400" width="1060" height="54" rx="10"/>
<text x="550" y="434" class="t1">Shared on every step:  system ID  ·  rule ID  ·  policy hash</text></g>
</svg>"""
    return section("architecture", "How it works", svg,
                   "One policy drives both halves. The same IDs and policy hash link every test, gate decision, "
                   "runtime event and generated test back to the exact rule and policy version.")


def rows_by_rule(d: dict) -> dict:
    return {r["rule"]: r for r in (d["evidence"] or {}).get("rules", [])}


def systems(d: dict) -> str:
    rows, cards = rows_by_rule(d), []
    for s in d["policy"].get("systems") or []:
        rules = [r for r in d["policy"]["rules"] if s["id"] in (r.get("applies_to") or [])]
        results = [rows[r["id"]]["result"] for r in rules if r["id"] in rows]
        if not results:
            status = badge("logged", "No results yet")
        elif "FAIL" in results:
            status = badge("BLOCKED")
        elif "WAIVED" in results:
            status = badge("WAIVED", "PASSED with waiver")
        else:
            status = badge("PASSED")
        items = "".join(f'<li>{escape(r["id"])} {badge(rows[r["id"]]["result"]) if r["id"] in rows else ""}</li>'
                        for r in rules)
        cards.append(f'<article class="card"><h3>{escape(s["id"])}</h3>{status}'
                     f'<p>{escape(s.get("purpose", ""))}</p>'
                     f'<p><strong>EU AI Act risk tier:</strong> {escape(str(s.get("risk_tier", "–")))}</p>'
                     f'<p><strong>Rules that apply:</strong></p><ul>{items}</ul></article>')
    return section("systems", "Systems", f'<div class="cards">{"".join(cards)}</div>')


def rules(d: dict) -> str:
    rows, tests = rows_by_rule(d), (d["evidence"] or {}).get("tests", [])
    body = []
    for i, rule in enumerate(d["policy"]["rules"]):
        rid, r = rule["id"], rows.get(rule["id"])
        rate = (f'{bar(r["pass_rate"])} {pct(r["pass_rate"])} ({r["passed"]}/{r["total"]})' if r else "not run")
        mine = [t for t in tests if t["rule"] == rid]
        test_items = "".join(
            f'<li>{badge("PASS" if t["passed"] else "FAIL")} {escape(t["description"])}'
            f'{" <em>(generated from a runtime event)</em>" if t.get("source") == "runtime" else ""}'
            f'{"<br><small>" + escape(t["reason"]) + "</small>" if t.get("reason") else ""}</li>' for t in mine)
        body.append(
            f'<tr><td><button class="expand" aria-expanded="false" aria-controls="tests-{i}">▸ {escape(rid)}</button>'
            f'<br><small>{escape(rule.get("description", ""))}</small></td>'
            f'<td>{escape(", ".join(rule.get("applies_to") or []))}</td>'
            f'<td>{escape(rule.get("gate_tier", "high"))}</td>'
            f'<td>{escape(rule.get("severity", ""))}</td>'
            f'<td>{rule.get("pass_threshold")}</td><td class="rate">{rate}</td>'
            f'<td>{badge(r["result"]) if r else "–"}</td>'
            f'<td><small>{escape("; ".join(rule.get("maps_to") or []))}</small></td></tr>'
            f'<tr id="tests-{i}" class="tests" hidden><td colspan="8">'
            f'{"<ul>" + test_items + "</ul>" if mine else "No test results recorded for this rule."}</td></tr>')
    table = ('<div class="scroll"><table><thead><tr><th>Rule</th><th>System</th><th>Gate tier</th>'
             '<th>Severity <small>(reporting only)</small></th><th>Threshold</th><th>Pass rate</th><th>Result</th>'
             f'<th>Framework mapping</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')
    return section("rules", "Rules", table, "Gate tier decides blocking; severity is a label for reporting only. "
                   "Select a rule to see its test cases and results from the latest run.")


def history(d: dict) -> str:
    runs = d["history"]
    if not runs:
        return section("history", "Run history", missing("recorded runs", "Each <code>gate.py</code> run adds one."))
    rule_ids = [r["id"] for r in d["policy"]["rules"]]
    w, h, gap = 64, 90, 22
    charts = []
    for rid in rule_ids:
        bars = []
        for i, run in enumerate(runs):
            v = (run["rules"].get(rid) or {}).get("pass_rate")
            x = i * (w + gap)
            if v is None:
                bars.append(f'<text x="{x + w / 2}" y="{h - 4}" class="t3">n/a</text>')
                continue
            bh = max(2, v * h)
            res = run["rules"][rid]["result"]
            bars.append(f'<rect x="{x}" y="{h - bh}" width="{w}" height="{bh}" class="hbar {TONE.get(res, "info")}"/>'
                        f'<text x="{x + w / 2}" y="{h + 20}" class="t3">{ICONS.get(res, "")} {pct(v)}</text>')
        width = len(runs) * (w + gap)
        charts.append(f'<div class="minichart"><div class="mlabel">{escape(rid)}</div>'
                      f'<svg viewBox="0 -4 {width} {h + 28}" width="{width}" height="{h + 28}" role="img" '
                      f'aria-label="{escape(rid)} pass rate per run">{"".join(bars)}</svg></div>')
    runs_head = "".join(f'<span class="runlabel" style="width:{w + gap}px">#{i + 1}</span>' for i in range(len(runs)))
    table_rows = "".join(
        f'<tr><td>#{i + 1}</td><td>{escape(r["timestamp"].replace("T", " ").replace("+00:00", ""))}</td>'
        f'<td>{escape(r.get("label", ""))}</td><td>{short(r["commit"], 7)}'
        f'{"" if r.get("working_tree_clean") else " <small>(uncommitted changes)</small>"}</td>'
        f'<td>{short(r["policy_sha256"])}</td><td>{badge(r["gate"])}</td>'
        f'<td>{escape(", ".join(k for k, v in r["rules"].items() if v["result"] == "FAIL") or "none")}</td></tr>'
        for i, r in enumerate(runs))
    body = (f'<div class="chart"><div class="minichart head"><div class="mlabel">Run</div><div>{runs_head}</div></div>'
            f'{"".join(charts)}</div>'
            '<div class="scroll"><table><thead><tr><th>Run</th><th>Time (UTC)</th><th>Label</th><th>Commit</th>'
            f'<th>Policy hash</th><th>Gate</th><th>Failing rules</th></tr></thead><tbody>{table_rows}</tbody></table></div>')
    return section("history", "Run history", body, "Pass rate per rule for every recorded gate run.")


def waivers(d: dict, today: date) -> str:
    tiers = {r["id"]: r.get("gate_tier", "high") for r in d["policy"]["rules"]}
    rows = []
    for w in d["policy"].get("waivers") or []:
        status, problem = waiver_problem(w, tiers, today)
        try:
            days = str((date.fromisoformat(str(w.get("expires"))) - today).days)
        except ValueError:
            days = "–"
        rows.append(f'<tr><td>{escape(str(w.get("rule", "–")))}</td><td>{escape(str(w.get("owner", "–")))}</td>'
                    f'<td>{escape(str(w.get("approved_by", "–")))}</td><td>{escape(str(w.get("reason", "–")))}</td>'
                    f'<td>{escape(str(w.get("expires", "–")))}</td><td>{days}</td>'
                    f'<td>{badge(status)}{"<br><small>" + escape(problem) + "</small>" if problem else ""}</td></tr>')
    if not rows:
        body = ('<p class="empty">No active waivers.</p><p>A waiver lets a failing rule through for a limited time, '
                'with a named owner. This is what one looks like in <code>policy.yaml</code> (example, not active):</p>'
                f'<pre class="code">{escape(WAIVER_EXAMPLE)}</pre>')
    else:
        body = ('<div class="scroll"><table><thead><tr><th>Rule</th><th>Owner</th><th>Approver</th><th>Reason</th>'
                f'<th>Expires</th><th>Days left</th><th>Status</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return section("waivers", "Waivers", body)


def events(d: dict) -> str:
    if not d["events"]:
        return section("events", "Runtime events", missing("runtime events", "Run <code>python -m runtime.simulate</code>."))
    rows = "".join(
        f'<tr><td>{escape(e["timestamp"].replace("T", " ").replace("+00:00", ""))}</td>'
        f'<td>{"sample" if e["_source"] == "sample" else "live"}</td><td>{escape(e["system_id"])}</td>'
        f'<td>{escape(e["rule_id"])}</td><td>{badge(e["action"])}</td><td>{e["latency_ms"]:.3f}</td>'
        f'<td><small>{escape(e["input"])}</small></td></tr>' for e in d["events"])
    body = ('<div class="scroll"><table><thead><tr><th>Time (UTC)</th><th>Source</th><th>System</th><th>Rule</th>'
            f'<th>Action</th><th>Guard ms</th><th>Input (redacted)</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return section("events", "Runtime events", body,
                   "What the runtime guard caught. Inputs are stored with personal data redacted; outputs are never stored. "
                   "\"sample\" rows come from the committed synthetic file, \"live\" rows from this machine's log.")


def feedback(d: dict) -> str:
    cases = {c.get("metadata", {}).get("event_key"): c for c in d["generated"]}
    tests = {t.get("event_key"): t for t in (d["evidence"] or {}).get("tests", []) if t.get("event_key")}
    rows = []
    for e in d["events"]:
        if e["action"] not in ("blocked", "flagged"):
            continue
        key = event_key(e)
        case, test = cases.get(key), tests.get(key)
        rows.append(f'<tr><td>{escape(e["rule_id"])}<br><small>{escape(e["system_id"])} · {escape(e["input"][:80])}</small></td>'
                    f'<td aria-hidden="true">→</td>'
                    f'<td>{escape(case["description"]) if case else "<em>no test generated yet (run runtime.to_tests)</em>"}</td>'
                    f'<td aria-hidden="true">→</td>'
                    f'<td>{badge("PASS" if test["passed"] else "FAIL") if test else "<em>not in the latest run</em>"}</td></tr>')
    if not rows:
        return section("feedback", "Feedback loop", missing("blocked or flagged events", ""))
    body = ('<div class="scroll"><table><thead><tr><th>Runtime event</th><th></th><th>Generated test</th><th></th>'
            f'<th>Latest result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return section("feedback", "Feedback loop", body,
                   "Each event caught at runtime becomes a regression test (matched by its event key), so CI keeps checking it.")


def evidence(d: dict) -> str:
    ev = d["evidence"]
    if not ev:
        return section("evidence", "Evidence", missing("evidence file", "Run the eval and <code>gate.py</code>."))
    fields = [("Gate", badge(ev["gate"])), ("Timestamp (UTC)", escape(ev["timestamp"])),
              ("Commit", escape(ev["git_commit"])), ("Policy SHA-256", escape(ev["policy_sha256"])),
              ("Answer model", escape(ev.get("answer_model", "–"))), ("Judge model", escape(ev.get("judge_model", "–"))),
              ("Systems", escape(", ".join(f'{s["id"]} ({s["risk_tier"]})' for s in ev.get("systems", [])))),
              ("Tests recorded", str(len(ev.get("tests", [])))),
              ("Problems", escape("; ".join(ev.get("problems", [])) or "none"))]
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in fields)
    raw = escape(json.dumps(ev, indent=2))
    body = (f'<dl class="kv">{dl}</dl><details><summary>View raw JSON</summary><pre class="code">{raw}</pre></details>')
    return section("evidence", "Evidence", body, f'From <code>{escape(d["paths"]["evidence"])}</code>, written by the latest gate run.')


def sources_footer(d: dict, built: datetime) -> str:
    items = "".join(f'<li><code>{escape(d["paths"][k])}</code>: {"found" if v else "not found"}</li>'
                    for k, v in d["found"].items())
    return (f'<footer><p>Built {escape(built.isoformat(timespec="seconds"))} from these repo files only:</p>'
            f'<ul>{items}</ul><p>Personal learning project. Not affiliated with or endorsed by any company.</p></footer>')


# ---------- page ----------

CSS = """
:root{--bg:#ffffff;--fg:#111418;--muted:#3d4450;--card:#f3f5f8;--line:#b9c0ca;--accent:#0b4fc0;
--pass:#0a6b2e;--fail:#b3001b;--warn:#7a4f00;--waived:#4a3aa8;--info:#3d4450;--barbg:#dde2e8;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1216;--fg:#f2f4f7;--muted:#c3cad4;
--card:#1a1f26;--line:#4a5361;--accent:#8ab4ff;--pass:#6fdc8c;--fail:#ff8a8a;--warn:#ffd27a;--waived:#c3b5ff;
--info:#c3cad4;--barbg:#2c333d;color-scheme:dark}}
:root[data-theme=dark]{--bg:#0f1216;--fg:#f2f4f7;--muted:#c3cad4;--card:#1a1f26;--line:#4a5361;--accent:#8ab4ff;
--pass:#6fdc8c;--fail:#ff8a8a;--warn:#ffd27a;--waived:#c3b5ff;--info:#c3cad4;--barbg:#2c333d;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:19px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1240px;margin:0 auto;padding:0 20px 40px}
h1{font-size:2.1rem;margin:0 0 12px}h2{font-size:1.65rem;margin:0 0 8px;padding-top:8px}h3{margin:0 0 8px;font-size:1.25rem}
section{border-top:2px solid var(--line);padding:22px 0}
.intro{color:var(--muted);margin:0 0 14px;max-width:70ch}
nav{position:sticky;top:0;background:var(--bg);border-bottom:2px solid var(--line);z-index:2}
nav .in{max-width:1240px;margin:0 auto;padding:8px 20px;display:flex;flex-wrap:wrap;gap:6px 18px;align-items:center}
nav a{color:var(--accent);font-weight:600;text-decoration:none}nav a:hover,nav a:focus{text-decoration:underline}
#theme{margin-left:auto;font:inherit;font-size:.9rem;padding:4px 12px;border:2px solid var(--line);border-radius:8px;
background:var(--card);color:var(--fg);cursor:pointer}
.strip{padding:24px 0 18px}
.gate .badge{font-size:1.6rem;padding:6px 18px}
.facts{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}
.fact{background:var(--card);border:2px solid var(--line);border-radius:10px;padding:8px 14px;min-width:130px}
.fact .k{display:block;color:var(--muted);font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.fact .v{font-size:1.2rem;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:700;border:2px solid currentColor;border-radius:999px;
padding:1px 10px;white-space:nowrap;font-size:.95rem}
.pass{color:var(--pass)}.fail{color:var(--fail)}.warn{color:var(--warn)}.waived{color:var(--waived)}.info{color:var(--info)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:1rem}
th,td{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--line)}
th{background:var(--card);font-weight:700}
small{color:var(--muted);font-size:.85rem}
.bar{display:inline-block;width:90px;height:14px;background:var(--barbg);border:1px solid var(--line);border-radius:4px;
vertical-align:middle;overflow:hidden}.bar span{display:block;height:100%;background:var(--accent)}
.rate{white-space:nowrap}
.expand{font:inherit;font-weight:700;background:none;border:0;color:var(--accent);cursor:pointer;padding:0;text-align:left}
.expand[aria-expanded=true]{text-decoration:underline}
tr.tests td{background:var(--card)}tr.tests ul{margin:0;padding-left:0;list-style:none}tr.tests li{margin:6px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.card{background:var(--card);border:2px solid var(--line);border-radius:12px;padding:16px 18px}
.card ul{margin:4px 0;padding-left:20px}.card li{margin:4px 0}
.arch{width:100%;height:auto;max-width:1100px;color:var(--fg)}
.arch rect{fill:var(--card);stroke:var(--line);stroke-width:2}
.arch .policy rect{stroke:var(--accent);stroke-width:3}
.arch .shared rect{fill:none;stroke:var(--accent);stroke-width:3;stroke-dasharray:8 6}
.arch text{fill:currentColor;text-anchor:middle}.arch .t1{font-size:21px;font-weight:700}.arch .t2{font-size:16px;fill:var(--muted)}
.arch .t3{font-size:15px;font-weight:600;fill:var(--accent)}.arch .lane{font-size:15px;font-weight:700;text-anchor:start;fill:var(--muted);letter-spacing:.06em}
.arch .edge{fill:none;stroke:var(--fg);stroke-width:2.5}.arch .arrowhead{fill:var(--fg)}
.chart{margin-bottom:18px}
.minichart{display:flex;align-items:flex-end;gap:16px;margin:6px 0}
.minichart.head{align-items:center}.mlabel{width:230px;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.95rem;padding-bottom:20px}
.minichart.head .mlabel{padding-bottom:0}.runlabel{display:inline-block;text-align:center;font-weight:700;padding-right:22px}
.minichart svg text{fill:currentColor;text-anchor:middle}.minichart .t3{font-size:14px;font-weight:700}
.hbar.pass{fill:var(--pass)}.hbar.fail{fill:var(--fail)}.hbar.warn{fill:var(--warn)}.hbar.waived{fill:var(--waived)}
.empty{font-weight:700}
.code{background:var(--card);border:2px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:.85rem;max-height:520px}
details summary{cursor:pointer;font-weight:700;color:var(--accent);margin:10px 0}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:0}.kv dt{font-weight:700}.kv dd{margin:0;word-break:break-all}
footer{border-top:2px solid var(--line);padding-top:16px;color:var(--muted);font-size:.9rem}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
"""

JS = """
document.querySelectorAll('.expand').forEach(function(b){b.addEventListener('click',function(){
var r=document.getElementById(b.getAttribute('aria-controls'));var open=b.getAttribute('aria-expanded')==='true';
b.setAttribute('aria-expanded',String(!open));r.hidden=open;b.firstChild.textContent=(open?'▸ ':'▾ ')+b.textContent.slice(2);});});
var root=document.documentElement,btn=document.getElementById('theme');
function set(t){root.setAttribute('data-theme',t);btn.textContent=(t==='dark'?'☀ Light mode':'☾ Dark mode');
try{localStorage.setItem('theme',t)}catch(e){}}
var saved=null;try{saved=localStorage.getItem('theme')}catch(e){}
set(saved||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
btn.addEventListener('click',function(){set(root.getAttribute('data-theme')==='dark'?'light':'dark')});
"""


def render(d: dict, now: datetime) -> str:
    nav = "".join(f'<a href="#{i}">{t}</a>' for i, t in [
        ("architecture", "How it works"), ("systems", "Systems"), ("rules", "Rules"), ("history", "History"),
        ("waivers", "Waivers"), ("events", "Runtime events"), ("feedback", "Feedback loop"), ("evidence", "Evidence")])
    parts = [header(d), architecture(), systems(d), rules(d), history(d), waivers(d, now.date()), events(d),
             feedback(d), evidence(d), sources_footer(d, now)]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>AI Build Governance Kit</title><style>{CSS}</style></head><body>'
            f'<nav aria-label="Sections"><div class="in">{nav}<button id="theme" type="button">Theme</button></div></nav>'
            f'<main>{"".join(parts)}</main><script>{JS}</script></body></html>')


def main(sources: dict = SOURCES, out_path: Path = OUT_PATH) -> Path:
    html = render(load(sources), datetime.now(timezone.utc))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    path = main()
    print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB). Open it with: uv run python -m dashboard.open")
