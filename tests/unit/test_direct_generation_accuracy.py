from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "run_direct_generation_accuracy.py"
SPEC = importlib.util.spec_from_file_location("run_direct_generation_accuracy", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_parse_correctness = MODULE._parse_correctness


def test_parse_correctness_accepts_json_boolean() -> None:
    correct, reason = _parse_correctness('{"correct": true, "reason": "same value"}')

    assert correct is True
    assert reason == "same value"


def test_parse_correctness_rejects_non_json_text() -> None:
    correct, reason = _parse_correctness("not equivalent")

    assert correct is False
    assert reason == "not equivalent"
