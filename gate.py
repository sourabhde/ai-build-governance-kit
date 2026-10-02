"""CI gate: compare promptfoo results against policy.yaml, write evidence, block the merge if needed.

Usage: uv run python gate.py results/results.json [policy.yaml] [--label "what this run is"]
Writes results/evidence.json and appends a one-line summary to evidence/history.jsonl.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from runtime.pii import redact_pii

WAIVER_FIELDS = {"rule", "owner", "reason", "expires"}
# Per gate tier: the longest a waiver may run (days from today), and whether a second person must approve it.
WAIVER_LIMITS = {"low": (30, False), "medium": (30, False), "high": (14, True)}


def waiver_problem(w: dict, tiers: dict, today: date) -> tuple[str, str | None]:
    """Check one waiver against its tier's rules. Returns (status, problem): valid / expired / invalid."""
    rid = w.get("rule", "?")
    if rid not in tiers:
        return "invalid", f"waiver for unknown rule {rid}"
    tier = tiers[rid]
    max_days, needs_approver = WAIVER_LIMITS.get(tier, WAIVER_LIMITS["high"])
    required = WAIVER_FIELDS | ({"approved_by"} if needs_approver else set())
    if missing := required - {k for k, v in w.items() if v not in (None, "")}:
        return "invalid", f"waiver for {rid} is missing: {', '.join(sorted(missing))}"
    try:
        expires = date.fromisoformat(str(w["expires"]))
    except ValueError:
        return "invalid", f"waiver for {rid} has an invalid expiry date: {w['expires']}"
    if expires < today:
        return "expired", f"waiver for {rid} (owner {w['owner']}) EXPIRED on {expires}"
    if (expires - today).days > max_days:
        return "invalid", (f"waiver for {rid} expires {expires}, more than {max_days} days ahead "
                           f"(the maximum for a {tier}-tier rule)")
    if needs_approver and str(w["approved_by"]).strip().casefold() == str(w["owner"]).strip().casefold():
        return "invalid", (f"waiver for {rid} is approved by its own owner ({w['owner']}); "
                           f"a {tier}-tier waiver needs a second person")
    return "valid", None


def check_waivers(waivers: list, tiers: dict, today: date) -> tuple[dict, list]:
    """Split waivers into valid ones (by rule id) and problems (anything breaking the waiver rules)."""
    valid, problems = {}, []
    for w in waivers or []:
        status, problem = waiver_problem(w, tiers, today)
        if problem:
            problems.append(problem)
        else:
            valid[w["rule"]] = w
    return valid, problems


def main(results_path: str, policy_path: str = "policy.yaml", label: str = "local") -> int:
    policy_bytes = Path(policy_path).read_bytes()
    policy = yaml.safe_load(policy_bytes)
    results = json.load(open(results_path))["results"]["results"]
    now = datetime.now(timezone.utc)

    # Count passed / total tests per rule, using the metadata.rule tag on each test.
    passed, total = defaultdict(int), defaultdict(int)
    for r in results:
        rule = (r.get("testCase", {}).get("metadata") or r.get("metadata") or {}).get("rule")
        total[rule] += 1
        passed[rule] += bool(r.get("success"))

    tiers = {rule["id"]: rule.get("gate_tier", "high") for rule in policy["rules"]}  # no tier -> strictest
    waivers, problems = check_waivers(policy.get("waivers"), tiers, now.date())
    # Every rule must say which system(s) it governs, using IDs from the policy's systems list.
    systems = {s["id"]: s for s in policy.get("systems") or []}
    for rule in policy["rules"]:
        applies = rule.get("applies_to") or []
        if not applies or any(x not in systems for x in applies):
            problems.append(f"rule {rule['id']} must apply to known systems; got {applies or 'none'}")
    block = bool(problems)  # an invalid waiver or rule definition fails the gate on its own
    rows = []
    for rule in policy["rules"]:
        rid, n, tier = rule["id"], total[rule["id"]], tiers[rule["id"]]
        rate = passed[rid] / n if n else 0.0  # a rule with no tests counts as failing
        if tier in ("low", "medium"):
            ok = n > 0 and rate >= rule["pass_threshold"]  # judged against the threshold
        else:
            ok = n > 0 and passed[rid] == n  # high: any failing test blocks, whatever the threshold
        waiver = waivers.get(rid)
        if ok:
            result = "PASS"
        elif waiver:
            result = "WAIVED"
        elif tier == "low":
            result = "WARN"
        else:
            result, block = "FAIL", True
        rows.append({"rule": rid, "systems": rule.get("applies_to") or [], "gate_tier": tier,
                     "severity": rule["severity"], "passed": passed[rid], "total": n, "pass_rate": round(rate, 3), "threshold": rule["pass_threshold"],
                     "result": result,
                     "waiver_owner": waiver["owner"] if waiver else None,
                     "waiver_expires": str(waiver["expires"]) if waiver else None,
                     "waiver_approved_by": waiver.get("approved_by") if waiver else None})
    verdict = "BLOCKED" if block else "PASSED"

    # 1. Console table, then waiver notes
    sys_width = max([len("system")] + [len(",".join(r["systems"])) for r in rows]) + 2
    print(f"{'rule':<24}{'system':<{sys_width}}{'gate_tier':<11}{'severity':<10}{'pass rate':<14}{'threshold':<11}result")
    for r in rows:
        print(f"{r['rule']:<24}{','.join(r['systems']) or '-':<{sys_width}}{r['gate_tier']:<11}{r['severity']:<10}"
              f"{f'{r['pass_rate']:.0%} ({r['passed']}/{r['total']})':<14}{r['threshold']:<11}{r['result']}")
    for r in rows:
        if r["result"] == "WAIVED":
            approver = f", approved by {r['waiver_approved_by']}" if r["waiver_approved_by"] else ""
            print(f"\nWAIVED {r['rule']}: owner {r['waiver_owner']}{approver}, expires {r['waiver_expires']}"
                  f" - {waivers[r['rule']]['reason']}")
    for p in problems:
        print(f"\nFAIL {p}")
    print("\nGATE:", "BLOCKED - fix failing rules before merging." if block else "PASSED - OK to merge.")

    # 2. Evidence file: what was tested, against which policy version, with what result.
    sha = os.environ.get("GITHUB_SHA") or subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    clean = bool(os.environ.get("GITHUB_SHA")) or not subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
    tests = []  # one line per test; model outputs are never stored, failure reasons are PII-redacted
    for r in results:
        meta = r.get("testCase", {}).get("metadata") or r.get("metadata") or {}
        reason = "" if r.get("success") else (r.get("gradingResult") or {}).get("reason") or r.get("error") or ""
        tests.append({"description": r.get("testCase", {}).get("description", ""), "rule": meta.get("rule"),
                      "source": meta.get("source", "suite"), "event_key": meta.get("event_key"),
                      "passed": bool(r.get("success")), "reason": redact_pii(str(reason))[:300]})
    evidence = {
        "timestamp": now.isoformat(timespec="seconds"),
        "git_commit": sha,
        "systems": [{"id": s["id"], "risk_tier": s.get("risk_tier")} for s in systems.values()],
        "answer_model": policy["answer_model"],
        "judge_model": policy["judge_model"],
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "gate": verdict,
        "rules": rows,
        "problems": problems,  # invalid waivers or rule definitions
        "tests": tests,
    }
    Path("results").mkdir(exist_ok=True)
    Path("results/evidence.json").write_text(json.dumps(evidence, indent=2))

    # Run history: one line per gate run, so trends can be shown later.
    history = {"timestamp": evidence["timestamp"], "commit": sha, "working_tree_clean": clean,
               "policy_sha256": evidence["policy_sha256"], "gate": verdict, "label": label,
               "rules": {r["rule"]: {"pass_rate": r["pass_rate"], "result": r["result"]} for r in rows}}
    Path("evidence").mkdir(exist_ok=True)
    with open("evidence/history.jsonl", "a") as f:
        f.write(json.dumps(history) + "\n")

    # 3. GitHub job summary (shown on the PR / run page), only when running in Actions.
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        lines = [f"## Governance gate: {'❌ BLOCKED' if block else '✅ PASSED'}", "",
                 "| Rule | System | Gate tier | Severity | Pass rate | Threshold | Result |",
                 "|---|---|---|---|---|---|---|"]
        lines += [f"| {r['rule']} | {', '.join(r['systems'])} | {r['gate_tier']} | {r['severity']} | {r['pass_rate']:.0%} "
                  f"({r['passed']}/{r['total']}) | {r['threshold']} | {r['result']} |" for r in rows]
        lines += [f"\n**Waived:** {r['rule']} by {r['waiver_owner']}, expires {r['waiver_expires']}"
                  for r in rows if r["result"] == "WAIVED"]
        lines += [f"\n**Problem:** {p}" for p in problems]
        lines += ["", f"Policy `{evidence['policy_sha256'][:12]}` · answer model `{policy['answer_model']}` "
                      f"· judge `{policy['judge_model']}` · commit `{sha[:7]}`"]
        with open(summary, "a") as f:
            f.write("\n".join(lines) + "\n")

    return 1 if block else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Governance gate: results + policy -> verdict and evidence.")
    parser.add_argument("results")
    parser.add_argument("policy", nargs="?", default="policy.yaml")
    parser.add_argument("--label", default="local", help="what this run is, recorded in evidence/history.jsonl")
    args = parser.parse_args()
    sys.exit(main(args.results, args.policy, args.label))
