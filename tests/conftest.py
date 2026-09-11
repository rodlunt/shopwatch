from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh migrated database per test, redirected via the environment."""
    from app.db import migrate

    path = tmp_path / "test.db"
    monkeypatch.setenv("SHOPWATCH_DB", str(path))
    monkeypatch.setenv("SHOPWATCH_ALERTS_ENABLED", "false")
    # The suite must never reach the network or sleep on the politeness delay. Adapters
    # are stubbed where behaviour is under test; this stops anything else leaking out.
    monkeypatch.setenv("SHOPWATCH_SCRAPING_ENABLED", "false")
    monkeypatch.setenv("SHOPWATCH_REQUEST_DELAY", "0")
    monkeypatch.setenv("SHOPWATCH_UNRESOLVED_FREIGHT_PENALTY", "60")
    migrate(path)
    return path


@pytest.fixture()
def conn(db):
    from app.db import connect

    connection = connect(db)
    yield connection
    connection.commit()
    connection.close()


@pytest.fixture()
def seeded(db):
    """A database with the Q930H board seeded, as the container does on first boot."""
    from app.seed import seed_all

    seed_all()
    return db


@pytest.fixture()
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
