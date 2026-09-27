"""CI gate: compare promptfoo results against policy.yaml and block the merge if needed.

Usage: uv run python gate.py results/results.json
"""
import json
import sys
from collections import defaultdict

import yaml


def main(results_path: str) -> int:
    policy = yaml.safe_load(open("policy.yaml"))
    results = json.load(open(results_path))["results"]["results"]

    # Count passed / total tests per rule, using the metadata.rule tag on each test.
    passed, total = defaultdict(int), defaultdict(int)
    for r in results:
        rule = (r.get("testCase", {}).get("metadata") or r.get("metadata") or {}).get("rule")
        total[rule] += 1
        passed[rule] += bool(r.get("success"))

    blocking = set(policy["block_merge_on"])
    block = False
    print(f"{'rule':<24}{'severity':<10}{'pass rate':<14}{'threshold':<11}result")
    for rule in policy["rules"]:
        rid, n = rule["id"], total[rule["id"]]
        rate = passed[rid] / n if n else 0.0  # a rule with no tests counts as failing
        ok = rate >= rule["pass_threshold"]
        block |= not ok and rule["severity"] in blocking
        print(f"{rid:<24}{rule['severity']:<10}{f'{rate:.0%} ({passed[rid]}/{n})':<14}"
              f"{rule['pass_threshold']:<11}{'PASS' if ok else 'FAIL'}")

    print("\nGATE:", "BLOCKED - fix failing rules before merging." if block else "OK to merge.")
    return 1 if block else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
