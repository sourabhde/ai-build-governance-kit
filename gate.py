"""CI gate: compare promptfoo results against policy.yaml, write evidence, block the merge if needed.

Usage: uv run python gate.py results/results.json
"""
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml


def main(results_path: str) -> int:
    policy_bytes = Path("policy.yaml").read_bytes()
    policy = yaml.safe_load(policy_bytes)
    results = json.load(open(results_path))["results"]["results"]

    # Count passed / total tests per rule, using the metadata.rule tag on each test.
    passed, total = defaultdict(int), defaultdict(int)
    for r in results:
        rule = (r.get("testCase", {}).get("metadata") or r.get("metadata") or {}).get("rule")
        total[rule] += 1
        passed[rule] += bool(r.get("success"))

    blocking = set(policy["block_merge_on"])
    rows, block = [], False
    for rule in policy["rules"]:
        rid, n = rule["id"], total[rule["id"]]
        rate = passed[rid] / n if n else 0.0  # a rule with no tests counts as failing
        ok = rate >= rule["pass_threshold"]
        block |= not ok and rule["severity"] in blocking
        rows.append({"rule": rid, "severity": rule["severity"], "passed": passed[rid], "total": n,
                     "pass_rate": round(rate, 3), "threshold": rule["pass_threshold"],
                     "result": "PASS" if ok else "FAIL"})
    verdict = "BLOCKED" if block else "OK"

    # 1. Console table
    print(f"{'rule':<24}{'severity':<10}{'pass rate':<14}{'threshold':<11}result")
    for r in rows:
        print(f"{r['rule']:<24}{r['severity']:<10}{f'{r['pass_rate']:.0%} ({r['passed']}/{r['total']})':<14}"
              f"{r['threshold']:<11}{r['result']}")
    print("\nGATE:", "BLOCKED - fix failing rules before merging." if block else "OK to merge.")

    # 2. Evidence file: what was tested, against which policy version, with what result.
    sha = os.environ.get("GITHUB_SHA") or subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    evidence = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": sha,
        "system": policy["system"],
        "answer_model": policy["answer_model"],
        "judge_model": policy["judge_model"],
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "gate": verdict,
        "rules": rows,
    }
    Path("results").mkdir(exist_ok=True)
    Path("results/evidence.json").write_text(json.dumps(evidence, indent=2))

    # 3. GitHub job summary (shown on the PR / run page), only when running in Actions.
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        lines = [f"## Governance gate: {'❌ BLOCKED' if block else '✅ OK'}", "",
                 "| Rule | Severity | Pass rate | Threshold | Result |", "|---|---|---|---|---|"]
        lines += [f"| {r['rule']} | {r['severity']} | {r['pass_rate']:.0%} ({r['passed']}/{r['total']}) "
                  f"| {r['threshold']} | {r['result']} |" for r in rows]
        lines += ["", f"Policy `{evidence['policy_sha256'][:12]}` · answer model `{policy['answer_model']}` "
                      f"· judge `{policy['judge_model']}` · commit `{sha[:7]}`"]
        with open(summary, "a") as f:
            f.write("\n".join(lines) + "\n")

    return 1 if block else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
