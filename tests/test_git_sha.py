"""Footer build-info resolution: a real opti deploy vs a local dev checkout vs neither.

"local build" (no SHA at all) must only mean literally no git info was available - not
just "GIT_SHA wasn't set", which is true of every local dev run and would otherwise
make the honest "here's what commit you're looking at" label never appear locally.
"""

from __future__ import annotations

import subprocess

from app.main import _resolve_git_sha


def test_env_var_set_means_a_real_deploy(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234567890")
    sha, is_deploy = _resolve_git_sha()
    assert sha == "abc1234567890"
    assert is_deploy is True


def test_no_env_var_falls_back_to_the_local_git_checkout(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    sha, is_deploy = _resolve_git_sha()
    # This test suite runs inside a real git checkout, so a real short SHA comes back.
    assert sha is not None
    assert len(sha) >= 7
    assert is_deploy is False


def test_no_env_var_and_no_git_available_falls_back_to_none(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sha, is_deploy = _resolve_git_sha()
    assert sha is None
    assert is_deploy is False


def test_git_present_but_not_a_repo_falls_back_to_none(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)

    class FakeResult:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())
    sha, is_deploy = _resolve_git_sha()
    assert sha is None
    assert is_deploy is False
