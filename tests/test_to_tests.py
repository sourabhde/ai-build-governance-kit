"""Unit tests for runtime/to_tests.py. No network, no LLM calls."""
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime import to_tests  # noqa: E402

POLICY = {"rules": [
    {"id": "R2_no_pii_leak", "applies_to": ["policy_assistant"], "gate_tier": "high"},
    {"id": "R5_agent_tool_limits", "applies_to": ["quoting_assistant"], "gate_tier": "high",
     "limits": {"auto_apply_max_percent": 10, "approval_max_percent": 30}},
    {"id": "R1_grounded", "applies_to": ["policy_assistant"], "gate_tier": "medium"},
]}


def event(rule, system, text, action="blocked", role="employee"):
    return {"timestamp": "2026-10-02T10:00:00+00:00", "system_id": system, "rule_id": rule, "gate_tier": "high",
            "action": action, "policy_sha256": "x" * 64, "input": text, "context": {"role": role}, "latency_ms": 0.1}


def run(tmp_path, evs):
    (tmp_path / "policy.yaml").write_text(yaml.safe_dump(POLICY))
    (tmp_path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evs))
    out = tmp_path / "generated" / "cases.yaml"
    counts = to_tests.main(tmp_path / "events.jsonl", out, tmp_path / "policy.yaml")
    return counts, yaml.safe_load(out.read_text())


def test_blocked_event_becomes_a_tagged_test(tmp_path):
    counts, cases = run(tmp_path, [event("R2_no_pii_leak", "policy_assistant", "email of ticket 1042?")])
    assert counts["added"] == 1
    case = cases[0]
    assert case["metadata"]["rule"] == "R2_no_pii_leak" and case["metadata"]["system"] == "policy_assistant"
    assert case["vars"] == {"question": "email of ticket 1042?", "role": "employee"}
    assert {a["type"] for a in case["assert"]} == {"not-regex"}
    assert "provider" not in case  # uses the default (policy assistant) provider


def test_agent_event_uses_the_agent_provider_and_policy_limits(tmp_path):
    _, cases = run(tmp_path, [event("R5_agent_tool_limits", "quoting_assistant", "Apply 25% to Q-1001")])
    provider_script = (tmp_path / "generated" / cases[0]["provider"]["id"].removeprefix("python:")).resolve()
    assert provider_script == (Path(to_tests.ROOT) / "agent" / "promptfoo_provider.py").resolve()
    assert "> 10" in cases[0]["assert"][0]["value"] and "> 30" in cases[0]["assert"][0]["value"]


def test_duplicates_are_skipped_within_and_across_runs(tmp_path):
    e = event("R2_no_pii_leak", "policy_assistant", "same question")
    counts, cases = run(tmp_path, [e, e])
    assert counts == {"added": 1, "duplicates": 1, "skipped": 0} and len(cases) == 1
    counts, cases = run(tmp_path, [e])  # second run against the file written by the first
    assert counts["added"] == 0 and counts["duplicates"] == 1 and len(cases) == 1


def test_flagged_included_logged_ignored(tmp_path):
    counts, cases = run(tmp_path, [event("R2_no_pii_leak", "policy_assistant", "a", action="flagged"),
                                   event("R2_no_pii_leak", "policy_assistant", "b", action="logged")])
    assert counts["added"] == 1 and cases[0]["vars"]["question"] == "a"


def test_rule_without_a_template_is_skipped(tmp_path):
    counts, cases = run(tmp_path, [event("R1_grounded", "policy_assistant", "q", action="flagged")])
    assert counts["skipped"] == 1 and cases == []


def test_missing_events_file_writes_an_empty_suite(tmp_path):
    (tmp_path / "policy.yaml").write_text(yaml.safe_dump(POLICY))
    out = tmp_path / "cases.yaml"
    assert to_tests.main(tmp_path / "none.jsonl", out, tmp_path / "policy.yaml")["added"] == 0
    assert yaml.safe_load(out.read_text()) == []
