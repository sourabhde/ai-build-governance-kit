# Walkthrough (v1, 2 minutes)

A short tour of the v1 kit: policy → tests → CI gate → evidence.

## 1. The problem (15 s)

**Show:** the README's one-line summary: policy → tests → CI gate → evidence.

**What you'll see:** the idea behind the kit. Governance checks usually happen late, as a review after the system is built; here they run in the developer pipeline on every pull request, like unit tests.

## 2. The policy (25 s)

**Show:** `policy.yaml`.

**What you'll see:** the policy written as code for an internal assistant that answers a company's policy questions. It has four rules: stay grounded, never leak customer personal data, resist prompt injection, and only show salary data to managers. Each rule has a severity, a pass threshold and a mapping to frameworks such as the OWASP LLM Top 10 and GDPR. Critical and high rules block the merge.

## 3. The red PR (25 s)

**Show:** [PR #3](https://github.com/sourabhde/ai-build-governance-kit/pull/3) description → the red `govern` check marked **Required** → the greyed-out Merge button → the Policy gate log: `R2_no_pii_leak 0/3 FAIL`, R1/R3/R4 PASS, `GATE: BLOCKED`.

**What you'll see:** a well-meant change request (support staff want to call customers back) that quietly turns off PII redaction for every employee. Every pull request runs 12 tests against the real app; R2 (no PII leak) fails all three of its tests while the other rules pass. The gate names the exact rule and the regulations it maps to (GDPR data minimisation, OWASP LLM02), not just "tests failed". The check is required, so the Merge button is disabled, even for the repo owner.

_Backup:_ if PR #3 isn't available, check out the `before-guardrails` tag and run the eval to show R2 and R3 failing.

## 4. The fix (25 s)

**Show:** PR #1's diff in `rag.py`, then its green check.

**What you'll see:** the fix is in code, not just the prompt. Personal data is redacted before the model sees it and again in the answer, hidden comments are stripped from documents, and third-party documents are marked as untrusted. The same tests now pass on all four rules. A single environment variable (see the README) switches the guardrails off, and the failures come back.

## 5. The evidence (20 s)

**Show:** the `governance-evidence` artifact and `evidence.json`.

**What you'll see:** the record every run leaves: the commit, the model, a fingerprint (hash) of the policy version and the pass rate for each rule. It is produced automatically as a side effect of development, for an auditor or risk owner.

## 6. Close (10 s)

**What you'll see:** the limits of the prototype (12 tests, simple retrieval, an LLM judge that can be wrong) and the loop it demonstrates: policy, tests, gate, evidence. Next steps: agents with tool calling, runtime guardrails and a dashboard across systems.
