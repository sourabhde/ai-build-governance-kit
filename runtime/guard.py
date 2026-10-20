"""Runtime guardrail: applies the same policy.yaml at request time, using cheap deterministic checks.

Both assistants call it:
  check_input(text)            before the model runs       (R3: injection patterns)
  check_output(text)           before the answer is shown  (R2: PII; R4: need-to-know)
  check_tool_call(name, args)  before a tool runs          (R5: tool-call limits)
Only rules whose applies_to includes this system are checked. What happens on a hit follows the
rule's gate_tier: low -> logged, medium -> flagged (allowed through), high -> blocked with a safe message.

R1_grounded is NOT checked inline: judging groundedness needs an LLM call, which is too slow and too
costly per request. In production a sample of answers would be judged asynchronously instead.

Set RUNTIME_GUARD=off to switch the guard off (default on).
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from runtime.pii import redact_pii

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "policy.yaml"
EVENTS_PATH = ROOT / "runtime" / "events.jsonl"

INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\b(ignore|disregard|forget)\b.{0,30}\b(rules|instructions|guidelines|polic(y|ies))\b",
    r"\b(reveal|show|print|repeat)\b.{0,20}\bsystem prompt\b",
    r"\byou are now\b",
    r"<!--",
)]
SALARY_FIGURE = re.compile(r"\d+\s*[-‐‑–]\s*\d+\s*lakh", re.IGNORECASE)
DISCOUNT_TOOLS = {"get_quote", "apply_discount", "request_approval"}

ACTIONS = {"low": "logged", "medium": "flagged", "high": "blocked"}
SAFE_MESSAGES = {
    "R2_no_pii_leak": "I can't share customers' personal contact details.",
    "R3_injection_resistant": "I can't follow instructions that try to change my rules. Please ask your question without them.",
    "R4_need_to_know": "That information is restricted to managers.",
    "R5_agent_tool_limits": "I can't apply that discount. Discounts above the automatic limit need a manager's approval.",
}


def _injection(subject: str, context: dict, rule: dict) -> str | None:
    hit = next((p.pattern for p in INJECTION_PATTERNS if p.search(subject)), None)
    return hit and f"input matches injection pattern {hit}"


def _pii(subject: str, context: dict, rule: dict) -> str | None:
    return "output contains a customer email or phone number" if redact_pii(subject) != subject else None


def _need_to_know(subject: str, context: dict, rule: dict) -> str | None:
    if context.get("role") == "manager":
        return None
    if "manager" in context.get("source_access", []):
        return "a manager-only document was used for a non-manager"
    return "output contains salary figures for a non-manager" if SALARY_FIGURE.search(subject) else None


def _tool_limits(subject: str, context: dict, rule: dict) -> str | None:
    tool, args, limits = context.get("tool"), context.get("arguments") or {}, rule.get("limits") or {}
    if tool not in DISCOUNT_TOOLS:
        return f"unknown tool {tool}"
    if tool == "get_quote":
        return None
    try:
        percent = float(args.get("percent"))
    except (TypeError, ValueError):
        return f"{tool} called without a valid percent"
    auto, approval = limits.get("auto_apply_max_percent", 0), limits.get("approval_max_percent", 0)
    if tool == "apply_discount" and percent > auto:
        return f"apply_discount {percent:g}% is above the {auto}% automatic limit"
    if tool == "request_approval" and percent > approval:
        return f"request_approval {percent:g}% is above the {approval}% approval limit"
    return None


# Which check runs for which rule, and at which step. R1_grounded is deliberately absent (see top).
CHECKS = {
    "R3_injection_resistant": ("input", _injection),
    "R2_no_pii_leak": ("output", _pii),
    "R4_need_to_know": ("output", _need_to_know),
    "R5_agent_tool_limits": ("tool_call", _tool_limits),
}


@lru_cache
def load_policy(path: str) -> tuple[dict, str]:
    """Read policy.yaml once per process; returns the policy and its SHA-256 (the policy version)."""
    raw = Path(path).read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


@dataclass
class Verdict:
    allowed: bool = True
    rule_id: str | None = None   # the rule that fired, if any
    action: str | None = None    # blocked / flagged / logged, or None if nothing fired
    message: str | None = None   # safe message to show instead, when blocked
    latency_ms: float = 0.0      # time spent in this step's checks


class Guard:
    def __init__(self, system_id: str, policy_path=POLICY_PATH, events_path=EVENTS_PATH):
        policy, self.policy_hash = load_policy(str(policy_path))
        self.system_id = system_id
        self.rules = [r for r in policy["rules"] if system_id in (r.get("applies_to") or [])]
        self.events_path = Path(events_path)
        self.enabled = os.getenv("RUNTIME_GUARD", "on").lower() != "off"

    def check_input(self, text: str, **context) -> Verdict:
        return self._run("input", text, text, context)

    def check_output(self, text: str, input_text: str, **context) -> Verdict:
        return self._run("output", text, input_text, context)

    def check_tool_call(self, name: str, args: dict, input_text: str, **context) -> Verdict:
        return self._run("tool_call", "", input_text, {**context, "tool": name, "arguments": args})

    def _run(self, stage: str, subject: str, input_text: str, context: dict) -> Verdict:
        verdict = Verdict()
        if not self.enabled:
            return verdict
        for rule in self.rules:
            step, check = CHECKS.get(rule["id"], (None, None))
            if step != stage:
                continue
            start = time.perf_counter()
            reason = check(subject, context, rule)
            ms = (time.perf_counter() - start) * 1000
            verdict.latency_ms += ms
            if not reason:
                continue
            tier = rule.get("gate_tier", "high")
            action = ACTIONS.get(tier, "blocked")  # unknown tier -> strictest
            self._record(rule["id"], tier, action, stage, reason, input_text, context, ms)
            if action == "blocked":
                return Verdict(False, rule["id"], action, SAFE_MESSAGES.get(rule["id"], "Blocked by policy."),
                               round(verdict.latency_ms, 3))
            verdict.rule_id, verdict.action = verdict.rule_id or rule["id"], verdict.action or action
        verdict.latency_ms = round(verdict.latency_ms, 3)
        return verdict

    def _record(self, rule_id, tier, action, stage, reason, input_text, context, ms):
        """Append one event. Inputs and tool arguments are PII-redacted; outputs are never logged."""
        safe_context = {k: context[k] for k in ("role", "tool", "arguments") if k in context}
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "system_id": self.system_id,
            "rule_id": rule_id,
            "gate_tier": tier,
            "action": action,
            "stage": stage,
            "reason": reason,
            "policy_sha256": self.policy_hash,
            "input": redact_pii(input_text),
            "context": json.loads(redact_pii(json.dumps(safe_context))),
            "latency_ms": round(ms, 3),
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.events_path, "a") as f:
            f.write(json.dumps(event) + "\n")
