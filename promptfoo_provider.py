"""promptfoo provider: lets promptfoo call our RAG app exactly as a user would."""
import os

from rag import answer

# The eval tests each app's OWN controls, so the runtime guard is off here by default
# (it has its own unit tests in tests/test_guard.py). Set RUNTIME_GUARD=on to test both layers together.
os.environ.setdefault("RUNTIME_GUARD", "off")


def call_api(prompt, options, context):
    vars = context["vars"]
    try:
        result = answer(vars["question"], vars["role"])
    except Exception as e:  # report API errors to promptfoo instead of crashing the run
        return {"error": f"{type(e).__name__}: {e}"}
    return {"output": result["answer"], "metadata": {"sources": result["sources"], "model": result["model"]}}
