"""Build the governance dashboard: one self-contained HTML file from real repo files only.

Usage: uv run python -m dashboard.build   -> writes dashboard/index.html (opens offline, no CDNs)
Sources: policy.yaml, results/evidence.json, evidence/history.jsonl, runtime/sample_events.jsonl,
runtime/events.jsonl (if present) and tests/generated/runtime_cases.yaml. Nothing is invented: when a
source is missing, the page says so instead of showing a number.
"""
import hashlib
import json
import os
import subprocess
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
TABS = [("architecture", "How it works"), ("systems", "Systems"), ("rules", "Rules"), ("history", "History"),
        ("waivers", "Waivers"), ("events", "Runtime events"), ("feedback", "Feedback loop"), ("evidence", "Evidence")]

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


def run_from_evidence(ev: dict) -> dict:
    """The same shape as a history line, for when only evidence.json exists."""
    return {"timestamp": ev["timestamp"], "commit": ev["git_commit"], "working_tree_clean": None,
            "policy_sha256": ev["policy_sha256"], "gate": ev["gate"], "label": "latest evidence",
            "rules": {r["rule"]: {k: r[k] for k in ("pass_rate", "result", "passed", "total")} for r in ev["rules"]},
            "tests": ev.get("tests", [])}


def group_events(events: list[dict]) -> list[dict]:
    """One row per event key (same rule, system, input and role), newest first, with where it was seen."""
    groups = {}
    for e in events:
        key = event_key(e)
        g = groups.setdefault(key, {**e, "key": key, "sources": set(), "count": 0})
        g["sources"].add(e["_source"])
        g["count"] += 1
        if e["timestamp"] > g["timestamp"]:
            g.update({k: e[k] for k in ("timestamp", "latency_ms", "action", "gate_tier")})
    return sorted(groups.values(), key=lambda g: g["timestamp"], reverse=True)


def load(sources: dict) -> dict:
    policy_bytes = sources["policy"].read_bytes()
    events = [{**e, "_source": "sample"} for e in read_jsonl(sources["sample_events"])]
    events += [{**e, "_source": "live"} for e in read_jsonl(sources["live_events"])]
    evidence = json.loads(sources["evidence"].read_text()) if sources["evidence"].exists() else None
    runs = read_jsonl(sources["history"]) or ([run_from_evidence(evidence)] if evidence else [])
    generated = yaml.safe_load(sources["generated"].read_text()) if sources["generated"].exists() else None
    return {
        "policy": yaml.safe_load(policy_bytes),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "evidence": evidence,
        "runs": runs,
        "events": group_events(events),
        "generated": generated or [],
        "found": {name: path.exists() for name, path in sources.items()},
        "branch": current_branch(),
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


def clip(text: str, limit: int = 90) -> str:
    """Shorten at a word boundary with an ellipsis; the full text stays available on hover."""
    if len(text) <= limit:
        return escape(text)
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f'<span title="{escape(text)}">{escape(cut)}…</span>'


def when(ts: str) -> str:
    return escape(ts.replace("T", " ").replace("+00:00", ""))


def panel(sid: str, title: str, body: str, intro: str = "") -> str:
    intro_html = f'<p class="intro">{intro}</p>' if intro else ""
    return (f'<section id="panel-{sid}" class="panel" role="tabpanel" aria-labelledby="tab-{sid}" tabindex="0">'
            f'<h2>{escape(title)}</h2>{intro_html}{body}</section>')


def missing(what: str, how: str) -> str:
    return f'<p class="empty">No {escape(what)} yet. {how}</p>'


def per_run(d: dict, render_one) -> str:
    """Render one variant per recorded run; the run selector shows one at a time (latest by default)."""
    if not d["runs"]:
        return render_one(None, None)
    last = len(d["runs"]) - 1
    return "".join(f'<div class="run-view" data-run="{i}"{"" if i == last else " hidden"}>{render_one(run, i)}</div>'
                   for i, run in enumerate(d["runs"]))


def current_branch() -> str:
    """The branch the page is built from: the PR's head branch in CI, else the local git branch."""
    env = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    if env:
        return env
    out = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, cwd=ROOT)
    return out.stdout.strip() or "this branch"


def latest_label(run: dict, branch: str) -> str:
    """E.g. 'Latest run on v2 (PR #5)'."""
    link = pr_link(run)
    return f'Latest run on {escape(run.get("branch") or branch)}{" (" + link + ")" if link else ""}'


def run_name(run: dict, i: int) -> str:
    return f'#{i + 1} {run.get("label", "")} ({when(run["timestamp"])} UTC)'


def failing(run: dict) -> list[str]:
    return [rid for rid, v in run["rules"].items() if v["result"] == "FAIL"]


def pr_link(run: dict) -> str:
    """The run's pull request as a link, if one was recorded."""
    url = run.get("pr") or ""
    if not url.startswith("https://"):
        return ""
    text = f'PR #{url.rstrip("/").rsplit("/", 1)[-1]}' if "/pull/" in url else "link"
    return f'<a href="{escape(url)}">{escape(text)}</a>'


def run_story(run: dict) -> str:
    """Description and PR link, e.g. 'Everything as intended. · PR #5'."""
    return " · ".join(x for x in (escape(run.get("description") or ""), pr_link(run)) if x)


# ---------- header with run selector ----------

def header(d: dict) -> str:
    policy, runs = d["policy"], d["runs"]
    counts = [("Systems", str(len(policy.get("systems") or []))), ("Rules", str(len(policy["rules"])))]

    def one(run, i):
        if run is None:
            return '<p class="empty">No gate run found. Run the eval and <code>gate.py</code>, then rebuild.</p>'
        if i != len(runs) - 1:
            story = run_story(run)
            past = (f'<div class="pastnote" role="status"><strong>Showing past run {escape(run_name(run, i))}, '
                    f'not the latest.</strong>{"<br>" + story if story else ""}'
                    f'<br>Failed: {escape(", ".join(failing(run)) or "none")}</div>')
        else:
            story = run_story(run)
            detail = f'#{i + 1} {escape(run.get("label", ""))}{": " + escape(run.get("description") or "") if run.get("description") else ""}'
            past = f'<p class="runnote"><strong>{latest_label(run, d["branch"])}</strong> · {detail}</p>'

        same = run["policy_sha256"] == d["policy_sha256"]
        facts = counts + [
            ("Commit", short(run["commit"], 7) + ("" if run.get("working_tree_clean") is not False else " (uncommitted changes)")),
            ("Policy hash", short(run["policy_sha256"]) + ("" if same else " ⚠ differs from current policy.yaml")),
            ("Run time (UTC)", when(run["timestamp"])),
            ("Tests", str(len(run.get("tests") or [])) or "–")]
        items = "".join(f'<div class="fact"><span class="k">{k}</span><span class="v">{v}</span></div>' for k, v in facts)
        return f'{past}<div class="gate">{badge(run["gate"], "Gate " + run["gate"])}</div><div class="facts">{items}</div>'

    selector = ""
    if len(runs) > 1:
        options = "".join(f'<option value="{i}"{" selected" if i == len(runs) - 1 else ""}>'
                          f'{escape(run_name(r, i))}{" (latest)" if i == len(runs) - 1 else ""}</option>'
                          for i, r in enumerate(runs))
        selector = (f'<label class="runpick">Run shown in header, Systems and Rules: '
                    f'<select id="run">{options}</select></label>')
    return f'<header class="strip"><h1>AI Build Governance Kit</h1>{selector}{per_run(d, one)}</header>'


# ---------- tabs ----------

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
    return panel("architecture", "How it works", svg,
                 "One policy drives both halves. The same IDs and policy hash link every test, gate decision, "
                 "runtime event and generated test back to the exact rule and policy version.")


def systems(d: dict) -> str:
    def one(run, i):
        results = (run or {}).get("rules", {})
        cards = []
        for s in d["policy"].get("systems") or []:
            rules = [r for r in d["policy"]["rules"] if s["id"] in (r.get("applies_to") or [])]
            got = [results[r["id"]]["result"] for r in rules if r["id"] in results]
            if not got:
                status = badge("logged", "No results yet")
            elif "FAIL" in got:
                status = badge("BLOCKED")
            elif "WAIVED" in got:
                status = badge("WAIVED", "PASSED with waiver")
            else:
                status = badge("PASSED")
            items = "".join(f'<li>{escape(r["id"])} {badge(results[r["id"]]["result"]) if r["id"] in results else "<em>not in this run</em>"}</li>'
                            for r in rules)
            cards.append(f'<article class="card"><h3>{escape(s["id"])}</h3>{status}'
                         f'<p>{escape(s.get("purpose", ""))}</p>'
                         f'<p><strong>EU AI Act risk tier:</strong> {escape(str(s.get("risk_tier", "–")))}</p>'
                         f'<p><strong>Rules that apply:</strong></p><ul>{items}</ul></article>')
        return f'<div class="cards">{"".join(cards)}</div>'
    return panel("systems", "Systems", per_run(d, one), "Status for the run selected in the header.")


def rules(d: dict) -> str:
    def one(run, ri):
        results, tests = (run or {}).get("rules", {}), (run or {}).get("tests") or []
        body = []
        for i, rule in enumerate(d["policy"]["rules"]):
            rid, r = rule["id"], results.get(rule["id"])
            rate = (f'{bar(r["pass_rate"])} {pct(r["pass_rate"])}'
                    f'{" (" + str(r["passed"]) + "/" + str(r["total"]) + ")" if "total" in r else ""}') if r else "not run"
            mine = [t for t in tests if t.get("rule") == rid]
            test_items = "".join(test_item(t) for t in mine)
            tid = f"tests-{ri}-{i}"
            body.append(
                f'<tr><td><button class="expand" type="button" aria-expanded="false" aria-controls="{tid}">'
                f'<span aria-hidden="true">▸</span> {escape(rid)}</button>'
                f'<br><small>{escape(rule.get("description", ""))}</small></td>'
                f'<td>{escape(", ".join(rule.get("applies_to") or []))}</td>'
                f'<td>{escape(rule.get("gate_tier", "high"))}</td>'
                f'<td>{escape(rule.get("severity", ""))}</td>'
                f'<td>{rule.get("pass_threshold")}</td><td class="rate">{rate}</td>'
                f'<td>{badge(r["result"]) if r else "–"}</td>'
                f'<td><small>{escape("; ".join(rule.get("maps_to") or []))}</small></td></tr>'
                f'<tr id="{tid}" class="tests" hidden><td colspan="8">'
                f'{"<ul>" + test_items + "</ul>" if mine else "No test details recorded for this rule in this run."}</td></tr>')
        return ('<div class="scroll"><table><thead><tr><th>Rule</th><th>System</th><th>Gate tier</th>'
                '<th>Severity <small>(reporting only)</small></th><th>Threshold</th><th>Pass rate</th><th>Result</th>'
                f'<th>Framework mapping</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')
    return panel("rules", "Rules", per_run(d, one),
                 "Gate tier decides blocking; severity is a label for reporting only. Select a rule to see its test "
                 "cases and results for the run selected in the header.")


def test_item(t: dict) -> str:
    """One test in an expanded rule. Failed tests also show their input, what happened and why it failed."""
    line = (f'<li>{badge("PASS" if t["passed"] else "FAIL")} {escape(t["description"])}'
            f'{" <em>(generated from a runtime event)</em>" if t.get("source") == "runtime" else ""}')
    if not t["passed"]:
        details = [("Input", f'&ldquo;{escape(t["input"])}&rdquo;' + (f' (role {escape(t["role"])})' if t.get("role") else "")
                    if t.get("input") else ""),
                   ("What happened", escape(t.get("outcome") or "")), ("Why it failed", escape(t.get("reason") or ""))]
        line += "".join(f'<div class="detail"><strong>{k}:</strong> {v}</div>' for k, v in details if v)
    return line + "</li>"


def history(d: dict) -> str:
    runs = d["runs"]
    if not runs:
        return panel("history", "Run history", missing("recorded runs", "Each <code>gate.py</code> run adds one."))
    head = "".join(f'<th scope="col">#{i + 1}<br><small>{escape(r.get("label", ""))}</small></th>' for i, r in enumerate(runs))
    rows = []
    for rule in d["policy"]["rules"]:
        cells = []
        for r in runs:
            v = r["rules"].get(rule["id"])
            cells.append(f'<td class="cell">{badge(v["result"], pct(v["pass_rate"]))}</td>' if v else '<td class="cell">n/a</td>')
        rows.append(f'<tr><th scope="row">{escape(rule["id"])}</th>{"".join(cells)}</tr>')
    gate_row = "".join(f'<td class="cell">{badge(r["gate"])}</td>' for r in runs)
    grid = (f'<div class="scroll"><table class="grid"><thead><tr><th>Rule</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}<tr class="gaterow"><th scope="row">Gate</th>{gate_row}</tr></tbody></table></div>')
    run_rows = "".join(
        f'<tr><td>#{i + 1}</td><td>{when(r["timestamp"])}</td><td>{escape(r.get("label", ""))}</td>'
        f'<td>{run_story(r) or "–"}</td>'
        f'<td>{short(r["commit"], 7)}{" <small>(uncommitted changes)</small>" if r.get("working_tree_clean") is False else ""}</td>'
        f'<td>{short(r["policy_sha256"])}</td><td>{badge(r["gate"])}</td>'
        f'<td>{escape(", ".join(failing(r)) or "none")}</td></tr>'
        for i, r in enumerate(runs))
    table = ('<h3>Runs</h3><div class="scroll"><table><thead><tr><th>Run</th><th>Time (UTC)</th><th>Label</th>'
             f'<th>What changed</th><th>Commit</th><th>Policy hash</th><th>Gate</th><th>Failing rules</th></tr></thead><tbody>{run_rows}</tbody></table></div>')
    return panel("history", "Run history", grid + table, "Pass rate per rule for every recorded gate run.")


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
    return panel("waivers", "Waivers", body)


def source_label(sources: set) -> str:
    return " + ".join(s for s in ("sample", "live") if s in sources)


def events(d: dict) -> str:
    if not d["events"]:
        return panel("events", "Runtime events", missing("runtime events", "Run <code>python -m runtime.simulate</code>."))
    rows = "".join(
        f'<tr><td>{when(e["timestamp"])}</td><td>{source_label(e["sources"])}'
        f'{" <small>(seen " + str(e["count"]) + " times)</small>" if e["count"] > 1 else ""}</td>'
        f'<td>{escape(e["system_id"])}</td><td>{escape(e["rule_id"])}</td><td>{badge(e["action"])}</td>'
        f'<td>{e["latency_ms"]:.3f}</td><td><small>{escape(e["input"])}</small></td></tr>' for e in d["events"])
    body = ('<div class="scroll"><table><thead><tr><th>Latest (UTC)</th><th>Source</th><th>System</th><th>Rule</th>'
            f'<th>Action</th><th>Guard ms</th><th>Input (redacted)</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return panel("events", "Runtime events", body,
                 "What the runtime guard caught, one row per distinct event. Inputs are stored with personal data "
                 "redacted; outputs are never stored. \"sample\" is the committed synthetic file, \"live\" is this "
                 "machine's log.")


def feedback(d: dict) -> str:
    cases = {c.get("metadata", {}).get("event_key"): c for c in d["generated"]}
    tests = {t.get("event_key"): t for t in (d["evidence"] or {}).get("tests", []) if t.get("event_key")}
    rows = []
    for e in d["events"]:
        if e["action"] not in ("blocked", "flagged"):
            continue
        case, test = cases.get(e["key"]), tests.get(e["key"])
        rows.append(f'<tr><td>{escape(e["rule_id"])}<br><small>{escape(e["system_id"])} · {source_label(e["sources"])} · '
                    f'{clip(e["input"])}</small></td><td aria-hidden="true">→</td>'
                    f'<td>{escape(case["description"]) if case else "<em>no test generated yet (run runtime.to_tests)</em>"}</td>'
                    f'<td aria-hidden="true">→</td>'
                    f'<td>{badge("PASS" if test["passed"] else "FAIL") if test else "<em>not in the latest run</em>"}</td></tr>')
    if not rows:
        return panel("feedback", "Feedback loop", missing("blocked or flagged events", ""))
    body = ('<div class="scroll"><table><thead><tr><th>Runtime event</th><th></th><th>Generated test</th><th></th>'
            f'<th>Regression test on current code</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return panel("feedback", "Feedback loop", body,
                 "Each event caught at runtime becomes a regression test (matched by its event key), so CI keeps checking it. "
                 "Results are the regression test on current code (the latest run), not the result of any earlier pull request.")


def evidence(d: dict) -> str:
    ev = d["evidence"]
    if not ev:
        return panel("evidence", "Evidence", missing("evidence file", "Run the eval and <code>gate.py</code>."))
    fields = [("Gate", badge(ev["gate"])), ("Timestamp (UTC)", escape(ev["timestamp"])),
              ("Commit", escape(ev["git_commit"])), ("Policy SHA-256", escape(ev["policy_sha256"])),
              ("Answer model", escape(ev.get("answer_model", "–"))), ("Judge model", escape(ev.get("judge_model", "–"))),
              ("Systems", escape(", ".join(f'{s["id"]} ({s["risk_tier"]})' for s in ev.get("systems", [])))),
              ("Tests recorded", str(len(ev.get("tests", [])))),
              ("Problems", escape("; ".join(ev.get("problems", [])) or "none"))]
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in fields)
    raw = escape(json.dumps(ev, indent=2))
    body = f'<dl class="kv">{dl}</dl><details><summary>View raw JSON</summary><pre class="code">{raw}</pre></details>'
    return panel("evidence", "Evidence", body,
                 f'From <code>{escape(d["paths"]["evidence"])}</code>, written by the latest gate run.')


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
h1{font-size:2.1rem;margin:0 0 12px}h2{font-size:1.65rem;margin:0 0 8px}h3{margin:16px 0 8px;font-size:1.25rem}
.panel{padding:22px 0}.panel:focus-visible{outline-offset:6px}
.intro{color:var(--muted);margin:0 0 14px;max-width:70ch}
.strip{padding:22px 0 14px;border-bottom:2px solid var(--line)}
.runpick{display:block;font-weight:700;margin-bottom:12px}
.runpick select{font:inherit;font-weight:400;padding:4px 8px;margin-left:6px;border:2px solid var(--line);border-radius:8px;
background:var(--card);color:var(--fg);max-width:100%}
.pastnote{border:2px dashed var(--warn);padding:10px 14px;border-radius:8px;margin:0 0 12px}
.pastnote strong{color:var(--warn)}.runnote{margin:0 0 12px;color:var(--muted)}.runnote strong{color:var(--fg)}
a{color:var(--accent);font-weight:700}
.detail{font-size:.92rem;margin:2px 0 0 4px}.detail strong{color:var(--muted)}
.gate .badge{font-size:1.6rem;padding:6px 18px}
.facts{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}
.fact{background:var(--card);border:2px solid var(--line);border-radius:10px;padding:8px 14px;min-width:130px}
.fact .k{display:block;color:var(--muted);font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.fact .v{font-size:1.2rem;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace}
.tabbar{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:2px solid var(--line);
position:sticky;top:0;background:var(--bg);z-index:2}[role=tablist]{display:flex;flex-wrap:wrap;gap:6px}
[role=tab]{font:inherit;font-weight:700;font-size:1rem;padding:8px 14px;border:2px solid var(--line);border-radius:10px;
background:var(--card);color:var(--fg);cursor:pointer}
[role=tab][aria-selected=true]{background:var(--accent);border-color:var(--accent);color:var(--bg)}
#theme{margin-left:auto;font:inherit;font-size:.9rem;padding:6px 12px;border:2px solid var(--line);border-radius:10px;
background:var(--card);color:var(--fg);cursor:pointer}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:700;border:2px solid currentColor;border-radius:999px;
padding:1px 10px;white-space:nowrap;font-size:.95rem}
.pass{color:var(--pass)}.fail{color:var(--fail)}.warn{color:var(--warn)}.waived{color:var(--waived)}.info{color:var(--info)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:1rem}
th,td{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--line)}
thead th{background:var(--card);font-weight:700}
.grid td.cell{text-align:center;vertical-align:middle}.grid thead th{text-align:center}.grid thead th:first-child{text-align:left}
.grid tbody th{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.95rem}.gaterow th,.gaterow td{border-top:2px solid var(--line)}
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
.empty{font-weight:700}
.code{background:var(--card);border:2px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:.85rem;max-height:520px}
details summary{cursor:pointer;font-weight:700;color:var(--accent);margin:10px 0}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:0}.kv dt{font-weight:700}.kv dd{margin:0;word-break:break-all}
span[title]{text-decoration:underline dotted;cursor:help}
footer{border-top:2px solid var(--line);padding-top:16px;color:var(--muted);font-size:.9rem}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
"""

JS = """
(function(){
var tabs=[].slice.call(document.querySelectorAll('[role=tab]'));
var ids=tabs.map(function(t){return t.id.slice(4)});
function show(id,focus){
  if(ids.indexOf(id)<0)id=ids[0];
  tabs.forEach(function(t){var on=t.id==='tab-'+id;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;
    document.getElementById('panel-'+t.id.slice(4)).hidden=!on;if(on&&focus)t.focus();});
}
function fromHash(){return decodeURIComponent(location.hash.slice(1))}
tabs.forEach(function(t,i){
  t.addEventListener('click',function(){show(ids[i],false);location.hash=ids[i]});
  t.addEventListener('keydown',function(e){
    var j={ArrowRight:i+1,ArrowLeft:i-1,Home:0,End:tabs.length-1}[e.key];
    if(j===undefined)return;e.preventDefault();j=(j+tabs.length)%tabs.length;
    location.hash=ids[j];show(ids[j],true);});
});
window.addEventListener('hashchange',function(){show(fromHash(),false)});
show(fromHash(),false);
document.querySelectorAll('.expand').forEach(function(b){b.addEventListener('click',function(){
  var r=document.getElementById(b.getAttribute('aria-controls'));var open=b.getAttribute('aria-expanded')==='true';
  b.setAttribute('aria-expanded',String(!open));r.hidden=open;b.firstChild.textContent=open?'▸':'▾';});});
var pick=document.getElementById('run');
if(pick)pick.addEventListener('change',function(){
  document.querySelectorAll('.run-view').forEach(function(v){v.hidden=v.getAttribute('data-run')!==pick.value});});
var root=document.documentElement,btn=document.getElementById('theme');
function set(t){root.setAttribute('data-theme',t);btn.textContent=(t==='dark'?'☀ Light mode':'☾ Dark mode');
  try{localStorage.setItem('theme',t)}catch(e){}}
var saved=null;try{saved=localStorage.getItem('theme')}catch(e){}
set(saved||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
btn.addEventListener('click',function(){set(root.getAttribute('data-theme')==='dark'?'light':'dark')});
})();
"""


def render(d: dict, now: datetime) -> str:
    tablist = "".join(f'<button type="button" role="tab" id="tab-{i}" aria-controls="panel-{i}" aria-selected="false" '
                      f'tabindex="-1">{escape(t)}</button>' for i, t in TABS)
    panels = [architecture(), systems(d), rules(d), history(d), waivers(d, now.date()), events(d), feedback(d), evidence(d)]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>AI Build Governance Kit</title><style>{CSS}</style></head><body><main>'
            f'{header(d)}<div class="tabbar"><div role="tablist" aria-label="Dashboard sections">{tablist}</div>'
            f'<button id="theme" type="button">Theme</button></div>'
            f'{"".join(panels)}{sources_footer(d, now)}</main><script>{JS}</script></body></html>')


def main(sources: dict = SOURCES, out_path: Path = OUT_PATH) -> Path:
    html = render(load(sources), datetime.now(timezone.utc))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    path = main()
    print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB). Open it with: uv run python -m dashboard.open")
