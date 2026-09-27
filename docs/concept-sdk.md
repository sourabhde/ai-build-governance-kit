> **Concept only, not a real product.** `govkit` does not exist. This page sketches how the ideas in this repo could be packaged as a developer SDK. It is a personal concept, not affiliated with or endorsed by any company.

# govkit: a concept developer SDK for AI governance

**Idea:** make governance checks as easy to add to an AI project as a linter. A developer picks a policy, `govkit` generates the tests, CI enforces them, and the results are recorded automatically.

## 1. Install

```bash
pip install govkit        # or: uv add govkit
```

## 2. Initialise with a policy

```bash
govkit init --policy customer-support-assistant
```

This would:
- download a ready-made policy (like this repo's `policy.yaml`) with rules, severities, thresholds and framework mappings (OWASP LLM Top 10, NIST AI RMF, GDPR)
- generate a starter test suite for those rules, which the team then adapts to their app
- write a CI workflow that runs `govkit check`

## 3. Check in CI

```bash
govkit check
```

This would run the tests, compare each rule's pass rate with its threshold, fail the build if a blocking rule fails, and write an evidence file (what was tested, which policy version, which model, what passed).

## 4. Send results to an AI inventory

```bash
govkit check --report
```

Each run's evidence would be sent to the organisation's AI inventory: the list of AI systems, their owners and risk tiers, and their current compliance status. The inventory stays up to date as a side effect of normal development, with no separate questionnaire to fill in.

## How this could plug into an AI governance platform

- **Policy library in:** governance, privacy and security teams maintain approved policies in a central platform. `govkit init` pulls them, so developers start from rules the organisation has already agreed on instead of writing their own.
- **Evidence out to the system record:** every `govkit check` result is attached to that AI system's record in the platform, with its commit, model, policy version and pass rates. An auditor or risk owner sees current, test-backed status instead of a one-off assessment.
- **The loop:** if a policy changes centrally, the next CI run re-tests against the new version, and the system record shows which systems now fail.

## Open questions

- Who owns the tests: the central team or each product team?
- How are LLM-judge results reviewed, given the judge can be wrong?
- How are runtime checks (in production) linked with build-time checks (in CI)?
