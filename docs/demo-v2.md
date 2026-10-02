# Demo script, v2 (5 minutes)

## Before you start (once, 10 minutes ahead)

```bash
uv sync
npx promptfoo@0.123.1 eval -c promptfooconfig.yaml --env-file .env -o results/results.json
uv run python gate.py results/results.json --label "rehearsal"
uv run python -m dashboard.build
uv run python -m dashboard.open
```

Have three things open: the dashboard (on **How it works**), a terminal in the repo, and the open v2 pull request on GitHub. Make the browser window full screen; the page is sized for a shared screen.

## The 5-minute version

### 1. The problem (0:00–0:30)

**Show:** the dashboard header.

> "AI governance usually happens late, as a review after the system is built. This kit moves the checks into the developer pipeline and into the running system, driven by one policy file. The header shows the current state: the gate result, the commit, and a fingerprint of the exact policy version that was tested."

### 2. How it works (0:30–1:15)

**Click:** the **How it works** tab (the default).

> "Top half: every pull request runs tests per rule, a gate decides by tier, and evidence is written. Bottom half: the same policy runs as a guard on live requests. What it catches becomes a new test and flows back into the top half. The dashed box is the key idea: every step carries the same system ID, rule ID and policy hash, so anything can be traced to the exact rule and policy version."

### 3. Systems and rules (1:15–2:00)

**Click:** **Systems**, then **Rules**. Click **R5_agent_tool_limits** to expand its test cases.

> "Two AI systems are governed: a policy assistant and a quoting agent, each with its EU AI Act risk tier. Each rule says which systems it applies to and has a gate tier. High means any single failure blocks the merge; medium compares the pass rate to a threshold. Severity is just a label. For the agent, the tests don't judge wording; they check what it did: which tools it called, with what arguments, and its final decision."

### 4. History: the gate catching real breakages (2:00–2:50)

**Click:** **History**. Then, in the header, pick run **#2 agent misconfigured** from the run selector and click **Rules**.

> "These are three real recorded runs. In the first, the policy assistant's own guardrails were switched off: personal data leaked and an injection got through, so R2 and R3 failed and the gate blocked. In the second, someone changed one number, raising the agent's automatic discount limit from 10 to 30 percent. The prompt still looked fine, but the agent started applying 20 and 25 percent discounts, so R5 failed and the gate blocked. The third is the current code: everything passes."

**Click:** the run selector back to the latest run.

### 5. Runtime guard and feedback loop (2:50–3:50)

**Click:** **Runtime events**, then **Feedback loop**.

> "At run time the guard checks every request with cheap, deterministic checks, in hundredths of a millisecond, as you can see in the latency column. It blocked a request for a customer's contact details, two prompt injections and a 25 percent discount the agent tried to apply. Inputs are stored with personal data redacted; outputs are never stored. Each event became a regression test, which a person reviews and commits, and here is that test's result in the latest run. Groundedness isn't checked inline, because it needs an LLM call; in production it would be sampled asynchronously."

Optional live step, in the terminal (needs the network):

```bash
uv run python -m runtime.simulate
```

### 6. Waivers and evidence (3:50–4:30)

**Click:** **Waivers**, then **Evidence**, then **View raw JSON**.

> "If a team must ship with a known failure, they add a waiver: a named owner, a reason and an expiry. For high-risk rules a second person must approve it, and it can run for at most 14 days. An expired or self-approved waiver fails the gate by itself. Every run writes this evidence: commit, models, policy hash, per-rule results and per-test results, which is what an auditor or risk owner needs."

### 7. Close (4:30–5:00)

**Show:** the v2 pull request with its required **govern** check.

> "So: one policy, tested on every pull request, enforced on every request, with the runtime feeding the tests and a record for every run. It's a prototype: the tests are few, the PII and injection checks are simple patterns, and the judge model can be wrong. The architecture document lists what a production version would add."

## The 60-second version

1. **How it works** tab (20 s): "One policy file drives tests on every pull request and a guard on every live request. What the guard catches becomes a new test. Every step carries the system ID, rule ID and policy hash."
2. **History** tab (20 s): "Three real runs. Switching off the guardrails, or changing one number in the agent's discount limit, made the gate block. The current code passes."
3. **Feedback loop** tab (20 s): "Live catches, blocked in hundredths of a millisecond, each turned into a regression test that CI now runs. And every run leaves evidence tied to the exact policy version."

## Fallback if the network or the model API fails

Everything in the 5-minute version except the optional live step works offline from committed files:

- **Dashboard:** `uv run python -m dashboard.build` needs no network. Run history comes from the committed `evidence/history.jsonl`, the runtime events from the committed synthetic `runtime/sample_events.jsonl`, and the feedback loop from the committed `tests/generated/runtime_cases.yaml`.
- **Evidence tab:** this needs a local `results/evidence.json`. Keep the one from the rehearsal run; it is not committed. Without it, the tab says "No evidence file yet" rather than showing made-up numbers. As a backup, download the `governance-dashboard` artifact from the v2 pull request's CI run in advance and open that file.
- **Instead of the live simulation:** say "here are the events from a recorded run" and use the **Runtime events** tab.
- **To show something running live without the API:** `uv run pytest -q` runs the gate, guard, test generator and dashboard unit tests (no network, no model calls) in under a second.
