"""promptfoo provider: runs the quoting assistant and returns its JSON (answer + tool calls) as output."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, so `agent` and `rag` import

from agent.assistant import run  # noqa: E402


def call_api(prompt, options, context):
    try:
        result = run(context["vars"]["question"])
    except Exception as e:  # report API errors to promptfoo instead of crashing the run
        return {"error": f"{type(e).__name__}: {e}"}
    return {"output": json.dumps(result)}
