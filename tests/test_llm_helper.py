"""Reply parsing for tools/llm-helper.py - the part that can be tested without a real
`claude`/`codex` subprocess. See that script's own docstring for why it exists and where
it runs (on the user's own machine, never inside the shopwatch container)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "llm-helper.py"
_SPEC = importlib.util.spec_from_file_location("llm_helper", _PATH)
llm_helper = importlib.util.module_from_spec(_SPEC)
sys.modules["llm_helper"] = llm_helper
_SPEC.loader.exec_module(llm_helper)


def test_a_clean_json_reply_parses():
    reply = '{"candidates": [{"model": "DREAME-A2", "label": "Dreame A2"}], "note": null}'
    result = llm_helper.parse_reply(reply)
    assert result["candidates"] == [{"model": "DREAME-A2", "label": "Dreame A2"}]
    assert result["note"] is None


def test_a_fenced_reply_still_parses():
    reply = 'Sure thing:\n```json\n{"candidates": [], "note": "too new to be sure"}\n```'
    result = llm_helper.parse_reply(reply)
    assert result["candidates"] == []
    assert result["note"] == "too new to be sure"


def test_zero_candidates_is_valid_not_an_error():
    """The honest answer when unsure - must not be treated as a parse failure."""
    reply = '{"candidates": [], "note": "no real Dreame RoboMower model exists yet"}'
    result = llm_helper.parse_reply(reply)
    assert result["candidates"] == []


def test_a_candidate_missing_a_model_is_dropped_not_kept_blank():
    reply = '{"candidates": [{"model": "", "label": "no idea"}, {"model": "REAL-1"}], "note": null}'
    result = llm_helper.parse_reply(reply)
    assert result["candidates"] == [{"model": "REAL-1", "label": "REAL-1"}]


def test_more_than_five_candidates_is_truncated():
    many = [{"model": f"M{i}", "label": f"M{i}"} for i in range(9)]
    reply = f'{{"candidates": {many!r}, "note": null}}'.replace("'", '"')
    result = llm_helper.parse_reply(reply)
    assert len(result["candidates"]) == 5


def test_reply_with_no_json_object_at_all():
    with pytest.raises(ValueError, match="no JSON"):
        llm_helper.parse_reply("I'm not sure what that product is.")


def test_a_truncated_json_reply_reports_what_the_cli_actually_said():
    """Regression: switching parse_reply to raw_decode (to fix the trailing-prose bug)
    initially dropped the diagnostic snippet for the separate case of a reply that has
    a `{` but is not valid JSON at all (e.g. cut off mid-object by a hung CLI or the
    call timeout) - whoever is debugging a failed wizard request needs to see what the
    CLI actually said, not a bare JSONDecodeError with no content."""
    reply = '{"candidates": [{"model": "REAL-1", "label": "cut off mid-str'
    with pytest.raises(ValueError, match=re.escape(reply)):
        llm_helper.parse_reply(reply)


def test_reply_missing_the_candidates_key():
    with pytest.raises(ValueError, match="candidates"):
        llm_helper.parse_reply('{"note": "hmm"}')


def test_a_reply_with_trailing_prose_after_the_json_still_parses():
    """A real Claude reply hit this: a clean JSON object followed by trailing text
    containing its own brace, which broke the old first-`{`/last-`}` slice (it grabbed
    everything up to the LAST `}` in the whole reply, not just the JSON object's own
    closing brace)."""
    reply = (
        '{"candidates": [{"model": "QA55S90DAWXXY", "label": "Samsung 55\\" S90D OLED (AU)"}], '
        '"note": null}\n\n(Let me know if you meant a different size, e.g. {55, 65}.)'
    )
    result = llm_helper.parse_reply(reply)
    assert result["candidates"] == [{"model": "QA55S90DAWXXY", "label": 'Samsung 55" S90D OLED (AU)'}]


def test_build_prompt_includes_the_query():
    prompt = llm_helper.build_prompt("Dreame RoboMower")
    assert "Dreame RoboMower" in prompt
