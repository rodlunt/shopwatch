"""Domain -> retailer identity helpers for the "paste a listing URL" path (issue #94).

Pure unit tests, no network, no database: this module only ever parses a string and
looks up the adapter registry.
"""

from __future__ import annotations

from app import url_intake
from app.retailers import crowdshop


def test_bare_domain_strips_www_and_lowercases():
    assert url_intake.bare_domain("https://WWW.Crowdshop.com.au/some/page") == "crowdshop.com.au"


def test_bare_domain_without_www_is_unchanged():
    assert url_intake.bare_domain("https://centrecom.com.au/x") == "centrecom.com.au"


def test_bare_domain_rejects_a_non_http_scheme():
    assert url_intake.bare_domain("javascript:alert(1)") is None
    assert url_intake.bare_domain("ftp://example.com/file") is None
    assert url_intake.bare_domain("mailto:someone@example.com") is None


def test_bare_domain_rejects_a_bare_string_with_no_scheme():
    """A domain typed without a scheme is not a URL this app was given - the caller
    (the from-url endpoint) must not silently invent https:// on the user's behalf and
    fetch or record something they didn't actually paste."""
    assert url_intake.bare_domain("centrecom.com.au/some/page") is None


def test_bare_domain_rejects_garbage():
    assert url_intake.bare_domain("not a url at all") is None
    assert url_intake.bare_domain("") is None


def test_adapter_for_domain_matches_a_registered_adapter():
    assert url_intake.adapter_for_domain("crowdshop.com.au") is crowdshop.CrowdshopAdapter


def test_adapter_for_domain_matches_regardless_of_www():
    # The adapter's own homepage carries www.; the pasted URL's domain (already bare,
    # since bare_domain strips www. first) must still match it.
    assert url_intake.adapter_for_domain("jbhifi.com.au") is not None


def test_adapter_for_domain_returns_none_for_an_unconfigured_retailer():
    assert url_intake.adapter_for_domain("centrecom.com.au") is None


def test_display_name_for_domain_strips_the_tld_and_titlecases():
    assert url_intake.display_name_for_domain("centrecom.com.au") == "Centrecom"


def test_display_name_for_domain_splits_on_hyphens_and_dots():
    assert url_intake.display_name_for_domain("some-cool-shop.com") == "Some Cool Shop"


def test_display_name_for_domain_leaves_an_unrecognised_tld_in_place():
    # An unusual TLD this app doesn't recognise is not stripped - a worse-looking name
    # is safer than silently guessing which suffix to drop.
    assert url_intake.display_name_for_domain("example.unusualtld") == "Example Unusualtld"
