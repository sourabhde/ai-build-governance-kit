# Demo script (2 minutes)

## 1. The problem (15 s)

> "AI governance usually happens late: a review or questionnaire after the system is built. By then, fixing a problem is slow and expensive. I wanted to see what it looks like to put governance checks into the developer pipeline, the way we already run unit tests."

**Show:** the README's one-line summary: policy → tests → CI gate → evidence.

## 2. The policy (25 s)

**Show:** `policy.yaml`.

> "This is the policy, written as code. The system is an internal assistant answering Acme Retail policy questions. It has four rules: stay grounded, never leak customer personal data, resist prompt injection, and only show salary data to managers. Each rule has a severity, a pass threshold, and a mapping to frameworks like the OWASP LLM Top 10 and GDPR. Critical and high rules block the merge."

## 3. The red PR (25 s)

**Show:** the red demo PR and its job summary table.

> "Here's the app without guardrails. Every pull request runs 12 tests against the real app. It fails two critical rules: asked about a support ticket, it gives out the customer's email and phone number, and it repeats an instruction hidden inside a vendor document, telling users that Acme keeps data forever. The gate goes red and the merge is blocked."

## 4. The fix (25 s)

**Show:** PR #1's diff in `rag.py`, then its green check.

> "The fix is in code, not just the prompt: personal data is redacted before the model sees it and again in the answer, hidden comments are stripped from documents, and third-party documents are marked as untrusted. Same tests, and now all four rules pass. I can switch the guardrails off with one environment variable and watch them fail again."

## 5. The evidence (20 s)

**Show:** the `governance-evidence` artifact and `evidence.json`.

> "Every run leaves evidence: the commit, the model, a fingerprint of the policy version, and the pass rate for each rule. That's the record an auditor or risk owner needs, produced automatically as a side effect of development."

## 6. Close (10 s)

> "It's a small prototype: 12 tests, simple retrieval, and an LLM judge that can be wrong. But it shows the loop: policy, tests, gate, evidence. The next steps are agents with tool calling, runtime guardrails, and a dashboard across systems."
