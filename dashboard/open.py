"""Open the governance dashboard in the default browser (builds it first if it doesn't exist yet).

Usage: uv run python -m dashboard.open
"""
import webbrowser

from dashboard.build import OUT_PATH, main as build

if __name__ == "__main__":
    if not OUT_PATH.exists():
        build()
    webbrowser.open(OUT_PATH.as_uri())
    print(f"Opened {OUT_PATH}")
