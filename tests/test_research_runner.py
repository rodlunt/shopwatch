"""Reply parsing for the host-level research runner - the part that can be tested
without a real `claude` subprocess. See deploy/research-runner.py's own docstring for
why this script exists and where it runs (never inside the shopwatch container)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "deploy" / "research-runner.py"
_SPEC = importlib.util.spec_from_file_location("research_runner", _PATH)
research_runner = importlib.util.module_from_spec(_SPEC)
sys.modules["research_runner"] = research_runner
_SPEC.loader.exec_module(research_runner)


def test_a_clean_json_reply_with_a_price_parses(monkeypatch):
    reply = '{"found": true, "price": 1099, "stock": "In stock", "url": "https://x", "reason": "ok"}'
    result = research_runner.parse_research_reply(reply)
    assert result["price"] == 1099
    assert result["stock"] == "In stock"


def test_a_fenced_reply_still_parses():
    reply = 'Here you go:\n```json\n{"found": true, "price": 500, "reason": "ok"}\n```'
    result = research_runner.parse_research_reply(reply)
    assert result["price"] == 500


def test_reply_survives_trailing_prose_with_its_own_brace():
    """Same defect app/offers.py's parse_cli_output and tools/llm-helper.py's
    parse_reply both had: a naive first-`{`/last-`}` slice breaks the moment the
    reply's trailing text has its own brace pair."""
    reply = ('{"found": true, "price": 1099, "stock": "In stock", "url": "https://x",'
              ' "reason": "ok"}\n\n(Prices vary by size, e.g. {55, 65}.)')
    result = research_runner.parse_research_reply(reply)
    assert result["price"] == 1099


def test_a_leading_reference_price_does_not_shadow_the_real_answer():
    """A code-review pass caught the mirror-image defect the raw_decode fix
    introduced: it took the FIRST complete JSON object, so a reply that states an
    older/similar model's price before the exact model requested silently returned
    the wrong price instead of erroring. Every reproduced example had the real
    answer LAST."""
    reply = (
        'For a similar older model I found {"found": true, "price": 999, "reason": "similar model"} '
        'but for the exact model requested: '
        '{"found": true, "price": 1099, "stock": "In stock", "url": "https://x", "reason": "ok"}'
    )
    result = research_runner.parse_research_reply(reply)
    assert result["price"] == 1099


def test_found_as_a_string_is_not_treated_as_true():
    """`"found": "false"` is a non-empty string, which is truthy in Python - a model
    that returns the word instead of the JSON boolean must not bypass the
    not-found guard."""
    reply = '{"found": "false", "price": 199, "reason": "could not confirm"}'
    with pytest.raises(research_runner.RunnerError) as exc_info:
        research_runner.parse_research_reply(reply)
    assert exc_info.value.status == "NEEDS_MANUAL_CHECK"


def test_a_nan_price_is_not_treated_as_usable():
    """Python's json parser accepts the non-standard NaN token by default; NaN is a
    float and is not None, so it would otherwise pass the found-a-price guard and
    get imported as a real price that silently fails every trigger comparison."""
    reply = '{"found": true, "price": NaN, "reason": "estimate"}'
    with pytest.raises(research_runner.RunnerError) as exc_info:
        research_runner.parse_research_reply(reply)
    assert exc_info.value.status == "NEEDS_MANUAL_CHECK"


def test_found_false_is_reported_as_needs_manual_check():
    reply = '{"found": false, "price": null, "reason": "page blocked the request"}'
    with pytest.raises(research_runner.RunnerError) as exc_info:
        research_runner.parse_research_reply(reply)
    assert exc_info.value.status == "NEEDS_MANUAL_CHECK"
    assert "blocked" in exc_info.value.note


def test_found_true_with_no_price_is_still_needs_manual_check():
    """A model claiming success with no number is not a usable finding either."""
    reply = '{"found": true, "price": null, "reason": "saw the page, no price listed"}'
    with pytest.raises(research_runner.RunnerError) as exc_info:
        research_runner.parse_research_reply(reply)
    assert exc_info.value.status == "NEEDS_MANUAL_CHECK"


def test_reply_with_no_json_object_at_all():
    with pytest.raises(research_runner.RunnerError) as exc_info:
        research_runner.parse_research_reply("I couldn't find pricing for this item.")
    assert exc_info.value.status == "NEEDS_MANUAL_CHECK"
    assert "no JSON" in exc_info.value.note


def test_reply_with_malformed_json():
    with pytest.raises(research_runner.RunnerError) as exc_info:
        research_runner.parse_research_reply('{"found": true, "price": }')
    assert exc_info.value.status == "NEEDS_MANUAL_CHECK"


def test_empty_reply():
    with pytest.raises(research_runner.RunnerError):
        research_runner.parse_research_reply("")
