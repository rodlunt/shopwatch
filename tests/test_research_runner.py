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



# --------------------------------------------------- retailer search (Firecrawl-backed)

def test_bare_domain_strips_www_and_scheme():
    assert research_runner._bare_domain("https://www.jbhifi.com.au/products/x") == "jbhifi.com.au"
    assert research_runner._bare_domain("bunnings.com.au") == "bunnings.com.au"


def test_bare_domain_is_lowercased():
    """The control this test exists for: without lowercasing, a Firecrawl result at
    https://WWW.NewStore.example and a stored homepage at https://www.newstore.example
    would never match each other in discover_retailers' exclusion/dedup sets."""
    assert research_runner._bare_domain("https://WWW.NewStore.example/product") == "newstore.example"
    assert research_runner._bare_domain("https://www.newstore.example") == "newstore.example"


def test_domain_display_name_strips_tld_and_title_cases():
    assert research_runner._domain_display_name("jb-hifi.com.au") == "Jb Hifi"
    assert research_runner._domain_display_name("bunnings.com.au") == "Bunnings"


def test_name_from_search_result_prefers_a_short_trailing_title_segment():
    name = research_runner._name_from_search_result(
        "https://www.example.com.au/x", "Samsung Soundbar HW-Q930H | Example Store"
    )
    assert name == "Example Store"


def test_name_from_search_result_falls_back_to_domain_when_trailing_segment_has_a_digit():
    """A trailing "| $899" or "- SKU1234" is a price or SKU, not a store name - trusting
    it would show the user a nonsense "retailer" instead of an honest domain guess."""
    name = research_runner._name_from_search_result(
        "https://www.example.com.au/x", "Samsung Soundbar HW-Q930H | $899"
    )
    assert name == "Example"


def test_name_from_search_result_falls_back_to_domain_with_no_separator():
    name = research_runner._name_from_search_result(
        "https://www.example.com.au/x", "Samsung Soundbar HW-Q930H"
    )
    assert name == "Example"


def _fake_search_response(monkeypatch, data, success=True):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": success, "data": data}

    monkeypatch.setattr(research_runner.requests, "post", lambda *a, **k: FakeResponse())


def test_discover_retailers_returns_candidates_from_search_results(monkeypatch):
    _fake_search_response(monkeypatch, [
        {"url": "https://www.newstore.example/product", "title": "Soundbar | New Store"},
    ])
    result = research_runner.discover_retailers(
        "http://firecrawl", "Samsung Soundbar", "HW-Q930H", [], [],
    )
    assert result["retailers"] == [{"name": "New Store", "homepage": "https://newstore.example"}]


def test_discover_retailers_excludes_by_homepage_domain(monkeypatch):
    """The control this test exists for: without domain-based exclusion, a retailer
    already selected for this product would be suggested again as if it were new."""
    _fake_search_response(monkeypatch, [
        {"url": "https://www.knownstore.example/product", "title": "Soundbar | Known Store"},
        {"url": "https://www.newstore.example/product", "title": "Soundbar | New Store"},
    ])
    result = research_runner.discover_retailers(
        "http://firecrawl", "Samsung Soundbar", "HW-Q930H",
        [], ["https://www.knownstore.example"],
    )
    names = [r["name"] for r in result["retailers"]]
    assert "Known Store" not in names
    assert "New Store" in names


def test_discover_retailers_excludes_by_name(monkeypatch):
    _fake_search_response(monkeypatch, [
        {"url": "https://www.newstore.example/product", "title": "Soundbar | New Store"},
    ])
    result = research_runner.discover_retailers(
        "http://firecrawl", "Samsung Soundbar", "HW-Q930H", ["New Store"], [],
    )
    assert result["retailers"] == []


def test_discover_retailers_deduplicates_the_same_domain(monkeypatch):
    _fake_search_response(monkeypatch, [
        {"url": "https://www.newstore.example/a", "title": "Soundbar | New Store"},
        {"url": "https://www.newstore.example/b", "title": "Soundbar A/V | New Store"},
    ])
    result = research_runner.discover_retailers(
        "http://firecrawl", "Samsung Soundbar", "HW-Q930H", [], [],
    )
    assert len(result["retailers"]) == 1


def test_discover_retailers_excludes_by_homepage_domain_regardless_of_case(monkeypatch):
    _fake_search_response(monkeypatch, [
        {"url": "https://WWW.KnownStore.example/product", "title": "Soundbar | Known Store"},
    ])
    result = research_runner.discover_retailers(
        "http://firecrawl", "Samsung Soundbar", "HW-Q930H",
        [], ["https://www.knownstore.example"],
    )
    assert result["retailers"] == []


def test_discover_retailers_raises_when_firecrawl_reports_failure(monkeypatch):
    """The control this test exists for: a failed search must not silently look like
    a successful search that simply found nothing (hardening.md rule 2)."""
    _fake_search_response(monkeypatch, [], success=False)
    with pytest.raises(RuntimeError, match="did not succeed"):
        research_runner.discover_retailers("http://firecrawl", "Product", "MODEL", [], [])


def test_discover_retailers_raises_when_the_request_itself_fails(monkeypatch):
    def fake_post(*a, **k):
        raise research_runner.requests.RequestException("connection refused")

    monkeypatch.setattr(research_runner.requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="firecrawl search failed"):
        research_runner.discover_retailers("http://firecrawl", "Product", "MODEL", [], [])


def test_the_claude_call_grants_web_search_and_fetch(monkeypatch):
    """The prompt tells the model to search the web and read the retailer's own
    site, but neither tool is available by default in a non-interactive `-p` call
    with no TTY to approve a permission prompt - the CLI just declines in plain
    text instead, which then fails the JSON check and reports every retailer as
    NEEDS_MANUAL_CHECK regardless of whether the price actually exists. Same
    discipline app/offers.py already uses for its own subprocess call
    (--allowedTools Read)."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        raise research_runner.subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(research_runner.subprocess, "run", fake_run)
    with pytest.raises(research_runner.RunnerError):
        research_runner.research_one_retailer(
            "http://x", "claude", "Some Product", "SKU-1", "Some Retailer", None
        )
    args = captured["args"]
    assert "--allowedTools" in args
    tools = args[args.index("--allowedTools") + 1]
    assert "WebSearch" in tools.split(",")
    assert "WebFetch" in tools.split(",")
