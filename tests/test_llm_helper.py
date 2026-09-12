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
    CLI actually said, not a bare JSONDecodeError with no content.

    Matches against `repr(reply[:150])`, built the same way the error message is,
    rather than `re.escape(reply)` directly: a code-review pass caught that the two
    diverge whenever the reply contains an apostrophe, because Python's repr() picks
    its quote style (and what it escapes) based on the string's own content, not on
    whatever quoting `re.escape` was given.
    """
    reply = "{\"candidates\": [{\"model\": \"REAL-1\", \"label\": \"Rodney's cut off mid-str"
    with pytest.raises(ValueError, match=re.escape(repr(reply[:150]))):
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


def test_a_leading_draft_does_not_shadow_the_real_answer():
    """A code-review pass caught the mirror-image defect the raw_decode fix
    introduced: it took the FIRST complete JSON object, so a reply that states a
    draft or a reference case before the real answer silently returned the wrong
    one instead of erroring. Every reproduced example had the real answer LAST."""
    reply = (
        'For an unrecognised product I would say {"candidates": [], "note": "unrecognised"}. '
        'For this one: {"candidates": [{"model": "DREAME-A2", "label": "Dreame A2"}], "note": null}'
    )
    result = llm_helper.parse_reply(reply)
    assert result["candidates"] == [{"model": "DREAME-A2", "label": "Dreame A2"}]


def test_a_non_dict_candidate_item_is_dropped_not_a_crash():
    """A code-review pass caught this: candidates[:5] items were never type-checked
    before .get() was called, so a model returning a bare string in the list raised
    an unhandled AttributeError instead of being treated like any other malformed
    candidate."""
    reply = '{"candidates": ["oops-a-string", {"model": "REAL-1"}], "note": null}'
    result = llm_helper.parse_reply(reply)
    assert result["candidates"] == [{"model": "REAL-1", "label": "REAL-1"}]


def test_build_prompt_includes_the_query():
    prompt = llm_helper.build_prompt("Dreame RoboMower")
    assert "Dreame RoboMower" in prompt
