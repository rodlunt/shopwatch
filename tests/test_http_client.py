"""app.http_client: the scrapers' GET, with a classical TLS key exchange.

The wire behaviour (a different ClientHello) cannot be observed in a unit test, so these
check the wiring: that the restricted adapter is what actually carries the request, that a
strict server falls back to the default handshake, and that the switch turns it off.
"""
import pytest
import requests

from app import http_client


class Resp:
    status_code = 200
    text = "ok"
    headers: dict = {}


@pytest.fixture()
def spy(monkeypatch):
    seen = {"mounted": [], "session_gets": 0, "plain_gets": 0, "session_error": None}

    def fake_session_get(self, url, **kw):
        seen["session_gets"] += 1
        if seen["session_error"]:
            raise seen["session_error"]
        return Resp()

    def fake_mount(self, prefix, adapter):
        seen["mounted"].append((prefix, adapter))

    def fake_plain_get(url, **kw):
        seen["plain_gets"] += 1
        return Resp()

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests.Session, "mount", fake_mount)
    monkeypatch.setattr(requests, "get", fake_plain_get)
    monkeypatch.delenv("SHOPWATCH_TLS_CURVE", raising=False)
    return seen


def test_https_requests_ride_the_restricted_adapter(spy):
    http_client.get("https://example.com/", timeout=5, headers={"User-Agent": "x"})
    assert spy["session_gets"] == 1 and spy["plain_gets"] == 0
    prefix, adapter = spy["mounted"][-1]
    assert prefix == "https://"
    assert isinstance(adapter, http_client._CurveAdapter)
    assert adapter._curve == "X25519"


def test_an_ssl_failure_falls_back_to_the_default_handshake_once(spy):
    spy["session_error"] = requests.exceptions.SSLError("handshake refused")
    got = http_client.get("https://strict.example/")
    assert got.status_code == 200
    assert spy["session_gets"] == 1 and spy["plain_gets"] == 1


def test_other_errors_are_not_swallowed(spy):
    spy["session_error"] = requests.exceptions.ConnectTimeout("slow")
    with pytest.raises(requests.exceptions.ConnectTimeout):
        http_client.get("https://slow.example/")
    assert spy["plain_gets"] == 0, "a timeout is not a handshake problem"


def test_an_empty_setting_turns_the_restriction_off(spy, monkeypatch):
    monkeypatch.setenv("SHOPWATCH_TLS_CURVE", "")
    http_client.get("https://example.com/")
    assert spy["plain_gets"] == 1 and spy["session_gets"] == 0 and not spy["mounted"]


def test_the_curve_can_be_overridden(spy, monkeypatch):
    monkeypatch.setenv("SHOPWATCH_TLS_CURVE", "prime256v1")
    http_client.get("https://example.com/")
    assert spy["mounted"][-1][1]._curve == "prime256v1"


def test_the_adapter_builds_a_context_with_the_curve_set():
    """Real objects, no mocks: the context is created and accepts the curve name."""
    adapter = http_client._CurveAdapter("X25519")
    assert adapter.poolmanager is not None
