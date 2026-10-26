"""The Pi watch end to end: transitions, alerts, delivery, health, and the API.

Adapters are replaced by a scripted fake so each test states exactly what the retailer
"said" on each run. Where a test proves something does NOT happen, the sentence next to it
says what the control is, because an absence proves nothing until the same setup is shown
able to produce the presence.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app import alerts, db, pi_events, pi_health, price_watch, retailers, store
from app.config import load_config
from app.db import utcnow
from app.retailers import FetchError, Observation


class Script:
    """Stands in for a retailer adapter: each check() pops the next scripted reading."""

    slug = "core_electronics"
    name = "Core Electronics"
    wants_product_name = False

    def __init__(self):
        self.queue: list = []

    def check(self, url, model=None):
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def reading(price, text="In stock", state="in_stock", limit=None):
    return Observation(
        advertised_price=price, stock_status=text, availability=state,
        availability_text=text, unit_limit=limit, condition="NEW",
    )


@pytest.fixture()
def pi(db, monkeypatch):
    """A Pi product with one Core Electronics listing, and a scripted adapter."""
    script = Script()
    monkeypatch.setattr(retailers, "get_adapter", lambda slug: script if slug else None)
    with db_conn(db) as conn:
        retailer = store.ensure_retailer(conn, "Core Electronics", adapter="core_electronics")
        product_id = store.create_product(
            conn, {"name": "Raspberry Pi 4 Model B 2GB", "model": "SC0193",
                   "category": "Barkmarker", "trigger_price": 100.0})
        listing_id = store.create_listing(
            conn, {"product_id": product_id, "retailer_id": retailer["id"],
                   "url": "https://example.test/pi4"})
        pi_events.ensure_rules(conn)
        conn.commit()
    return script, product_id, listing_id


def db_conn(path):
    return db.session(path)


def go(db_path, **kw):
    kw.setdefault("category", "Barkmarker")
    return price_watch.run(trigger="test", **kw)


def events(db_path, status=None):
    with db_conn(db_path) as conn:
        q = "SELECT kind, status, attempts, last_error FROM alert_events"
        q += " WHERE status = ?" if status else ""
        return [dict(r) for r in conn.execute(q, (status,) if status else ())]


def listing(db_path, listing_id):
    with db_conn(db_path) as conn:
        return dict(conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone())


# ------------------------------------------------------------------ baselines


def test_the_first_automatic_run_is_a_baseline_and_says_nothing(pi, db):
    script, _, lid = pi
    script.queue = [reading(40.0, "Out of stock", "out_of_stock")]
    summary = go(db)
    assert summary["ok"] == 1 and summary["errors"] == 0
    assert events(db) == [], "no previous adapter reading means nothing to compare against"
    row = listing(db, lid)
    assert (row["advertised_price"], row["availability"]) == (40.0, "out_of_stock")


# ----------------------------------------------------------------- price drop


@pytest.mark.parametrize(
    "old, new, fires",
    [
        (100.0, 95.0, True),   # exactly 5%, over $3
        (100.0, 95.5, False),  # 4.5%: under 5%
        (20.0, 17.0, True),    # $3 flat, 15%
        (20.0, 17.5, False),   # $2.50: under $3 even though over 5%
        (100.0, 101.0, False), # a rise is not a drop
        (200.0, 189.0, True),  # $11 on $200 = 5.5%
        (200.0, 191.0, False), # $9 on $200 = 4.5%, over $3 but under 5%
    ],
)
def test_price_drop_threshold_is_the_larger_of_3_dollars_and_5_percent(pi, db, old, new, fires):
    script, _, _ = pi
    script.queue = [reading(old), reading(new)]
    go(db)
    go(db)
    kinds = [e["kind"] for e in events(db)]
    assert ("PRICE_DROP" in kinds) is fires


def test_price_drop_alert_carries_old_new_stock_limit_and_link(pi, db, capsys):
    script, _, lid = pi
    script.queue = [reading(100.0, "In stock (limit 2 per customer)", "limited", 2),
                    reading(90.0, "In stock (limit 2 per customer)", "limited", 2)]
    go(db)
    capsys.readouterr()
    summary = go(db)
    out = capsys.readouterr().out
    assert "PRICE DROP: Raspberry Pi 4 Model B 2GB" in out
    assert "$90.00 (was $100.00, down $10.00)" in out
    assert "In stock (limit 2 per customer)" in out
    assert "https://example.test/pi4" in out
    # The same fall is also the cheapest in-stock price ever seen, so two events, one each.
    assert summary["events"]["sent"] == 2
    assert sorted(e["kind"] for e in events(db)) == ["NEW_LOWEST", "PRICE_DROP"]
    row = listing(db, lid)
    assert (row["previous_price"], row["price_changed_at"] is not None) == (100.0, True)


def test_a_hand_typed_price_is_not_the_baseline(pi, db):
    """Control for the baseline rule: the same drop does fire once an adapter has read it."""
    script, _, lid = pi
    with db_conn(db) as conn:
        conn.execute("UPDATE listings SET advertised_price = 200, stock_status = 'In stock'"
                     " WHERE id = ?", (lid,))
    script.queue = [reading(100.0)]
    go(db)
    assert events(db) == [], "200 was typed in, never observed, so 100 is not a drop"
    script.queue = [reading(80.0)]
    go(db)
    assert "PRICE_DROP" in [e["kind"] for e in events(db)]


# -------------------------------------------------------------- back in stock


@pytest.mark.parametrize(
    "before, after, fires",
    [
        (("Out of stock", "out_of_stock"), ("In stock", "in_stock"), True),
        (("Backorder", "backorder"), ("In stock", "in_stock"), True),
        (("Expect dispatch 2 to 6 Nov", "dispatch_later"),
         ("In stock (limit 1 per customer)", "limited"), True),
        (("In stock", "in_stock"), ("Out of stock", "out_of_stock"), False),
        (("In stock", "in_stock"), ("In stock", "in_stock"), False),
        (("Out of stock", "out_of_stock"), ("Out of stock", "out_of_stock"), False),
        (("Out of stock", "out_of_stock"), ("Backorder", "backorder"), False),
    ],
)
def test_back_in_stock_only_on_a_waiting_to_buyable_change(pi, db, before, after, fires):
    script, _, _ = pi
    script.queue = [reading(50.0, *before), reading(50.0, *after)]
    go(db)
    go(db)
    assert ("BACK_IN_STOCK" in [e["kind"] for e in events(db)]) is fires


def test_unknown_availability_never_overwrites_and_never_alerts(pi, db):
    script, _, lid = pi
    script.queue = [reading(50.0, "Out of stock", "out_of_stock"),
                    Observation(advertised_price=50.0, availability="unknown"),
                    reading(50.0, "In stock", "in_stock")]
    go(db)
    go(db)
    assert listing(db, lid)["availability"] == "out_of_stock", "unknown keeps the last good value"
    go(db)
    assert "BACK_IN_STOCK" in [e["kind"] for e in events(db)]


# ------------------------------------------------------------------ new lowest


def test_new_lowest_needs_a_baseline_then_a_cheaper_buyable_price(pi, db):
    script, _, _ = pi
    script.queue = [reading(100.0), reading(100.0), reading(97.0), reading(99.0), reading(90.0)]
    go(db)
    go(db)
    assert "NEW_LOWEST" not in [e["kind"] for e in events(db)], "first sight is a baseline"
    go(db)
    assert [e["kind"] for e in events(db)].count("NEW_LOWEST") == 1
    go(db)
    go(db)
    assert [e["kind"] for e in events(db)].count("NEW_LOWEST") == 2, "a dearer day does not raise the bar"


def test_an_out_of_stock_price_is_never_a_new_low(pi, db):
    script, _, _ = pi
    script.queue = [reading(100.0), reading(60.0, "Out of stock", "out_of_stock")]
    go(db)
    go(db)
    assert "NEW_LOWEST" not in [e["kind"] for e in events(db)]


# ------------------------------------------------------------------ dedupe etc.


def test_the_same_change_can_never_be_queued_twice(pi, db):
    _, pid, lid = pi
    cfg = load_config()
    with db_conn(db) as conn:
        first = pi_events._queue(conn, cfg, "PRICE_DROP", pid, lid, "k1", {"x": 1})
        second = pi_events._queue(conn, cfg, "PRICE_DROP", pid, lid, "k1", {"x": 1})
    assert (first, second) == ("queued", "duplicate")
    assert len(events(db)) == 1


def test_a_second_event_inside_the_cooldown_is_recorded_as_suppressed(pi, db):
    _, pid, lid = pi
    cfg = load_config()
    with db_conn(db) as conn:
        a = pi_events._queue(conn, cfg, "BACK_IN_STOCK", pid, lid, "a", {})
        b = pi_events._queue(conn, cfg, "BACK_IN_STOCK", pid, lid, "b", {})
        c = pi_events._queue(conn, cfg, "PRICE_DROP", pid, lid, "c", {})
    assert (a, b, c) == ("queued", "suppressed", "queued")
    assert sorted(e["status"] for e in events(db)) == ["pending", "pending", "suppressed"]


def test_rate_limit_defers_the_excess_to_the_next_run(pi, db, monkeypatch):
    _, pid, lid = pi
    monkeypatch.setenv("SHOPWATCH_PI_MAX_ALERTS_PER_RUN", "2")
    cfg = load_config()
    with db_conn(db) as conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO alert_events (kind, product_id, listing_id, dedupe_key, payload,"
                " created_at) VALUES ('PRICE_DROP', ?, ?, ?, ?, ?)",
                (pid, lid, f"k{i}", '{"product":"p","retailer":"r","new_price":1}', utcnow()),
            )
        out = pi_events.deliver_pending(conn, cfg)
    assert (out["sent"], out["deferred"]) == (2, 3)
    assert len(events(db, "pending")) == 3




# -------------------------------------------------------- delivery failure


class FailingSend:
    def __init__(self, fail=True):
        self.fail = fail
        self.calls = 0

    def __call__(self, alert, config=None):
        self.calls += 1
        report = alerts.DeliveryReport()
        if self.fail:
            report.failures.append("ntfy delivery failed: HTTP 403")
        else:
            report.sent.append("ntfy")
        return report


def test_a_failed_delivery_is_loud_retried_and_never_marked_sent(pi, db, monkeypatch):
    script, _, _ = pi
    send = FailingSend(fail=True)
    monkeypatch.setattr(alerts, "send", send)
    script.queue = [reading(100.0), reading(80.0), reading(80.0)]
    go(db)
    summary = go(db)
    assert set(summary["delivery_failures"]) == {"ntfy delivery failed: HTTP 403"}
    assert summary["events"]["failed"] == 2, "price drop and new lowest, both held for retry"
    pending = events(db, "pending")
    assert len(pending) >= 1 and pending[0]["attempts"] == 1
    assert pending[0]["last_error"] == "ntfy delivery failed: HTTP 403"
    assert price_watch.main(["--category", "Barkmarker"]) in (0, 1)

    send.fail = False  # the notifier recovers
    summary = go(db)
    assert summary["delivery_failures"] == []
    assert summary["events"]["sent"] >= 1
    assert events(db, "pending") == [], "the retry delivered what the first attempt could not"


def test_an_event_that_can_never_be_delivered_expires_loudly(pi, db, monkeypatch):
    _, pid, lid = pi
    monkeypatch.setattr(alerts, "send", FailingSend(fail=True))
    old = (datetime.now(UTC) - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db_conn(db) as conn:
        conn.execute(
            "INSERT INTO alert_events (kind, product_id, listing_id, dedupe_key, payload,"
            " created_at) VALUES ('PRICE_DROP', ?, ?, 'old', ?, ?)",
            (pid, lid, '{"product":"p","retailer":"r","new_price":1}', old),
        )
        out = pi_events.deliver_pending(conn, load_config())
    assert out["expired"] == 1 and "expired undelivered" in out["failures"][0]
    assert [e["status"] for e in events(db)] == ["expired"]


def test_a_failed_target_alert_stays_armed_so_it_is_retried(pi, db, monkeypatch):
    script, _, _ = pi
    send = FailingSend(fail=True)
    monkeypatch.setattr(alerts, "send", send)
    script.queue = [reading(90.0), reading(90.0)]
    go(db)
    go(db)
    with db_conn(db) as conn:
        rule = conn.execute("SELECT last_fired_price FROM alert_rules WHERE kind='TRIGGER'"
                            ).fetchone()
    assert rule["last_fired_price"] is None, "never marked fired on a failed delivery"
    assert send.calls >= 2, "and it was offered again on the next run"


# ------------------------------------------------------------ target alert


def test_target_alert_follows_trigger_price_ignores_require_complete_and_needs_stock(
    pi, db, capsys
):
    script, pid, _ = pi
    with db_conn(db) as conn:
        # The stock default would suppress a Pi listing for lacking included components.
        conn.execute("UPDATE alert_rules SET require_complete = 1"
                     " WHERE kind = 'TRIGGER'")
    script.queue = [reading(90.0, "Out of stock", "out_of_stock"), reading(90.0)]
    summary = go(db)
    assert [a for a in summary["alerts"] if a.get("rule")] == [], "out of stock: no target alert"
    capsys.readouterr()
    summary = go(db)
    out = capsys.readouterr().out
    assert "AT OR BELOW TARGET: Raspberry Pi 4 Model B 2GB" in out
    assert any(a.get("rule") == "At or below trigger price" for a in summary["alerts"])
    with db_conn(db) as conn:
        conn.execute("UPDATE products SET trigger_price = 50 WHERE id = ?", (pid,))
        assert alerts.evaluate_all(conn) == [], "moving trigger_price moves the alert"


def test_other_categories_still_honour_require_complete(db):
    """Control: the Pi opt-out must not leak to the rest of the board."""
    with db_conn(db) as conn:
        r = store.ensure_retailer(conn, "Some Shop")
        pid = store.create_product(conn, {"name": "Thing", "model": "T1", "category": "general",
                                          "trigger_price": 100.0})
        store.create_listing(conn, {"product_id": pid, "retailer_id": r["id"],
                                    "advertised_price": 50.0, "freight": 0.0})
        conn.execute(
            "INSERT INTO alert_rules (product_id, name, kind, max_delivered, require_complete)"
            " VALUES (?, 'x', 'TRIGGER', 0, 1)", (pid,))
        assert alerts.evaluate_all(conn) == []
        conn.execute("UPDATE alert_rules SET require_complete = 0")
        assert len(alerts.evaluate_all(conn)) == 1


# ------------------------------------------------- failure handling + health


def test_a_failed_check_keeps_the_last_good_value_and_is_counted(pi, db):
    script, _, lid = pi
    script.queue = [reading(70.0), FetchError("HTTP 503"), RuntimeError("parser exploded")]
    go(db)
    for _ in range(2):
        summary = go(db)
        assert summary["errors"] == 1 and summary["ok"] == 0
    assert listing(db, lid)["advertised_price"] == 70.0
    assert summary["status"] == "failed"
    with db_conn(db) as conn:
        h = conn.execute("SELECT * FROM adapter_health").fetchone()
    assert (h["consecutive_failures"], h["total_failures"]) == (2, 2)


def test_three_failed_runs_in_a_row_make_the_adapter_unhealthy_and_a_success_resets_it(pi, db):
    script, _, _ = pi
    script.queue = [reading(70.0)] + [FetchError("HTTP 500")] * 3 + [reading(70.0)]
    go(db)
    with db_conn(db) as conn:
        assert pi_health.health(conn)["status"] == "ok"
    for _ in range(2):
        go(db)
    with db_conn(db) as conn:
        assert pi_health.health(conn)["status"] == "ok", "two failures is below the limit"
    go(db)
    with db_conn(db) as conn:
        h = pi_health.health(conn)
    assert h["status"] == "unhealthy"
    assert "core_electronics has failed 3 runs in a row" in h["reasons"][0]
    assert "1.5 days" in h["reasons"][0]
    go(db)
    with db_conn(db) as conn:
        assert pi_health.health(conn)["status"] == "ok"


def test_a_locked_price_is_reported_as_unresolved_not_as_a_success(pi, db):
    script, _, lid = pi
    with db_conn(db) as conn:
        from app import provenance
        provenance.set_field(conn, lid, "advertised_price", 55.0, state=provenance.MANUAL)
    script.queue = [reading(40.0)]
    summary = go(db)
    assert (summary["ok"], summary["unresolved"]) == (0, 1)
    assert listing(db, lid)["advertised_price"] == 55.0


def test_stale_alarm_fires_after_36_hours_and_not_before(pi, db):
    cfg = load_config()
    assert (cfg.pi_stale_hours, cfg.pi_streak_limit) == (36.0, 3)
    _, pid, lid = pi

    def success_at(hours_ago, source="core_electronics"):
        ts = (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with db_conn(db) as conn:
            conn.execute("DELETE FROM price_history")
            conn.execute(
                "INSERT INTO price_history (product_id, listing_id, observed_at,"
                " advertised_price, source) VALUES (?, ?, ?, 50, ?)", (pid, lid, ts, source))

    for hours, stale in [(35, False), (37, True)]:
        success_at(hours)
        with db_conn(db) as conn:
            h = pi_health.health(conn)
        assert (h["status"] == "unhealthy") is stale, hours
        if stale:
            assert "no successful price check" in h["reasons"][0]
            assert "36" in h["reasons"][0]
    # Control: hand-typed rows (source 'ui') must not count as the watch working.
    success_at(1, source="ui")
    with db_conn(db) as conn:
        conn.execute("UPDATE schema_migrations SET applied_at = '2020-01-01T00:00:00Z'"
                     " WHERE filename = '0016_pi_watch.sql'")
        h = pi_health.health(conn)
    assert h["status"] == "unhealthy" and h["last_successful_check"] is None


def test_a_fresh_install_is_not_stale_before_its_first_run(db):
    with db_conn(db) as conn:
        assert pi_health.health(conn)["status"] == "ok"


def test_health_cli_exits_nonzero_with_a_reason_when_stale(pi, db, capsys):
    with db_conn(db) as conn:
        conn.execute("UPDATE schema_migrations SET applied_at = '2020-01-01T00:00:00Z'"
                     " WHERE filename = '0016_pi_watch.sql'")
    assert pi_health.main([]) == 1
    assert "[PI-WATCH-FAULT] no successful price check" in capsys.readouterr().err


def test_only_the_pi_category_is_polled(pi, db):
    script, _, _ = pi
    with db_conn(db) as conn:
        r = store.ensure_retailer(conn, "Other", adapter="core_electronics")
        pid = store.create_product(conn, {"name": "TV", "model": "TV1", "category": "tv"})
        store.create_listing(conn, {"product_id": pid, "retailer_id": r["id"],
                                    "url": "https://example.test/tv"})
    script.queue = [reading(50.0), reading(999.0)]
    summary = go(db)
    assert summary["checked"] == 1
    assert len(script.queue) == 1, "the TV was never fetched"


# ---------------------------------------------------------- migration + API


def test_migration_releases_hand_typed_locks_and_creates_rules(tmp_path, monkeypatch):
    src = db.MIGRATIONS_DIR
    staged = tmp_path / "migrations"
    staged.mkdir()
    for f in sorted(src.glob("*.sql")):
        if f.name < "0016":
            (staged / f.name).write_text(f.read_text())
    monkeypatch.setattr(db, "MIGRATIONS_DIR", staged)
    path = tmp_path / "old.db"
    db.migrate(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        INSERT INTO retailers (name, slug) VALUES ('Core Electronics', 'core_electronics'),
                                                  ('Amazon AU', 'amazon_au');
        INSERT INTO products (name, model, category, trigger_price)
            VALUES ('Pi', 'SC1', 'Barkmarker', 44), ('TV', 'TV1', 'tv', NULL);
        INSERT INTO listings (product_id, retailer_id, url, advertised_price)
            VALUES (1, 1, 'u1', 46), (1, 2, 'u2', 148), (2, 1, 'u3', 900);
        INSERT INTO field_provenance (listing_id, field, state, source, manual_locked)
            VALUES (1, 'advertised_price', 'MANUAL', 'ui', 1),
                   (2, 'advertised_price', 'MANUAL', 'ui', 1),
                   (3, 'advertised_price', 'MANUAL', 'ui', 1);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", src)
    assert db.migrate(path) == [f.name for f in sorted(src.glob("*.sql")) if f.name >= "0016"]
    conn = sqlite3.connect(path)
    locks = dict(conn.execute("SELECT listing_id, manual_locked FROM field_provenance"))
    assert locks == {1: 0, 2: 1, 3: 1}, "only the Pi listing that has an adapter is released"
    kinds = sorted(r[0] for r in conn.execute("SELECT kind FROM alert_rules WHERE product_id = 1"))
    assert kinds == ["BACK_IN_STOCK", "NEW_LOWEST", "PRICE_DROP", "TRIGGER"]
    assert conn.execute("SELECT count(*) FROM alert_rules WHERE product_id = 2").fetchone()[0] == 0
    adapter = conn.execute("SELECT adapter FROM retailers WHERE slug='core_electronics'").fetchone()
    assert adapter[0] == "core_electronics"
    assert conn.execute("SELECT adapter FROM retailers WHERE slug='amazon_au'").fetchone()[0] is None


def test_api_surfaces_the_new_listing_fields_and_the_pi_summary(pi, db):
    from fastapi.testclient import TestClient

    from app.main import app

    script, pid, lid = pi
    script.queue = [reading(100.0, "In stock (limit 2 per customer)", "limited", 2),
                    reading(90.0, "In stock (limit 2 per customer)", "limited", 2)]
    go(db)
    go(db)
    with TestClient(app) as client:
        listings = [p for p in client.get("/api/products").json() if p["id"] == pid][0]["listings"]
        row = listings[0]
        assert row["availability"] == "limited" and row["unit_limit"] == 2
        assert row["availability_text"] == "In stock (limit 2 per customer)"
        assert row["previous_price"] == 100.0 and row["price_changed_at"]
        assert row["last_checked_at"]

        body = client.get("/api/pi-watch").json()
        assert body["category"] == "Barkmarker"
        product = [p for p in body["products"] if p["id"] == pid][0]
        assert product["cheapest_in_stock"]["price"] == 90.0
        assert product["cheapest_in_stock"]["retailer"] == "Core Electronics"
        assert product["listings"][0]["automatic"] is True
        assert body["health"]["status"] == "ok"
        assert body["health"]["adapters"][0]["adapter"] == "core_electronics"

        assert client.get("/healthz").json()["pi_watch"]["status"] == "ok"
        assert client.get("/api/meta").json()["pi_watch"]["stale_after_hours"] == 36.0

        dry = client.post("/api/alerts/evaluate", json={}).json()
        assert set(dry) == {"alerts", "pending_events", "would_queue_new_lowest"}


def test_pi_watch_marks_a_manual_retailer_as_not_automatic(pi, db):
    from fastapi.testclient import TestClient

    from app.main import app

    _, pid, _ = pi
    with db_conn(db) as conn:
        r = store.ensure_retailer(conn, "Amazon AU")
        store.create_listing(conn, {"product_id": pid, "retailer_id": r["id"],
                                    "url": "https://example.test/amz", "advertised_price": 148.0,
                                    "stock_status": "In stock (only 1 left)"})
    with TestClient(app) as client:
        body = client.get("/api/pi-watch").json()
    amazon = [x for x in body["products"][0]["listings"] if x["retailer"] == "Amazon AU"][0]
    assert amazon["automatic"] is False and amazon["availability"] == "limited"
    assert amazon["unit_limit"] == 1
