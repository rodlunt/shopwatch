"""Retailers checked by a person: skipped by the scraper, watched by a staleness alarm.

A manual retailer must never mean an unwatched one, so most tests here pair a case with its
control: the same setup without the manual flag must behave the old way, otherwise "the
scraper did nothing" would pass for the wrong reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import db as dbmod
from app import pi_events, pi_health, price_watch, provenance, retailers, store
from app.config import load_config
from app.retailers import Observation


def ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Script:
    slug = "zaitronics"
    name = "Zaitronics"
    wants_product_name = False
    firecrawl_state = "untried"
    firecrawl_outcome = None

    def __init__(self):
        self.queue: list = []
        self.calls = 0

    def check(self, url, model=None):
        self.calls += 1
        return self.queue.pop(0)


def reading(price):
    return Observation(advertised_price=price, stock_status="In stock", availability="in_stock",
                       availability_text="In stock", condition="NEW")


@pytest.fixture()
def shop(db, monkeypatch):
    """A Pi product listed at Zaitronics; returns helpers and ids."""
    script = Script()
    monkeypatch.setattr(retailers, "get_adapter", lambda slug: script if slug else None)
    with dbmod.session(db) as conn:
        retailer = store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")
        pid = store.create_product(
            conn, {"name": "Raspberry Pi 4 Model B 2GB", "model": "SC0193",
                   "category": "Barkmarker", "trigger_price": 100.0})
        lid = store.create_listing(
            conn, {"product_id": pid, "retailer_id": retailer["id"], "url": "https://z.test/pi4"})
        pi_events.ensure_rules(conn)
    return script, retailer["id"], pid, lid


def set_manual(db, retailer_id, on=True, since=None):
    with dbmod.session(db) as conn:
        store.set_retailer_manual(conn, retailer_id, on, "Cloudflare 429")
        if on and since:
            conn.execute("UPDATE retailers SET manual_since = ? WHERE id = ?", (since, retailer_id))


def checked_at(db, lid, when):
    with dbmod.session(db) as conn:
        conn.execute("UPDATE listings SET last_checked_at = ? WHERE id = ?", (when, lid))


# ------------------------------------------------------------------- the migration


def test_migration_marks_the_two_blocked_retailers_and_no_others(db):
    sql = (Path(__file__).parents[1] / "app/migrations/0017_manual_retailers.sql").read_text()
    with dbmod.session(db) as conn:
        for name, adapter in (("Small Devices", "small_devices"), ("Zaitronics", "zaitronics"),
                              ("Core Electronics", "core_electronics")):
            store.ensure_retailer(conn, name, adapter=adapter)
        conn.executescript(sql[sql.index("UPDATE retailers"):])
        marked = {r["adapter"] for r in conn.execute(
            "SELECT adapter FROM retailers WHERE manual_since IS NOT NULL")}
    assert marked == {"small_devices", "zaitronics"}


def test_a_restart_does_not_undo_it(db):
    """The reason this is its own flag: the startup seed re-adds a missing adapter."""
    with dbmod.session(db) as conn:
        r = store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")
        store.set_retailer_manual(conn, r["id"], True, "x")
        store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")  # what seed does
        row = conn.execute("SELECT adapter, manual_since FROM retailers WHERE id = ?",
                           (r["id"],)).fetchone()
    assert row["adapter"] == "zaitronics" and row["manual_since"] is not None


def test_marking_manual_twice_keeps_the_original_clock(db):
    with dbmod.session(db) as conn:
        r = store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")
        store.set_retailer_manual(conn, r["id"], True, "first")
        conn.execute("UPDATE retailers SET manual_since = ? WHERE id = ?", (ago(100), r["id"]))
        again = store.set_retailer_manual(conn, r["id"], True, "second")
    assert again["manual_since"] == ago(100) and again["manual_reason"] == "first"


# ---------------------------------------------------------- the scraper and the health check


def test_the_scraper_skips_a_manual_retailer_and_still_checks_an_automatic_one(shop, db):
    script, rid, _, _ = shop
    script.queue = [reading(50.0)]
    control = price_watch.run(trigger="test", category="Barkmarker")
    assert control["checked"] == 1 and script.calls == 1, "the control: it is checked normally"

    set_manual(db, rid)
    script.queue = [reading(50.0)]
    summary = price_watch.run(trigger="test", category="Barkmarker")
    assert summary["checked"] == 0 and script.calls == 1, "manual: the scraper never calls it"


def test_scraper_failures_no_longer_trip_the_adapter_alarm_once_manual(shop, db):
    _, rid, _, lid = shop
    with dbmod.session(db) as conn:
        for _ in range(load_config().pi_streak_limit):
            pi_health.record_run(conn, {"zaitronics": {"ok": 0, "failed": 1, "error": "HTTP 429"}})
    checked_at(db, lid, ago(1))
    with dbmod.session(db) as conn:
        control = pi_health.health(conn)
    assert any("adapter zaitronics" in r for r in control["reasons"]), "the control: it alarms"

    set_manual(db, rid)
    with dbmod.session(db) as conn:
        after = pi_health.health(conn)
    assert not any("adapter zaitronics" in r for r in after["reasons"])
    assert [a["adapter"] for a in after["adapters"]] == []


# ------------------------------------------------------------------ the staleness alarm


def test_manual_does_not_mean_unwatched_a_stale_one_is_a_fault(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid, since=ago(24 * 20))
    checked_at(db, lid, ago(24 * 8))
    with dbmod.session(db) as conn:
        late = pi_health.health(conn)
    assert any("manual retailer Zaitronics" in r for r in late["reasons"])
    assert late["status"] == "unhealthy"

    checked_at(db, lid, ago(24 * 2))  # the control: two days is inside the limit
    with dbmod.session(db) as conn:
        fine = pi_health.health(conn)
    assert not any("manual retailer" in r for r in fine["reasons"])


def test_due_comes_before_overdue(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid, since=ago(24 * 20))
    cfg = load_config()
    for hours, due, overdue in ((5, False, False), (30, True, False),
                                (cfg.manual_stale_hours + 1, True, True)):
        checked_at(db, lid, ago(hours))
        with dbmod.session(db) as conn:
            row = pi_health.manual_retailers(conn)[0]["listings"][0]
        assert (row["due"], row["overdue"]) == (due, overdue), hours


def test_a_never_checked_listing_ages_from_when_the_retailer_went_manual(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid)
    checked_at(db, lid, None)
    with dbmod.session(db) as conn:
        fresh = pi_health.manual_retailers(conn)[0]["listings"][0]
        assert not fresh["due"], "flipping to manual must not raise an alarm at once"
        conn.execute("UPDATE retailers SET manual_since = ? WHERE id = ?", (ago(24 * 9), rid))
        old = pi_health.manual_retailers(conn)[0]["listings"][0]
    assert old["overdue"]


def test_the_scraper_flag_off_removes_it_from_the_manual_list(shop, db):
    _, rid, _, _ = shop
    set_manual(db, rid)
    set_manual(db, rid, on=False)
    with dbmod.session(db) as conn:
        assert pi_health.manual_retailers(conn) == []


# ------------------------------------------------------------------------ recording a check


def check(db, lid, price=59.95, stock="in_stock"):
    with dbmod.session(db) as conn:
        return price_watch.record_manual_check(conn, lid, price, stock)


def test_a_manual_check_records_price_stock_history_and_the_clock(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid)
    checked_at(db, lid, ago(100))
    out = check(db, lid, 59.95, "limited")
    assert out["price"] == 59.95
    with dbmod.session(db) as conn:
        row = conn.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()
        hist = conn.execute("SELECT source, advertised_price FROM price_history"
                            " WHERE listing_id = ?", (lid,)).fetchall()
        state = conn.execute("SELECT state, source, manual_locked FROM field_provenance"
                             " WHERE listing_id = ? AND field = 'advertised_price'",
                             (lid,)).fetchone()
        listing = pi_health.manual_retailers(conn)[0]["listings"][0]
    assert (row["advertised_price"], row["stock_status"], row["availability"]) == (
        59.95, "Limited stock", "limited")
    assert [(h["source"], h["advertised_price"]) for h in hist] == [("manual-check", 59.95)]
    assert not listing["due"], "the check reset the clock"
    assert (state["state"], state["source"], state["manual_locked"]) == (
        provenance.IMPORTED, "manual-check", 0), "not locked: a scraper may update it later"


def test_a_manual_check_never_makes_the_scraper_look_healthy(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid)
    check(db, lid)
    with dbmod.session(db) as conn:
        assert pi_health.last_success(conn, "Barkmarker") is None, (
            "only adapter sources count as a successful check")


@pytest.mark.parametrize("price, stock", [(0, "in_stock"), (-5, "in_stock"), ("59", "in_stock"),
                                           (True, "in_stock"), (59.95, "plenty"), (59.95, "unknown"),
                                           (None, "in_stock")])
def test_bad_input_is_refused_and_writes_nothing(shop, db, price, stock):
    _, _, _, lid = shop
    with pytest.raises(price_watch.ManualCheckError):
        check(db, lid, price, stock)
    with dbmod.session(db) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM price_history").fetchone()["c"] == 0


def test_a_hand_locked_price_refuses_the_check_and_leaves_everything_alone(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid)
    with dbmod.session(db) as conn:
        provenance.set_field(conn, lid, "advertised_price", 70.0, state=provenance.MANUAL,
                             source="ui", lock=True)
    with pytest.raises(price_watch.ManualCheckError, match="locked"):
        with dbmod.session(db) as conn:
            price_watch.record_manual_check(conn, lid, 59.95, "in_stock")
    with dbmod.session(db) as conn:
        row = conn.execute("SELECT advertised_price, stock_status FROM listings WHERE id = ?",
                           (lid,)).fetchone()
    assert row["advertised_price"] == 70.0 and row["stock_status"] is None, "rolled back whole"


def test_an_unknown_listing_is_a_lookup_error(shop, db):
    with pytest.raises(LookupError):
        check(db, 999999)


def test_back_in_stock_alerts_on_the_second_manual_check_not_the_first(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid)
    check(db, lid, 59.95, "out_of_stock")
    with dbmod.session(db) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM alert_events").fetchone()["c"] == 0, (
            "the first reading is a baseline, not news")
    check(db, lid, 59.95, "in_stock")
    with dbmod.session(db) as conn:
        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM alert_events")]
    assert "BACK_IN_STOCK" in kinds


# --------------------------------------------------------------------------------- the API


def test_api_toggle_list_and_check(client, db):
    with dbmod.session(db) as conn:
        retailer = store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")
        pid = store.create_product(
            conn, {"name": "Raspberry Pi 4 Model B 2GB", "model": "SC0193",
                   "category": "Barkmarker", "trigger_price": 100.0})
        lid = store.create_listing(conn, {"product_id": pid, "retailer_id": retailer["id"],
                                          "url": "https://z.test/pi4"})
    rid = retailer["id"]
    assert client.get("/api/manual-retailers").json() == []

    r = client.patch(f"/api/retailer/{rid}", json={"manual": True, "manual_reason": "429"})
    assert r.status_code == 200 and r.json()["manual_since"]
    listed = client.get("/api/manual-retailers").json()
    assert [x["name"] for x in listed] == ["Zaitronics"]

    ok = client.post(f"/api/retailers/{lid}/manual-check",
                     json={"price": 61.5, "availability": "in_stock"})
    assert ok.status_code == 200 and ok.json()["price"] == 61.5
    assert client.post(f"/api/retailers/{lid}/manual-check",
                       json={"price": "x", "availability": "in_stock"}).status_code == 400
    assert client.post("/api/retailers/999999/manual-check",
                       json={"price": 5, "availability": "in_stock"}).status_code == 404
    assert client.patch(f"/api/retailer/{rid}", json={}).status_code == 400

    assert client.patch(f"/api/retailer/{rid}", json={"manual": False}).status_code == 200
    assert client.get("/api/manual-retailers").json() == []


def test_pages_carry_the_banner_container_and_the_retailers_page_the_toggle(client, db):
    with dbmod.session(db) as conn:
        r = store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")
        bare = store.ensure_retailer(conn, "Some Shop")  # no adapter: by hand already, no toggle
    assert 'id="manual-banner"' in client.get("/").text
    page = client.get("/retailers").text
    assert f'data-retailer-manual="{r["id"]}"' in page and "Check by hand" in page
    assert f'data-retailer-manual="{bare["id"]}"' not in page, (
        "a retailer with no scraper has nothing to toggle")

    client.patch(f"/api/retailer/{r['id']}", json={"manual": True, "manual_reason": "429"})
    page = client.get("/retailers").text
    assert "Back to automatic" in page and "checked by hand" in page


# -------------------------------------------------------------------- review follow-ups


def test_going_manual_gives_a_full_grace_period_for_the_first_check(shop, db):
    """Data that was already old when the flag was set must not alarm at once."""
    _, rid, _, lid = shop
    checked_at(db, lid, ago(24 * 10))
    set_manual(db, rid)  # manual_since = now
    with dbmod.session(db) as conn:
        row = pi_health.manual_retailers(conn)[0]["listings"][0]
        health = pi_health.health(conn)
    assert row["due"] and row["age_hours"] > 200, "the banner still shows the data's real age"
    assert not row["overdue"], "but the alarm clock starts when it went manual"
    assert not any("manual retailer" in r for r in health["reasons"])
    # The control: a week after going manual with no check, it does alarm.
    set_manual(db, rid, since=ago(24 * 8))
    with dbmod.session(db) as conn:
        assert pi_health.manual_retailers(conn)[0]["listings"][0]["overdue"]


def buy(db, pid, lid, protection_until):
    with dbmod.session(db) as conn:
        conn.execute("UPDATE products SET status = 'PURCHASED' WHERE id = ?", (pid,))
        conn.execute(
            "INSERT INTO purchases (product_id, listing_id, purchased_at, price_paid,"
            " price_protection_until) VALUES (?, ?, ?, 60.0, ?)",
            (pid, lid, ago(24), protection_until),
        )


def test_a_bought_pi_inside_its_protection_window_is_still_watched(shop, db):
    _, rid, pid, lid = shop
    set_manual(db, rid, since=ago(24 * 20))
    buy(db, pid, lid, (datetime.now(UTC) + timedelta(days=5)).strftime("%Y-%m-%d"))
    with dbmod.session(db) as conn:
        names = [r["name"] for r in pi_health.manual_retailers(conn)]
    assert names == ["Zaitronics"], "the scraper used to cover this; the banner must now"


def test_a_bought_pi_outside_any_window_is_not_nagged_about(shop, db):
    _, rid, pid, lid = shop
    set_manual(db, rid, since=ago(24 * 20))
    buy(db, pid, lid, (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%d"))
    with dbmod.session(db) as conn:
        assert pi_health.manual_retailers(conn) == []


def test_a_manual_check_is_refused_for_a_retailer_the_scraper_owns(shop, db):
    _, rid, _, lid = shop
    with pytest.raises(price_watch.ManualCheckError, match="checked by the scraper"):
        check(db, lid)
    set_manual(db, rid)
    assert check(db, lid)["price"] == 59.95, "the control: once marked manual it is accepted"


def test_a_manual_check_is_refused_for_a_switched_off_listing(shop, db):
    _, rid, _, lid = shop
    set_manual(db, rid)
    with dbmod.session(db) as conn:
        conn.execute("UPDATE listings SET active = 0 WHERE id = ?", (lid,))
    with pytest.raises(price_watch.ManualCheckError, match="switched off"):
        check(db, lid)


def test_a_retailer_with_no_scraper_needs_no_flag(db):
    with dbmod.session(db) as conn:
        retailer = store.ensure_retailer(conn, "Some Shop")  # no adapter
        pid = store.create_product(
            conn, {"name": "Raspberry Pi 4 Model B 2GB", "model": "SC0193",
                   "category": "Barkmarker", "trigger_price": 100.0})
        lid = store.create_listing(
            conn, {"product_id": pid, "retailer_id": retailer["id"], "url": "https://s.test/p"})
    assert check(db, lid)["price"] == 59.95


def test_the_manual_flag_must_be_a_real_boolean(client, db):
    with dbmod.session(db) as conn:
        rid = store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")["id"]
    for bad in ("false", "true", 0, 1, None):
        assert client.patch(f"/api/retailer/{rid}", json={"manual": bad}).status_code == 400, bad
    with dbmod.session(db) as conn:
        assert conn.execute("SELECT manual_since FROM retailers WHERE id = ?",
                            (rid,)).fetchone()["manual_since"] is None, "nothing changed"
    assert client.patch(f"/api/retailer/{rid}", json={"manual": True}).status_code == 200


def test_alert_delivery_problems_are_reported_not_dropped(client, db, monkeypatch):
    with dbmod.session(db) as conn:
        retailer = store.ensure_retailer(conn, "Zaitronics", adapter="zaitronics")
        pid = store.create_product(
            conn, {"name": "Raspberry Pi 4 Model B 2GB", "model": "SC0193",
                   "category": "Barkmarker", "trigger_price": 100.0})
        lid = store.create_listing(conn, {"product_id": pid, "retailer_id": retailer["id"],
                                          "url": "https://z.test/pi4"})
        store.set_retailer_manual(conn, retailer["id"], True, "429")
    body = {"price": 61.5, "availability": "in_stock"}
    quiet = client.post(f"/api/retailers/{lid}/manual-check", json=body).json()
    assert quiet["alerts"] == {"sent": 0, "failed": 0, "expired": 0, "deferred": 0}

    monkeypatch.setenv("SHOPWATCH_ALERTS_ENABLED", "true")
    monkeypatch.setattr(pi_events, "deliver_pending", lambda conn, config=None: {
        "sent": 0, "failed": 2, "expired": 1, "deferred": 0, "failures": ["ntfy down"],
        "payload": []})
    loud = client.post(f"/api/retailers/{lid}/manual-check", json=body).json()
    assert (loud["alerts"]["failed"], loud["alerts"]["expired"]) == (2, 1)
