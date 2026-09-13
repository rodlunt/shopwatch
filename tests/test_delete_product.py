"""Permanent deletion: a real cascade, deliberately separate from archiving.

api_archive_product (DELETE /api/products/{id}) is the reversible "Give up on this"
path and never removes a row. store.delete_product / DELETE /api/products/{id}/permanently
is the other one - the control here is that it must actually fail to leave anything
behind, not just report success (hardening rule 13: a control must fail on the broken
version, so these build real child rows first and prove they are gone after).
"""

from __future__ import annotations

from app import research, store


def _fully_loaded_product(conn):
    """A product with a listing, price history, a purchase and a research job -
    one row in every table that cascades off products(id)."""
    product_id = store.create_product(conn, {"name": "Doomed Widget", "model": "DOOM-1"})
    retailer = store.ensure_retailer(conn, "Test Retailer")
    listing_id = store.create_listing(conn, {
        "product_id": product_id, "retailer_id": retailer["id"], "advertised_price": 100,
    })
    conn.execute(
        "INSERT INTO price_history (product_id, listing_id, retailer_id, advertised_price,"
        " delivered_price, observed_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (product_id, listing_id, retailer["id"], 100, 100),
    )
    store.record_purchase(conn, product_id, {"price_paid": 100, "listing_id": listing_id})
    research.create_job(conn, product_id, [retailer["id"]])
    conn.commit()
    return product_id


def _child_row_counts(conn, product_id):
    tables = ["listings", "price_history", "purchases", "research_jobs"]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE product_id = ?",
                             (product_id,)).fetchone()[0] for t in tables}


def test_delete_product_removes_the_product(conn):
    product_id = store.create_product(conn, {"name": "Gone", "model": "GONE-1"})
    conn.commit()

    store.delete_product(conn, product_id)
    conn.commit()

    assert store.get_product(conn, product_id) is None


def test_delete_product_cascades_to_every_dependent_table(conn):
    product_id = _fully_loaded_product(conn)
    before = _child_row_counts(conn, product_id)
    assert all(n > 0 for n in before.values()), f"fixture did not actually create rows: {before}"

    store.delete_product(conn, product_id)
    conn.commit()

    after = _child_row_counts(conn, product_id)
    assert all(n == 0 for n in after.values()), f"cascade left rows behind: {after}"


def test_delete_product_on_an_unknown_id_is_a_no_op(conn):
    store.delete_product(conn, 999999)  # must not raise


def test_archiving_a_product_never_deletes_it(conn):
    """The control for the OTHER endpoint: proves the two paths stay distinct."""
    product_id = store.create_product(conn, {"name": "Archived", "model": "ARCH-1"})
    conn.commit()

    store.update_product(conn, product_id, {"archived": 1})
    conn.commit()

    assert store.get_product(conn, product_id) is not None


def test_delete_permanently_endpoint_removes_the_product(client):
    products = client.get("/api/products").json()
    pid = products[0]["id"]

    response = client.delete(f"/api/products/{pid}/permanently")
    assert response.status_code == 200
    assert response.json() == {"deleted": pid}
    assert client.get(f"/api/products/{pid}").status_code == 404


def test_delete_permanently_endpoint_is_a_404_for_an_unknown_product(client):
    response = client.delete("/api/products/999999/permanently")
    assert response.status_code == 404


def test_archive_endpoint_is_unaffected_by_the_new_delete_endpoint(client):
    """The two DELETE routes on different paths must not shadow each other."""
    products = client.get("/api/products").json()
    pid = products[0]["id"]

    response = client.delete(f"/api/products/{pid}")
    assert response.status_code == 200
    assert response.json() == {"archived": pid}
    assert client.get(f"/api/products/{pid}").status_code == 200, "archived, not deleted"
