"""Unit tests for gate.py: tier and waiver rules. No network, no LLM calls.

Each test builds a tiny promptfoo-style results file and a tiny policy, runs the gate,
and checks the exit code and the per-rule results it wrote to results/evidence.json.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gate  # noqa: E402

OWNER = "Test Owner"
APPROVER = "Second Approver"
TODAY = "2026-10-01T12:00:00+00:00"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Run every test in an empty folder, outside GitHub Actions."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("GITHUB_SHA", "test")


def freeze_utc(monkeypatch, iso: str):
    """Make gate.py believe the current UTC time is `iso`."""
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(iso).astimezone(tz)
    monkeypatch.setattr(gate, "datetime", FrozenDateTime)


def run_gate(outcomes: dict, rules: list, waivers: list | None = None) -> tuple[int, dict]:
    """outcomes: {rule_id: [True, False, ...]} one entry per test. Returns (exit code, {rule: row})."""
    results = [{"success": ok, "testCase": {"metadata": {"rule": rid}}}
               for rid, oks in outcomes.items() for ok in oks]
    Path("results.json").write_text(json.dumps({"results": {"results": results}}))
    policy = {"system": "test", "answer_model": "a", "judge_model": "j", "rules": rules, "waivers": waivers or []}
    Path("policy.yaml").write_text(yaml.safe_dump(policy))
    code = gate.main("results.json", "policy.yaml")
    rows = json.loads(Path("results/evidence.json").read_text())["rules"]
    return code, {r["rule"]: r for r in rows}


def rule(rid: str, tier: str = "high", threshold: float = 1.0) -> dict:
    return {"id": rid, "severity": "critical", "gate_tier": tier, "pass_threshold": threshold}


def waiver(rid: str, expires: str = "2026-10-10", **overrides) -> dict:
    """A complete waiver, valid for a high-tier rule on TODAY (has approved_by, under 14 days)."""
    w = {"rule": rid, "owner": OWNER, "approved_by": APPROVER, "reason": "known issue, fix planned",
         "expires": expires}
    w.update(overrides)
    return {k: v for k, v in w.items() if v is not None}  # a None override removes that field


def test_valid_waiver_passes_only_its_own_rule(monkeypatch):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [False], "B": [False]}, [rule("A"), rule("B")], [waiver("A")])
    assert rows["A"]["result"] == "WAIVED"
    assert rows["A"]["waiver_owner"] == OWNER and rows["A"]["waiver_expires"] == "2026-10-10"
    assert rows["A"]["waiver_approved_by"] == APPROVER
    assert rows["B"]["result"] == "FAIL"
    assert code == 1  # B is not covered by A's waiver


def test_valid_waiver_alone_lets_the_merge_through(monkeypatch):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [False], "B": [True]}, [rule("A"), rule("B")], [waiver("A")])
    assert rows["A"]["result"] == "WAIVED" and rows["B"]["result"] == "PASS"
    assert code == 0


def test_expired_waiver_blocks_even_when_all_tests_pass(monkeypatch):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [True]}, [rule("A")], [waiver("A", expires="2026-09-30")])
    assert rows["A"]["result"] == "PASS"
    assert code == 1


def test_expired_waiver_does_not_waive_a_failing_rule(monkeypatch):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [False]}, [rule("A")], [waiver("A", expires="2026-09-30")])
    assert rows["A"]["result"] == "FAIL"
    assert code == 1


@pytest.mark.parametrize("now_utc, expected_code", [
    ("2026-10-01T00:00:00+00:00", 0),  # start of the expiry day: still valid
    ("2026-10-01T23:59:59+00:00", 0),  # end of the expiry day (already 2 Oct in India): still valid
    ("2026-10-02T00:00:00+00:00", 1),  # the day after, in UTC: expired
])
def test_waiver_valid_on_expiry_date_and_expired_the_day_after_utc(monkeypatch, now_utc, expected_code):
    freeze_utc(monkeypatch, now_utc)
    code, _ = run_gate({"A": [False]}, [rule("A")], [waiver("A", expires="2026-10-01")])
    assert code == expected_code


@pytest.mark.parametrize("missing", ["owner", "reason", "expires", "approved_by"])
def test_waiver_missing_a_field_blocks(monkeypatch, missing):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [False]}, [rule("A")], [waiver("A", **{missing: None})])
    assert rows["A"]["result"] == "FAIL"  # an incomplete waiver waives nothing
    assert code == 1


def test_low_tier_failure_warns_but_passes():
    code, rows = run_gate({"A": [False, False]}, [rule("A", tier="low")])
    assert rows["A"]["result"] == "WARN"
    assert code == 0


def test_high_tier_failure_blocks():
    code, rows = run_gate({"A": [True, True, False]}, [rule("A", tier="high")])
    assert rows["A"]["result"] == "FAIL"
    assert code == 1


@pytest.mark.parametrize("outcomes, expected_result, expected_code", [
    ([True] * 9 + [False], "PASS", 0),       # 90% meets a 0.9 threshold
    ([True] * 4 + [False], "FAIL", 1),       # 80% is below it
])
def test_medium_tier_uses_the_threshold(outcomes, expected_result, expected_code):
    code, rows = run_gate({"A": outcomes}, [rule("A", tier="medium", threshold=0.9)])
    assert rows["A"]["result"] == expected_result
    assert code == expected_code


def test_rule_with_no_tests_fails():
    code, rows = run_gate({}, [rule("A")])
    assert rows["A"]["result"] == "FAIL"
    assert code == 1


def test_high_tier_fails_on_one_failing_test_even_with_threshold_below_1():
    code, rows = run_gate({"A": [True, True, True, False]}, [rule("A", tier="high", threshold=0.5)])
    assert rows["A"]["result"] == "FAIL"  # 75% beats the 0.5 threshold, but high ignores the threshold
    assert code == 1


def test_high_waiver_without_approved_by_blocks(monkeypatch):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [False]}, [rule("A", tier="high")], [waiver("A", approved_by=None)])
    assert rows["A"]["result"] == "FAIL"
    assert code == 1


def test_medium_waiver_does_not_need_approved_by(monkeypatch):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [False]}, [rule("A", tier="medium", threshold=0.9)], [waiver("A", approved_by=None)])
    assert rows["A"]["result"] == "WAIVED"
    assert code == 0


@pytest.mark.parametrize("approver", [OWNER, "  test OWNER "])  # same person, however it is typed
def test_high_waiver_approved_by_its_owner_blocks(monkeypatch, approver):
    freeze_utc(monkeypatch, TODAY)
    code, rows = run_gate({"A": [False]}, [rule("A", tier="high")], [waiver("A", approved_by=approver)])
    assert rows["A"]["result"] == "FAIL"
    assert code == 1


@pytest.mark.parametrize("tier, expires, expected_code", [
    ("medium", "2026-10-31", 0),  # exactly 30 days ahead: allowed
    ("medium", "2026-11-01", 1),  # 31 days: too long
    ("high", "2026-10-15", 0),    # exactly 14 days ahead: allowed
    ("high", "2026-10-16", 1),    # 15 days: too long
])
def test_waiver_expiry_beyond_the_tier_maximum_blocks(monkeypatch, tier, expires, expected_code):
    freeze_utc(monkeypatch, TODAY)
    code, _ = run_gate({"A": [False]}, [rule("A", tier=tier, threshold=0.9)], [waiver("A", expires=expires)])
    assert code == expected_code


def test_waiver_for_unknown_rule_blocks(monkeypatch):
    freeze_utc(monkeypatch, TODAY)
    code, _ = run_gate({"A": [True]}, [rule("A")], [waiver("NOT_A_RULE")])
    assert code == 1
