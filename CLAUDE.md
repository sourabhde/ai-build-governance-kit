# ai-build-governance-kit

Personal learning project by Sourabh De. Demonstrates "governance-as-code for AI":
policy.yaml -> automated eval tests (promptfoo) -> CI gate (GitHub Actions) -> evidence file.

## Data
data/ holds 5 small documents for a fictional company. The first line of each file declares its access level
(all / employee / manager). vendor_note_cloudfax.md contains a planted prompt injection for testing.
Roles for the app: "employee" and "manager".

## Constraints
- Keep everything small and readable; a PM must be able to explain every file.
- Python 3.12 via uv (`uv run ...`, `uv add ...`). No LangChain or other agent/RAG frameworks.
- LLM: Groq API, key in .env as GROQ_API_KEY. NEVER print, log, or commit .env or the key.
  Answering model: openai/gpt-oss-120b (llama-3.3-70b-versatile was retired from Groq).
  Judge model: qwen/qwen3.8-27b on Groq (different model family from the answering model).
- Evals: promptfoo. Prefer deterministic code checks; use an LLM judge only where meaning matters,
  and the judge must be a DIFFERENT model from the one answering.
- SDK docs are a clearly labelled personal concept; never use any other names or branding.

## Plan
S1 rag.py: small RAG over data/ with role-based access filtering at retrieval
S2 policy.yaml: 4 rules (grounded, no PII leakage, injection-resistant, confidential only for managers)
S3 promptfoo suite (~15 tests); at least one should fail first, then fix
S4 GitHub Action: run suite on PRs, block on failure, upload results as evidence
S5 concept SDK README; S6 repo README + demo script
