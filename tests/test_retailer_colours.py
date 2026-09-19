"""Issue #100: colour-code retailers on the price axis.

Each retailer gets a stable colour, used for both its axis dot and its row in the
listing list below a product, so the two views visually match without hovering or
reading names. store.retailer_color() does the hashing; product_view() and
pricing.threshold_scale() are what carry the result onto the listing rows and the
axis points respectively - this is where a mismatch between the two would show up.
"""

from __future__ import annotations

from app import pricing, store


def test_retailer_color_is_stable_for_the_same_id():
    assert store.retailer_color(7) == store.retailer_color(7)


def test_retailer_color_has_no_opinion_without_an_id():
    assert store.retailer_color(None) is None


def test_retailer_color_draws_from_the_shared_candidate_palette():
    """Reuses group_view's existing --candidate-1..8 vars (issue #100's "no schema
    change" option) rather than a second palette just for retailers."""
    color = store.retailer_color(42)
    assert color is not None
    assert color.startswith("var(--candidate-")
    index = int(color.removeprefix("var(--candidate-").removesuffix(")"))
    assert 1 <= index <= len(store.CANDIDATE_PALETTE)


def test_different_retailer_ids_are_not_all_the_same_colour():
    """A control against a hash that quietly collapses to one bucket: with a fixed
    8-colour palette and a spread of ids, more than one colour must come out."""
    colors = {store.retailer_color(i) for i in range(1, 33)}
    assert len(colors) > 1


def test_product_view_gives_every_listing_a_retailer_color(conn):
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "HW-Q930H"})
    jb = store.ensure_retailer(conn, "JB Hi-Fi")
    hn = store.ensure_retailer(conn, "Harvey Norman")
    store.create_listing(conn, {
        "product_id": product_id, "retailer_id": jb["id"], "advertised_price": 899, "freight": 0,
    })
    store.create_listing(conn, {
        "product_id": product_id, "retailer_id": hn["id"], "advertised_price": 950, "freight": None,
    })
    conn.commit()

    view = store.product_view(conn, product_id)
    colors = {listing["retailer_id"]: listing["retailer_color"] for listing in view["listings"]}
    assert colors[jb["id"]] == store.retailer_color(jb["id"])
    assert colors[hn["id"]] == store.retailer_color(hn["id"])
    assert colors[jb["id"]] != colors[hn["id"]]


def test_the_axis_point_and_the_listing_row_agree_on_colour(conn):
    """The whole point of the issue: a retailer's dot and its row must not be free to
    drift apart, because nothing derives the colour a second, independent way."""
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "HW-Q930H"})
    jb = store.ensure_retailer(conn, "JB Hi-Fi")
    store.create_listing(conn, {
        "product_id": product_id, "retailer_id": jb["id"], "advertised_price": 899, "freight": 0,
    })
    conn.commit()

    view = store.product_view(conn, product_id)
    row_color = view["listings"][0]["retailer_color"]
    point = next(p for p in view["scale"]["points"] if p["id"] == view["listings"][0]["id"])
    assert point["retailer_color"] == row_color


def test_threshold_scale_carries_retailer_color_through_without_computing_it():
    """pricing stays about positions, not presentation: it must copy whatever the
    caller already put on the listing, not derive a colour of its own."""
    scale = pricing.threshold_scale(
        {"trigger_price": 900},
        900,
        [{
            "id": 1, "retailer_name": "JB Hi-Fi", "delivered_price": 850,
            "delivered_resolved": True, "classification": "TRIGGER_MET",
            "retailer_color": "var(--candidate-2)",
        }],
    )
    assert scale["points"][0]["retailer_color"] == "var(--candidate-2)"


def test_threshold_scale_tolerates_a_listing_with_no_color_set():
    """Control: callers that never set retailer_color (group_view's own points, an
    older caller) must not crash threshold_scale."""
    scale = pricing.threshold_scale(
        {"trigger_price": 900}, 900,
        [{"id": 1, "retailer_name": "JB Hi-Fi", "delivered_price": 850,
          "delivered_resolved": True, "classification": "TRIGGER_MET"}],
    )
    assert scale["points"][0]["retailer_color"] is None
