# Walkthrough, v2 (5 minutes)

A guided tour of v2 using the dashboard tabs.

## Before you start (once, 10 minutes ahead)

```bash
uv sync
npx promptfoo@0.123.1 eval -c promptfooconfig.yaml --env-file .env -o results/results.json
uv run python gate.py results/results.json --label "rehearsal"
uv run python -m dashboard.build
uv run python -m dashboard.open
```

Have three things open: the dashboard (on **How it works**), a terminal in the repo, and the open v2 pull request on GitHub. Make the browser window full screen; the page is sized for a shared screen.

## The 5-minute walkthrough

### 1. The problem (0:00–0:30)

**Show:** the dashboard header.

**What you'll see:** the current state at a glance: the gate result, the commit and a fingerprint (hash) of the exact policy version that was tested. The kit moves governance checks into the developer pipeline and into the running system, driven by one policy file, instead of a review after the system is built.

### 2. How it works (0:30–1:15)

**Click:** the **How it works** tab (the default).

**What you'll see:** the top half is build time: every pull request runs tests per rule, a gate decides by tier, and evidence is written. The bottom half is run time: the same policy runs as a guard on live requests, and what it catches becomes a new test that flows back into the top half. The dashed box shows the shared context: every step carries the same system ID, rule ID and policy hash, so anything can be traced to the exact rule and policy version.

### 3. Systems and rules (1:15–2:00)

**Click:** **Systems**, then **Rules**. Click **R5_agent_tool_limits** to expand its test cases.

**What you'll see:** two governed AI systems, a policy assistant and a quoting agent, each with its EU AI Act risk tier. Each rule lists the systems it applies to and its gate tier: high blocks on any single failure, medium compares the pass rate to a threshold, and severity is a reporting label only. The agent's tests don't judge wording; they check what it did: which tools it called, with which arguments, and its final decision.

### 4. History: the gate catching real breakages (2:00–2:50)

**Click:** **History**. Then, in the header, pick run **#2 agent misconfigured** from the run selector and click **Rules**.

**What you'll see:** three recorded runs. In the first, the policy assistant's own guardrails were switched off: personal data leaked and an injection got through, so R2 and R3 failed and the gate blocked. In the second, one number changed, raising the agent's automatic discount limit from 10 to 30 percent; the prompt still looked fine, but the agent applied 20 and 25 percent discounts, so R5 failed and the gate blocked. The third is the current code, and everything passes.

**Click:** the run selector back to the latest run.

**Optional, on GitHub:** show both blocked changes side by side. [PR #3](https://github.com/sourabhde/ai-build-governance-kit/pull/3) is the policy assistant example: support staff see customer contact details, so R2 fails. [PR #6](https://github.com/sourabhde/ai-build-governance-kit/pull/6) is the agent example: the auto-approve discount limit is raised to 30%, so R5 fails. On each, show the red required `govern` check and the gate table in the job summary.

**What you'll see:** neither is a staged failure in a test file. Both are realistic one-line change requests with a business reason, and the gate blocks both.

### 5. Runtime guard and feedback loop (2:50–3:50)

**Click:** **Runtime events**, then **Feedback loop**.

**What you'll see:** the guard checks every request with cheap, deterministic checks; the latency column shows hundredths of a millisecond. It blocked a request for a customer's contact details, two prompt injections and a 25 percent discount the agent tried to apply. Inputs are stored with personal data redacted, and outputs are never stored. Each event became a regression test, reviewed and committed by a person, shown with its result in the latest run. Groundedness isn't checked inline because it needs an LLM call; a production version would sample it asynchronously.

Optional live step, in the terminal (needs the network):

```bash
uv run python -m runtime.simulate
```

### 6. Waivers and evidence (3:50–4:30)

**Click:** **Waivers**, then **Evidence**, then **View raw JSON**.

**What you'll see:** how a team ships with a known failure: a waiver with a named owner, a reason and an expiry. For high-tier rules a second person must approve it and it can run for at most 14 days; an expired or self-approved waiver fails the gate by itself. The evidence for every run follows: commit, models, policy hash, per-rule results and per-test results, the record an auditor or risk owner needs.

### 7. Close (4:30–5:00)

**Show:** the v2 pull request with its required **govern** check.

**What you'll see:** the whole loop in one place: one policy, tested on every pull request, enforced on every request, with the runtime feeding the tests and a record for every run. The limits are stated in [architecture.md](architecture.md): few tests, simple pattern-based PII and injection checks, and a judge model that can be wrong.

## The 60-second walkthrough

1. **How it works** tab (20 s). **What you'll see:** one policy file driving tests on every pull request and a guard on every live request, what the guard catches becoming a new test, and the system ID, rule ID and policy hash on every step.
2. **History** tab (20 s). **What you'll see:** three recorded runs. Switching off the guardrails, or changing one number in the agent's discount limit, made the gate block; the current code passes.
3. **Feedback loop** tab (20 s). **What you'll see:** live catches blocked in hundredths of a millisecond, each turned into a regression test that CI now runs, with evidence tied to the exact policy version.

## Fallback if the network or the model API fails

Everything in the 5-minute walkthrough except the optional live step works offline from committed files:

- **Dashboard:** `uv run python -m dashboard.build` needs no network. Run history comes from the committed `evidence/history.jsonl`, the runtime events from the committed synthetic `runtime/sample_events.jsonl`, and the feedback loop from the committed `tests/generated/runtime_cases.yaml`.
- **Evidence tab:** this needs a local `results/evidence.json`. Keep the one from the rehearsal run; it is not committed. Without it, the tab says "No evidence file yet" rather than showing made-up numbers. As a backup, download the `governance-dashboard` artifact from the v2 pull request's CI run in advance and open that file.
- **Instead of the live simulation:** use the **Runtime events** tab, which shows events from a recorded run.
- **To show something running live without the API:** `uv run pytest -q` runs the gate, guard, test generator and dashboard unit tests (no network, no model calls) in under a second.
