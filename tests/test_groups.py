"""Watch groups: several different products tracked as competing candidates.

Buying one settles the question for the rest, and an archived product (whether via a
group purchase cascade or the standalone "give up" button) must never be researchable
again.
"""

from __future__ import annotations

import pytest

from app import research, store


@pytest.fixture()
def two_candidates(conn):
    """Two standalone products, not yet grouped."""
    a = store.create_product(conn, {"name": "RTX 4070", "model": "RTX-4070-A"})
    b = store.create_product(conn, {"name": "RX 7800 XT", "model": "RX-7800-XT-A"})
    conn.commit()
    return a, b


def test_create_group_requires_a_name(conn):
    with pytest.raises(ValueError, match="name"):
        store.create_group(conn, {"notes": "no name given"})


def test_set_product_group_attaches_and_detaches(conn, two_candidates):
    a, _b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()

    store.set_product_group(conn, a, group_id)
    conn.commit()
    assert store.get_product(conn, a)["group_id"] == group_id

    store.set_product_group(conn, a, None)
    conn.commit()
    assert store.get_product(conn, a)["group_id"] is None


def test_group_view_assembles_members_and_merged_scale(conn, two_candidates):
    a, b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.set_product_group(conn, a, group_id)
    store.set_product_group(conn, b, group_id)
    conn.commit()

    retailer = store.ensure_retailer(conn, "JB Hi-Fi")
    store.create_listing(conn, {
        "product_id": a, "retailer_id": retailer["id"], "advertised_price": 899,
    })
    store.create_listing(conn, {
        "product_id": b, "retailer_id": retailer["id"], "advertised_price": 749,
    })
    conn.commit()

    group = store.group_view(conn, group_id)
    assert len(group["members"]) == 2
    assert group["scale"] is not None
    assert len(group["scale"]["points"]) == 2
    # Cheapest point should be positioned lower than the dearest.
    values = sorted(p["value"] for p in group["scale"]["points"])
    assert values == [749.0, 899.0]


def test_group_view_best_is_the_cheapest_non_ruled_out_point(conn, two_candidates):
    a, b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.set_product_group(conn, a, group_id)
    store.set_product_group(conn, b, group_id)
    conn.commit()

    retailer = store.ensure_retailer(conn, "JB Hi-Fi")
    la = store.create_listing(conn, {
        "product_id": a, "retailer_id": retailer["id"], "advertised_price": 500,
    })
    store.create_listing(conn, {
        "product_id": b, "retailer_id": retailer["id"], "advertised_price": 749,
    })
    conn.commit()

    group = store.group_view(conn, group_id)
    assert group["best"]["value"] == 500.0

    # Rule out the cheapest one - it must never win, however cheap.
    conn.execute("UPDATE listings SET ruled_out = 1 WHERE id = ?", (la,))
    conn.commit()
    group = store.group_view(conn, group_id)
    assert group["best"]["value"] == 749.0


def test_group_view_with_no_priced_listings_has_no_scale(conn, two_candidates):
    a, _b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.set_product_group(conn, a, group_id)
    conn.commit()

    group = store.group_view(conn, group_id)
    assert group["scale"] is None


def test_list_groups_excludes_archived_by_default(conn):
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.update_group(conn, group_id, {"name": "GPU search"})  # touch, no-op
    conn.execute("UPDATE watch_groups SET archived = 1 WHERE id = ?", (group_id,))
    conn.commit()

    assert store.list_groups(conn) == []
    assert len(store.list_groups(conn, include_archived=True)) == 1


def test_list_products_exclude_grouped_hides_grouped_products(conn, two_candidates):
    a, b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.set_product_group(conn, a, group_id)
    conn.commit()

    all_products = store.list_products(conn)
    ungrouped_only = store.list_products(conn, exclude_grouped=True)
    assert {p["id"] for p in all_products} == {a, b}
    assert {p["id"] for p in ungrouped_only} == {b}


def test_buying_one_candidate_archives_the_rest_of_the_group(conn, two_candidates):
    a, b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.set_product_group(conn, a, group_id)
    store.set_product_group(conn, b, group_id)
    conn.commit()

    store.record_purchase(conn, a, {"price_paid": 899})
    conn.commit()

    bought = store.get_product(conn, a)
    other = store.get_product(conn, b)
    assert bought["status"] == "PURCHASED"
    assert not bought["archived"]  # the purchased one itself is not archived
    assert other["archived"] == 1
    assert store.get_group(conn, group_id)["archived"] == 1


def test_buying_a_standalone_product_does_not_touch_unrelated_products(conn, two_candidates):
    """No group membership means no cascade - archiving the wrong thing would be worse
    than not archiving anything."""
    a, b = two_candidates
    store.record_purchase(conn, a, {"price_paid": 899})
    conn.commit()

    assert not store.get_product(conn, b)["archived"]


def test_undo_purchase_does_not_revive_archived_group_siblings(conn, two_candidates):
    a, b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.set_product_group(conn, a, group_id)
    store.set_product_group(conn, b, group_id)
    conn.commit()
    store.record_purchase(conn, a, {"price_paid": 899})
    conn.commit()

    store.undo_purchase(conn, a)
    conn.commit()

    assert store.get_product(conn, a)["status"] == "ACTIVE"
    assert store.get_product(conn, b)["archived"] == 1  # still archived, not revived


def test_purchased_product_stays_visible_on_the_board_after_its_group_resolves(
    conn, two_candidates
):
    """The control this test exists for: a purchased, non-archived product must never
    become invisible just because its now-archived group stopped rendering a card."""
    a, b = two_candidates
    group_id = store.create_group(conn, {"name": "GPU search"})
    conn.commit()
    store.set_product_group(conn, a, group_id)
    store.set_product_group(conn, b, group_id)
    conn.commit()

    store.record_purchase(conn, a, {"price_paid": 899})
    conn.commit()

    # The group itself is gone from the board (archived)...
    assert store.list_groups(conn) == []
    # ...but the purchased product must still appear in the ungrouped board list,
    # because its group no longer renders a card that would show it instead.
    ungrouped = store.list_products(conn, status="ALL", exclude_grouped=True)
    assert a in {p["id"] for p in ungrouped}
    # The other, archived candidate correctly stays hidden either way.
    assert b not in {p["id"] for p in ungrouped}


def test_research_job_refuses_on_an_archived_product(conn, two_candidates):
    a, _b = two_candidates
    retailer = store.ensure_retailer(conn, "JB Hi-Fi")
    conn.execute("UPDATE products SET archived = 1 WHERE id = ?", (a,))
    conn.commit()

    with pytest.raises(ValueError, match="archived"):
        research.create_job(conn, a, [retailer["id"]])


def test_research_job_works_normally_on_an_unarchived_product(conn, two_candidates):
    a, _b = two_candidates
    retailer = store.ensure_retailer(conn, "JB Hi-Fi")
    conn.commit()
    job_id = research.create_job(conn, a, [retailer["id"]])  # must not raise
    assert job_id is not None
