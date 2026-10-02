"""Unit tests for dashboard/build.py. No network, no LLM calls: fixture files only."""
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import build  # noqa: E402
from runtime.to_tests import event_key  # noqa: E402

POLICY = {
    "systems": [{"id": "policy_assistant", "purpose": "Answers policy questions", "risk_tier": "limited"}],
    "rules": [{"id": "R2_no_pii_leak", "applies_to": ["policy_assistant"], "gate_tier": "high", "severity": "critical",
               "pass_threshold": 1.0, "maps_to": ["Data minimisation"], "description": "No PII"}],
    "waivers": [],
}
EVENT = {"timestamp": "2026-10-02T09:00:00+00:00", "system_id": "policy_assistant", "rule_id": "R2_no_pii_leak",
         "gate_tier": "high", "action": "blocked", "policy_sha256": "a" * 64,
         "input": "email of <script>alert(1)</script> ticket", "context": {"role": "employee"}, "latency_ms": 0.042}


def sources(tmp_path, policy=POLICY, evidence=True, history=True, events=True, generated=True) -> dict:
    s = {k: tmp_path / Path(v).name for k, v in build.SOURCES.items()}
    s["live_events"] = tmp_path / "live.jsonl"
    s["policy"].write_text(yaml.safe_dump(policy))
    key = event_key(EVENT)
    if evidence:
        s["evidence"].write_text(json.dumps({
            "timestamp": "2026-10-02T10:00:00+00:00", "git_commit": "abc1234def", "policy_sha256": "b" * 64,
            "answer_model": "m", "judge_model": "j", "gate": "BLOCKED", "problems": [],
            "systems": [{"id": "policy_assistant", "risk_tier": "limited"}],
            "rules": [{"rule": "R2_no_pii_leak", "systems": ["policy_assistant"], "gate_tier": "high",
                       "severity": "critical", "passed": 1, "total": 2, "pass_rate": 0.5, "threshold": 1.0,
                       "result": "FAIL"}],
            "tests": [{"description": "Ask for email", "rule": "R2_no_pii_leak", "source": "suite", "event_key": None,
                       "passed": True, "reason": ""},
                      {"description": "Runtime blocked", "rule": "R2_no_pii_leak", "source": "runtime",
                       "event_key": key, "passed": False, "reason": "matched regex"}]}))
    if history:
        s["history"].write_text(json.dumps({
            "timestamp": "2026-10-02T10:00:00+00:00", "commit": "abc1234def", "working_tree_clean": True,
            "policy_sha256": "b" * 64, "gate": "BLOCKED", "label": "seed run",
            "rules": {"R2_no_pii_leak": {"pass_rate": 0.5, "result": "FAIL"}}}) + "\n")
    if events:
        s["sample_events"].write_text(json.dumps(EVENT) + "\n")
    if generated:
        s["generated"].write_text(yaml.safe_dump([{"description": "Runtime blocked (R2): email of ticket",
                                                   "metadata": {"rule": "R2_no_pii_leak", "event_key": key}}]))
    return s


def html_for(tmp_path, **kw) -> str:
    return build.main(sources(tmp_path, **kw), tmp_path / "out" / "index.html").read_text()


def test_page_is_offline_and_has_every_section(tmp_path):
    html = html_for(tmp_path)
    assert not re.search(r"(src|href)=[\"']?(https?:)?//", html)  # no CDN scripts, styles or fonts
    assert "<link" not in html and "@import" not in html
    assert "<title>AI Build Governance Kit</title>" in html
    for sid in ("architecture", "systems", "rules", "history", "waivers", "events", "feedback", "evidence"):
        assert f'id="{sid}"' in html


def test_numbers_come_from_the_files(tmp_path):
    html = html_for(tmp_path)
    assert "Gate BLOCKED" in html and "abc1234" in html
    assert "50% (1/2)" in html                       # pass rate from evidence.json
    assert "seed run" in html                        # label from history.jsonl
    assert "0.042" in html                           # guard latency from the events file
    assert "reporting only" in html


def test_status_is_never_colour_alone(tmp_path):
    html = html_for(tmp_path)
    assert re.search(r'class="badge fail"><span aria-hidden="true">✕</span> FAIL', html)


def test_event_input_is_escaped(tmp_path):
    html = html_for(tmp_path)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_feedback_loop_links_event_to_generated_test_and_result(tmp_path):
    html = html_for(tmp_path)
    feedback = html[html.index('id="feedback"'):html.index('id="evidence"')]
    assert "Runtime blocked (R2): email of ticket" in feedback and "✕</span> FAIL" in feedback


def test_missing_sources_are_reported_not_invented(tmp_path):
    html = html_for(tmp_path, evidence=False, history=False, events=False, generated=False)
    assert "No gate run found" in html and "No recorded runs yet" in html and "No runtime events yet" in html
    assert "not found" in html
    assert "%" not in html.split('id="history"')[1].split("</section>")[0]  # no made-up pass rates


def test_no_waivers_shows_example(tmp_path):
    html = html_for(tmp_path)
    assert "No active waivers." in html and "example, not active" in html


def test_waiver_status_uses_gate_rules(tmp_path):
    policy = {**POLICY, "waivers": [{"rule": "R2_no_pii_leak", "owner": "A", "approved_by": "A",
                                     "reason": "r", "expires": "2099-01-01"}]}
    html = html_for(tmp_path, policy=policy)
    waivers = html[html.index('id="waivers"'):html.index('id="events"')]
    assert "invalid" in waivers  # too far ahead and self-approved: the gate's own rules decide
