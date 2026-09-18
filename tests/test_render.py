"""The render container must never outlive the render.

WHY THIS EXISTS. `render_html` bounds Chrome with `subprocess.run(timeout=...)`.
That kills the `docker run` CLIENT, which is only a process talking to the daemon
over a socket. The container carries on, and `--rm` never fires because `--rm`
runs when the container EXITS.

So a marketing email whose hero images hang left a headless Chrome running with
network access, permanently, with its own bind-mount source already deleted by
the cleanup path. Seen on opti 2026-09-18: the daily mailwatch run reported
"errors 0" and left a container up for ten minutes and counting, still holding
the outbound connection that tripped egress-watch. The alert found it. Nothing
in shopwatch did, and there were no tests for this module at all.

These tests drive the real `render_html` with `subprocess.run` replaced, so they
assert what the function actually does rather than what it looks like it does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import render


class FakeRun:
    """Stands in for subprocess.run, recording every call and scripting the first."""

    def __init__(self, on_render):
        self.calls: list[list[str]] = []
        self.on_render = on_render

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if cmd[:2] == ["docker", "run"]:
            return self.on_render(cmd, kwargs)
        # Anything else (the cleanup) succeeds quietly.
        return subprocess.CompletedProcess(cmd, 0, "", "")

    @property
    def run_cmd(self) -> list[str]:
        return next(c for c in self.calls if c[:2] == ["docker", "run"])

    @property
    def removals(self) -> list[list[str]]:
        return [c for c in self.calls if c[:3] == ["docker", "rm", "-f"]]


def _install(monkeypatch, on_render) -> FakeRun:
    fake = FakeRun(on_render)
    monkeypatch.setattr(render.subprocess, "run", fake)
    monkeypatch.setattr(render, "available", lambda: True)
    return fake


def _container_name(cmd: list[str]) -> str:
    return cmd[cmd.index("--name") + 1]



def test_container_is_named(monkeypatch):
    fake = _install(monkeypatch, lambda cmd, kw: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(cmd, 120)))
    with pytest.raises(render.RenderError):
        render.render_html("<p>hi</p>", timeout=120)
    assert "--name" in fake.run_cmd, "docker run was not given an explicit --name"
    assert _container_name(fake.run_cmd).startswith("shopwatch-render-")


def test_timeout_force_removes_the_container(monkeypatch):
    """The bug as shipped: the timeout killed the client and left the container."""
    fake = _install(monkeypatch, lambda cmd, kw: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(cmd, 120)))

    with pytest.raises(render.RenderError, match="timed out"):
        render.render_html("<p>hi</p>", timeout=120)

    name = _container_name(fake.run_cmd)
    assert fake.removals, "the container was never removed after the timeout"
    assert fake.removals[0] == ["docker", "rm", "-f", name], (
        f"removed the wrong container: {fake.removals[0]}, expected to remove {name}"
    )


def test_unexpected_exception_also_removes_the_container(monkeypatch):
    """A timeout is not the only way out of that call."""
    fake = _install(monkeypatch, lambda cmd, kw: (_ for _ in ()).throw(
        OSError("docker daemon went away")))

    with pytest.raises(render.RenderError):
        render.render_html("<p>hi</p>", timeout=120)

    assert fake.removals, "the container was never removed after an unexpected error"
    assert fake.removals[0][-1] == _container_name(fake.run_cmd)


def test_each_render_gets_its_own_name(monkeypatch):
    """Two concurrent renders must not fight over one container name, and a stuck
    container must not block the next run by holding the name."""
    names = set()
    for _ in range(3):
        fake = _install(monkeypatch, lambda cmd, kw: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd, 1)))
        with pytest.raises(render.RenderError):
            render.render_html("<p>hi</p>", timeout=1)
        names.add(_container_name(fake.run_cmd))
    assert len(names) == 3, f"names were reused across renders: {names}"


def test_timeout_removes_the_work_directory(monkeypatch):
    """The tempdir cleanup was already right, and must stay right: it is what made
    the orphan so confusing, a live container bind-mounted to a deleted path."""
    fake = _install(monkeypatch, lambda cmd, kw: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(cmd, 1)))
    with pytest.raises(render.RenderError):
        render.render_html("<p>hi</p>", timeout=1)
    mount = next(c[c.index("-v") + 1] for c in [fake.run_cmd])
    workdir = Path(mount.split(":")[0])
    assert not workdir.exists(), f"{workdir} was left behind"


def test_happy_path_returns_the_screenshot(monkeypatch):
    """CONTROL. Every test above asserts that a FAILING render cleans up. If the
    function could never succeed, they would all pass against a render_html that
    does nothing at all."""
    def succeed(cmd, kw):
        workdir = Path(cmd[cmd.index("-v") + 1].split(":")[0])
        (workdir / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    fake = _install(monkeypatch, succeed)
    shot = render.render_html("<p>hi</p>", timeout=120)
    try:
        assert shot.exists() and shot.stat().st_size > 0
        assert "--name" in fake.run_cmd
    finally:
        render.cleanup(shot)
    assert not shot.parent.exists()


def test_missing_screenshot_is_an_error_not_a_pass(monkeypatch):
    """CONTROL. A render that produces no file must raise rather than hand back a
    path to nothing: the caller keeps whatever the text pass produced, and a
    silent empty screenshot would be read as artwork that said nothing."""
    _install(monkeypatch, lambda cmd, kw: subprocess.CompletedProcess(cmd, 0, "", "boom"))
    with pytest.raises(render.RenderError, match="no screenshot"):
        render.render_html("<p>hi</p>", timeout=120)


# --- The summary has to SAY a render failed ---------------------------------
#
# render_errors was collected and never printed, so a timed-out render looked
# exactly like one where the artwork did not help. The run that orphaned a
# container on opti printed "errors 0".

from app.mailwatch import render_failure_lines  # noqa: E402


def test_failed_renders_are_reported():
    lines = render_failure_lines({"render_errors": ["chrome timed out after 120s"]})
    assert lines, "a failed render produced no output at all"
    assert "RENDER FAILED" in lines[0]
    assert "timed out" in lines[0]


def test_clean_run_says_nothing():
    """CONTROL. If this printed a line for a run with no failures, the check above
    would pass on a function that just always shouts."""
    assert render_failure_lines({"render_errors": []}) == []
    assert render_failure_lines({}) == []


def test_many_failures_are_summarised_not_dumped():
    lines = render_failure_lines({"render_errors": [f"err {i}" for i in range(9)]})
    assert len(lines) == 4, f"expected 3 lines plus a tail, got {len(lines)}"
    assert "6 more render failure(s)" in lines[-1]


# --- A failed render has to reach a human ----------------------------------
#
# Renders fail silently by nature: the text pass still answers, the offer is
# still recorded, the run still exits 0. Before this, the only trace was a line
# in a journal nobody reads, which is how a timeout that orphaned a container on
# opti went unnoticed until egress-watch shouted.

import urllib.error  # noqa: E402

from app import mailwatch  # noqa: E402


@pytest.fixture
def token(tmp_path):
    f = tmp_path / "ntfy_token"
    f.write_text("tok-abc123\n")
    return f


class FakeUrlopen:
    def __init__(self, code=200, raises=None):
        self.code, self.raises, self.requests = code, raises, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.raises:
            raise self.raises
        code = self.code

        class R:
            def getcode(self): return code
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()


def test_render_failure_is_published(monkeypatch, token):
    fake = FakeUrlopen()
    monkeypatch.setattr(mailwatch.urllib.request, "urlopen", fake)
    problem = mailwatch.notify_render_failures(
        {"render_errors": ["chrome timed out after 120s"], "rendered": 2},
        url="https://ntfy.example/server-alerts", token_file=str(token),
    )
    assert problem is None, f"reported a problem on a good publish: {problem}"
    assert len(fake.requests) == 1, "nothing was published"
    req = fake.requests[0]
    assert req.headers["Authorization"] == "Bearer tok-abc123"
    assert "shopwatch" in req.headers["Title"].lower()
    body = req.data.decode()
    assert "timed out" in body, "the alert does not say what went wrong"
    assert "alpine-chrome" in body, "the alert does not say how to check for an orphan"


def test_clean_run_publishes_nothing(monkeypatch, token):
    """CONTROL. An alarm that fires on every run teaches you to ignore it, and
    would make the test above pass against a function that always publishes."""
    fake = FakeUrlopen()
    monkeypatch.setattr(mailwatch.urllib.request, "urlopen", fake)
    assert mailwatch.notify_render_failures(
        {"render_errors": [], "rendered": 2},
        url="https://ntfy.example/server-alerts", token_file=str(token)) is None
    assert fake.requests == [], "published an alert for a run with no failures"


def test_unconfigured_publishes_nothing(monkeypatch, token):
    """Interactive and test runs must never publish."""
    fake = FakeUrlopen()
    monkeypatch.setattr(mailwatch.urllib.request, "urlopen", fake)
    assert mailwatch.notify_render_failures(
        {"render_errors": ["boom"], "rendered": 1}, url="", token_file=str(token)) is None
    assert fake.requests == []


def test_missing_token_is_reported_not_swallowed(monkeypatch, tmp_path):
    """Unauthenticated publish is rejected 403, so a missing token means the alert
    never arrives. That must not read as 'alerted'."""
    fake = FakeUrlopen()
    monkeypatch.setattr(mailwatch.urllib.request, "urlopen", fake)
    problem = mailwatch.notify_render_failures(
        {"render_errors": ["boom"], "rendered": 1},
        url="https://ntfy.example/server-alerts",
        token_file=str(tmp_path / "does-not-exist"),
    )
    assert problem and "token" in problem, f"a missing token was not reported: {problem!r}"
    assert fake.requests == [], "tried to publish with no token"


def test_transport_failure_is_reported(monkeypatch, token):
    monkeypatch.setattr(mailwatch.urllib.request, "urlopen",
                        FakeUrlopen(raises=urllib.error.URLError("no route to host")))
    problem = mailwatch.notify_render_failures(
        {"render_errors": ["boom"], "rendered": 1},
        url="https://ntfy.example/server-alerts", token_file=str(token))
    assert problem and "failed" in problem, f"a dead notifier reported success: {problem!r}"


def test_non_200_is_not_treated_as_delivered(monkeypatch, token):
    """A 200 means ntfy ACCEPTED it, not that a phone showed it. Anything else
    means it was not even accepted, and must not read as success."""
    monkeypatch.setattr(mailwatch.urllib.request, "urlopen", FakeUrlopen(code=403))
    problem = mailwatch.notify_render_failures(
        {"render_errors": ["boom"], "rendered": 1},
        url="https://ntfy.example/server-alerts", token_file=str(token))
    assert problem and "403" in problem, f"HTTP 403 read as delivered: {problem!r}"
