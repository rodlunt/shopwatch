"""End-to-end behaviour through the HTTP surface."""

from __future__ import annotations

from app import provenance, store
from app.db import connect


def q930h(client):
    products = client.get("/api/products").json()
    return next(p for p in products if p["model"] == "HW-Q930H/XY")


def test_board_page_renders_the_seed_data(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "HW-Q930H/XY" in body
    assert "Crowdshop" in body
    assert "Harvey Norman" in body
    assert "$900" in body, "the trigger price is on the page"


def test_product_page_renders(client):
    product = q930h(client)
    response = client.get(f"/products/{product['id']}")
    assert response.status_code == 200
    assert "Price history" in response.text
    assert "Samsung Q-Series" in response.text


def test_seed_values_are_present_and_correct(client):
    product = q930h(client)
    assert product["verdict"] == "MAYBE"
    assert product["trigger_price"] == 900
    assert product["excellent_price"] == 850
    assert product["historical_low_price"] == 800
    assert "Q990" in product["fit_notes"]

    by_retailer = {listing["retailer_name"]: listing for listing in product["listings"]}
    assert by_retailer["Crowdshop"]["advertised_price"] == 869
    assert by_retailer["Crowdshop"]["freight"] is None, "freight is unresolved, not free"
    assert by_retailer["Crowdshop"]["classification"] == "UNRESOLVED"
    assert "869-889" in by_retailer["Crowdshop"]["price_guide"]
    assert by_retailer["Appliance Central"]["advertised_price"] == 1059
    assert by_retailer["Harvey Norman"]["advertised_price"] == 1695
    assert by_retailer["JB Hi-Fi"]["advertised_price"] == 1699
    assert by_retailer["The Good Guys"]["advertised_price"] == 1699
    assert all(listing["condition"] == "NEW" for listing in product["listings"])


def test_the_matrix_is_ordered_by_delivered_price(client):
    product = q930h(client)
    names = [listing["retailer_name"] for listing in product["listings"]]
    assert names[0] == "Crowdshop"
    assert names[1] == "Appliance Central"


def test_inline_edit_persists_and_recalculates(client):
    product = q930h(client)
    listing = next(listing for listing in product["listings"]
                   if listing["retailer_name"] == "Crowdshop")

    response = client.patch(f"/api/retailers/{listing['id']}", json={"freight": "25"})
    assert response.status_code == 200
    updated = response.json()["listing"]
    assert updated["freight"] == 25.0
    assert updated["delivered_price"] == 894.0
    assert updated["delivered_resolved"] is True
    assert updated["classification"] == "TRIGGER_MET"
    assert updated["provenance"]["freight"]["manual_locked"] == 1

    # and it is still there on a fresh read
    again = client.get(f"/api/retailers/{listing['id']}").json()
    assert again["freight"] == 25.0


def test_manual_override_survives_an_imported_automated_update(client):
    product = q930h(client)
    listing = next(listing for listing in product["listings"]
                   if listing["retailer_name"] == "Crowdshop")
    client.patch(f"/api/retailers/{listing['id']}", json={"freight": "89"})

    result = client.post(
        "/api/import",
        json=[{"model": "HW-Q930H/XY", "retailer": "Crowdshop", "price": 879, "freight": 0,
               "stock": "In Stock"}],
    ).json()
    assert result["applied"] == 1
    assert "freight" in result["results"][0]["preserved_manual"]

    fresh = client.get(f"/api/retailers/{listing['id']}").json()
    assert fresh["freight"] == 89.0, "the manual value survived"
    assert fresh["advertised_price"] == 879.0, "the unlocked field updated"


def test_clear_override_returns_the_field_to_automation(client):
    product = q930h(client)
    listing = next(listing for listing in product["listings"]
                   if listing["retailer_name"] == "Crowdshop")
    client.patch(f"/api/retailers/{listing['id']}", json={"freight": "89"})

    cleared = client.post(
        f"/api/retailers/{listing['id']}/clear-override", json={"field": "freight"}
    ).json()
    assert cleared["cleared"] == "freight"
    assert cleared["listing"]["provenance"]["freight"]["manual_locked"] == 0

    client.post(
        "/api/import",
        json=[{"model": "HW-Q930H/XY", "retailer": "Crowdshop", "price": 869, "freight": 12}],
    )
    fresh = client.get(f"/api/retailers/{listing['id']}").json()
    assert fresh["freight"] == 12.0


def test_patching_an_unknown_field_is_rejected(client):
    product = q930h(client)
    listing = product["listings"][0]
    response = client.patch(f"/api/retailers/{listing['id']}", json={"id": 9999})
    assert response.status_code == 400


def test_export_import_round_trip_over_http(client):
    snapshot = client.get("/api/export").json()
    assert snapshot["format"] == "shopwatch-snapshot"
    result = client.post("/api/import", json=snapshot)
    assert result.status_code == 200
    assert result.json()["products"] == 1
    assert len(client.get("/api/products").json()) == 1, "re-import must not duplicate the product"


def test_csv_export(client):
    response = client.get("/api/export.csv")
    assert response.status_code == 200
    assert "HW-Q930H/XY" in response.text
    assert response.text.splitlines()[0].startswith("product,model,verdict,retailer")


def test_price_history_endpoint(client):
    product = q930h(client)
    history = client.get(f"/api/price-history/{product['id']}").json()
    assert len(history) == 5, "one seeded observation per listing"
    assert {h["source"] for h in history} == {"seed"}


def test_adding_a_listing_through_the_api(client):
    product = q930h(client)
    response = client.post(
        f"/api/products/{product['id']}/retailers",
        json={"retailer": "Bing Lee", "advertised_price": 1450, "condition": "NEW",
              "stock_status": "Limited"},
    )
    assert response.status_code == 201
    listing = response.json()
    assert listing["retailer_name"] == "Bing Lee"
    assert listing["provenance"]["advertised_price"]["manual_locked"] == 1


def test_creating_a_product_in_another_category(client):
    response = client.post(
        "/api/products",
        json={"name": "LG C4 65", "model": "OLED65C4PSA", "brand": "LG", "category": "tv",
              "trigger_price": 2200, "specs": {"panel_technology": "OLED", "hdmi_21_ports": 4}},
    )
    assert response.status_code == 201
    product = response.json()
    assert product["specs"]["panel_technology"] == "OLED"
    assert client.get(f"/products/{product['id']}").status_code == 200


def test_category_profiles_are_seeded(client):
    fields = client.get("/api/categories/tv/fields").json()
    keys = {f["field_key"] for f in fields}
    assert {"panel_technology", "hdmi_21_ports", "vrr", "earc"} <= keys
    soundbar = {f["field_key"] for f in client.get("/api/categories/soundbar/fields").json()}
    assert "channels" in soundbar and "panel_technology" not in soundbar


def test_adding_a_category_field_without_a_migration(client):
    client.post(
        "/api/categories/espresso_machine/fields",
        json={"field_key": "boiler_type", "label": "Boiler type", "kind": "text"},
    )
    fields = client.get("/api/categories/espresso_machine/fields").json()
    assert fields[0]["field_key"] == "boiler_type"


def test_price_watch_endpoint_runs_and_reports(client):
    summary = client.post("/api/price-watch/run", json={"send_alerts": False}).json()
    assert summary["status"] == "ok"
    assert summary["skipped"] == 5, "seeded listings have no URL, so nothing is fetched"


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["products"] == 1


def test_seeding_twice_does_not_duplicate_or_clobber(seeded):
    from app.seed import seed_all

    with connect(seeded) as conn:
        product = store.product_by_model(conn, "HW-Q930H/XY")
        listing = store.find_listing(
            conn, product["id"], store.ensure_retailer(conn, "Crowdshop")["id"]
        )
        provenance.set_field(conn, listing["id"], "advertised_price", 799.0,
                             state=provenance.MANUAL)
        conn.commit()

    seed_all()

    with connect(seeded) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"] == 5
        assert conn.execute(
            "SELECT advertised_price FROM listings WHERE id = ?", (listing["id"],)
        ).fetchone()[0] == 799.0


# --------------------------------------------------------- asset cache busting


def test_asset_token_changes_when_a_static_file_changes(tmp_path, monkeypatch):
    """The token must be derived from the bytes, not from a constant somebody bumps.

    Caddy serves /static immutable for 30 days. The old token was a hand-maintained
    version string that was never bumped, so every stylesheet change since the first
    commit was invisible to a returning browser with nothing reporting it.
    """
    from app import main

    static = tmp_path / "static"
    static.mkdir()
    (static / "style.css").write_text("body{color:red}")
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)

    before = main._asset_version()
    (static / "style.css").write_text("body{color:blue}")
    after = main._asset_version()

    assert before != after, "a changed stylesheet must produce a new token"
    assert len(after) == 12


def test_asset_token_is_stable_when_nothing_changes(tmp_path, monkeypatch):
    """A restart that changes no asset must not expire every browser's cache."""
    from app import main

    static = tmp_path / "static"
    static.mkdir()
    (static / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)

    assert main._asset_version() == main._asset_version()


def test_healthz_still_reports_the_semantic_version():
    """The asset hash answers "is your cache stale". It is not the app's version."""
    from fastapi.testclient import TestClient

    from app import __version__, main

    with TestClient(main.app) as client:
        assert client.get("/healthz").json()["version"] == __version__
        assert client.get("/api/meta").json()["version"] == __version__


# ------------------------------------------------- the axis is reachable as text


def test_the_axis_publishes_its_figures_as_text(client):
    """role="img" hid the whole subtree, so every plotted price was unreachable.

    The dots stay hidden (absolutely positioned marks read as noise), but the same
    numbers have to exist as real content or the axis is picture-only.
    """
    html = client.get("/").text

    assert 'role="img"' not in html, "the axis subtree must not be hidden behind an image role"
    assert "visually-hidden" in html, "the text version of the axis must be present"
    assert "Appliance Central" in html
    assert "target:" in html, "thresholds must be readable as text, not only as ticks"


def test_the_zoom_target_says_what_the_keys_do(client):
    html = client.get("/").text
    assert "aria-describedby" in html
    assert "arrow keys" in html, "a focusable zoom target with undiscoverable keys is not usable"
