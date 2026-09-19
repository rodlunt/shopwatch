"""Database safety: migrations are forward-only and never wipe existing data."""

from __future__ import annotations

from app import store
from app.db import backup, connect, migrate, restore


def test_migrate_is_idempotent_and_preserves_data(db):
    with connect(db) as conn:
        product_id = store.create_product(conn, {"name": "Keep me", "model": "KEEP-1"})
        conn.commit()

    assert migrate(db) == [], "already applied, so nothing runs a second time"

    with connect(db) as conn:
        assert store.get_product(conn, product_id)["name"] == "Keep me"


def test_migrations_are_recorded(db):
    with connect(db) as conn:
        applied = [r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations")]
    assert "0001_initial.sql" in applied


def test_retailer_excluded_migration_applies_cleanly_and_defaults_off(db):
    """issue #112: every existing retailer must be unaffected until someone
    deliberately excludes it."""
    with connect(db) as conn:
        applied = [r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations")]
        assert "0015_retailer_excluded.sql" in applied
        retailer_id = store.ensure_retailer(conn, "Some Shop")["id"]
        conn.commit()
        row = conn.execute("SELECT excluded FROM retailers WHERE id = ?", (retailer_id,)).fetchone()
    assert row["excluded"] == 0


def test_wal_mode_is_on(db):
    with connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_backup_and_restore_round_trip(db, tmp_path):
    """Restore is an offline operation: every connection is closed first, as the README says."""
    conn = connect(db)
    store.create_product(conn, {"name": "Before", "model": "BEFORE-1"})
    conn.commit()
    conn.close()

    snapshot = backup(tmp_path / "snap.db", db)
    assert snapshot.exists()

    conn = connect(db)
    store.create_product(conn, {"name": "After", "model": "AFTER-1"})
    conn.commit()
    conn.close()

    restore(snapshot, db)

    conn = connect(db)
    models = {r["model"] for r in conn.execute("SELECT model FROM products")}
    conn.close()
    assert models == {"BEFORE-1"}, "restore returns the database to the snapshot"
    assert list(db.parent.glob("test.replaced-*.db")), (
        "the database that was replaced is kept, not discarded"
    )


def test_config_rereads_the_environment(monkeypatch):
    """Guards the dataclass-default trap: a plain default freezes at import time.

    The control is the pair: the same call must return both values as the environment
    changes underneath it.
    """
    from app.config import load_config

    monkeypatch.setenv("SHOPWATCH_UNRESOLVED_FREIGHT_PENALTY", "60")
    monkeypatch.setenv("SHOPWATCH_SCRAPING_ENABLED", "true")
    assert load_config().unresolved_freight_penalty == 60.0
    assert load_config().scraping_enabled is True

    monkeypatch.setenv("SHOPWATCH_UNRESOLVED_FREIGHT_PENALTY", "125")
    monkeypatch.setenv("SHOPWATCH_SCRAPING_ENABLED", "false")
    assert load_config().unresolved_freight_penalty == 125.0
    assert load_config().scraping_enabled is False


def test_a_junk_numeric_setting_falls_back_instead_of_crashing_the_app(monkeypatch):
    from app.config import load_config

    monkeypatch.setenv("SHOPWATCH_STALE_AFTER_DAYS", "not-a-number")
    assert load_config().stale_after_days == 7
