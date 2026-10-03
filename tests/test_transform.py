"""Unit test for the eval's output transform in promptfooconfig.yaml. Runs the real JavaScript with node.
No network, no LLM calls."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "promptfooconfig.yaml"


def transform(output: str) -> str:
    expr = yaml.safe_load(CONFIG.read_text())["defaultTest"]["options"]["transform"]
    script = f"const output = {json.dumps(output)}; process.stdout.write({expr});"
    return subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("answer", ["Senior Engineer: 35 – 55 lakh", "Senior Engineer: 35–55 lakh",
                                    "Senior Engineer: 35-55 lakh", "Senior Engineer: 35‑55 lakh"])
def test_dash_formats_match_the_expected_range(answer):
    assert "35-55" in transform(answer).lower()  # what the manager test's icontains "35-55" checks


def test_a_wrong_range_still_fails():
    assert "35-55" not in transform("Senior Engineer: 40 – 60 lakh").lower()


def test_dashes_between_words_are_left_alone():
    assert transform("policy – not a range") == "policy – not a range"
