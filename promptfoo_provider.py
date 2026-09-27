"""promptfoo provider: lets promptfoo call our RAG app exactly as a user would."""
from rag import answer


def call_api(prompt, options, context):
    vars = context["vars"]
    try:
        result = answer(vars["question"], vars["role"])
    except Exception as e:  # report API errors to promptfoo instead of crashing the run
        return {"error": f"{type(e).__name__}: {e}"}
    return {"output": result["answer"], "metadata": {"sources": result["sources"], "model": result["model"]}}
