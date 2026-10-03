"""promptfoo provider: runs the quoting assistant and returns its JSON (answer + tool calls) as output."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, so `agent` and `rag` import

from agent.assistant import run  # noqa: E402

# The eval tests each app's OWN controls, so the runtime guard is off here by default
# (it has its own unit tests in tests/test_guard.py). Set RUNTIME_GUARD=on to test both layers together.
os.environ.setdefault("RUNTIME_GUARD", "off")


def call_api(prompt, options, context):
    try:
        result = run(context["vars"]["question"])
    except Exception as e:  # report API errors to promptfoo instead of crashing the run
        return {"error": f"{type(e).__name__}: {e}"}
    return {"output": json.dumps(result)}
