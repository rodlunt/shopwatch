"""Watcher behaviour: failures are survivable, locks hold, nothing is invented."""

from __future__ import annotations

import pytest

from app import price_watch, provenance, retailers, store
from app.db import connect
from app.retailers.base import FetchError, Observation


@pytest.fixture()
def wired(seeded, monkeypatch):
    """Seeded board with URLs on every listing, so adapters are actually attempted."""
    with connect(seeded) as conn:
        conn.execute("UPDATE listings SET url = 'https://example.invalid/product'")
        conn.commit()
    return seeded


def get(conn, retailer_name, field):
    row = conn.execute(
        "SELECT l.* FROM listings l JOIN retailers r ON r.id = l.retailer_id"
        " WHERE lower(r.name) = lower(?)",
        (retailer_name,),
    ).fetchone()
    return row[field]


def stub_adapters(monkeypatch, behaviour):
    """Replace every adapter's check() with a function of the adapter slug."""

    def fake_check(self, url, expected_model=None):
        return behaviour(self.slug)

    monkeypatch.setattr(retailers.base.RetailerAdapter, "check", fake_check, raising=True)


def test_successful_run_writes_live_values_and_history(wired, monkeypatch):
    stub_adapters(
        monkeypatch,
        lambda slug: Observation(advertised_price=1234.0, stock_status="In Stock",
                                 model_on_page="HW-Q930H/XY"),
    )
    summary = price_watch.run(send_alerts=False)
    assert summary["status"] == "ok"
    assert summary["checked"] == 5
    assert summary["errors"] == 0
    with connect(wired) as conn:
        assert get(conn, "JB Hi-Fi", "advertised_price") == 1234.0
        product = store.product_by_model(conn, "HW-Q930H/XY")
        history = store.price_history(conn, product["id"])
        assert len([h for h in history if h["source"] != "seed"]) == 5


def test_a_fetch_failure_never_destroys_the_last_good_value(wired, monkeypatch):
    with connect(wired) as conn:
        before = get(conn, "JB Hi-Fi", "advertised_price")
    assert before == 1699.0

    stub_adapters(monkeypatch, lambda slug: (_ for _ in ()).throw(FetchError("403: blocked")))
    summary = price_watch.run(send_alerts=False)

    assert summary["status"] == "failed", "every adapter failed, so the run must not report ok"
    assert summary["errors"] == 5
    with connect(wired) as conn:
        assert get(conn, "JB Hi-Fi", "advertised_price") == before


def test_one_retailer_failing_does_not_abort_the_others(wired, monkeypatch):
    def behaviour(slug):
        if slug == "jb_hifi":
            raise FetchError("403: blocked")
        if slug == "harvey_norman":
            raise RuntimeError("adapter bug")
        return Observation(advertised_price=999.0)

    stub_adapters(monkeypatch, behaviour)
    summary = price_watch.run(send_alerts=False)

    assert summary["errors"] == 2
    assert summary["ok"] == 3
    assert summary["status"] == "partial"
    with connect(wired) as conn:
        assert get(conn, "The Good Guys", "advertised_price") == 999.0
        assert get(conn, "JB Hi-Fi", "advertised_price") == 1699.0


def test_manual_override_survives_an_automated_run(wired, monkeypatch):
    with connect(wired) as conn:
        product = store.product_by_model(conn, "HW-Q930H/XY")
        listing = store.find_listing(
            conn, product["id"], store.ensure_retailer(conn, "Crowdshop")["id"]
        )
        provenance.set_field(
            conn, listing["id"], "freight", 89.0, state=provenance.MANUAL, source="checkout"
        )
        conn.commit()

    stub_adapters(monkeypatch, lambda slug: Observation(advertised_price=869.0, freight=0.0))
    price_watch.run(send_alerts=False)

    with connect(wired) as conn:
        assert get(conn, "Crowdshop", "freight") == 89.0
        assert get(conn, "Crowdshop", "advertised_price") == 869.0


def test_a_listing_without_a_url_is_skipped_not_errored(seeded, monkeypatch):
    stub_adapters(monkeypatch, lambda slug: Observation(advertised_price=1.0))
    summary = price_watch.run(send_alerts=False)
    assert summary["skipped"] == 5
    assert summary["errors"] == 0
    assert summary["status"] == "ok"


def test_a_retailer_with_no_adapter_is_skipped(wired, monkeypatch):
    with connect(wired) as conn:
        product = store.product_by_model(conn, "HW-Q930H/XY")
        retailer = store.ensure_retailer(conn, "Bing Lee")
        store.create_listing(
            conn,
            {"product_id": product["id"], "retailer_id": retailer["id"],
             "url": "https://example.invalid/bing"},
        )
        conn.commit()
    stub_adapters(monkeypatch, lambda slug: Observation(advertised_price=1.0))
    summary = price_watch.run(send_alerts=False)
    assert summary["skipped"] == 1
    assert summary["checked"] == 6


def test_a_model_mismatch_flags_verification(wired, monkeypatch):
    stub_adapters(
        monkeypatch,
        lambda slug: Observation(
            advertised_price=899.0, warnings=["model mismatch: page shows 'HW-Q990H/XY'"]
        ),
    )
    price_watch.run(send_alerts=False)
    with connect(wired) as conn:
        row = conn.execute(
            "SELECT l.id FROM listings l JOIN retailers r ON r.id = l.retailer_id"
            " WHERE r.adapter = 'jb_hifi'"
        ).fetchone()
        verification = provenance.verification_map(conn, row["id"])
        assert verification["model"]["status"] == provenance.FLAGGED
