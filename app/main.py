"""FastAPI application: HTML comparison board plus a plain local JSON API."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (
    __version__,
    alerts,
    ingest,
    llm_jobs,
    mailwatch,
    offers,
    price_watch,
    pricing,
    provenance,
    research,
    retailers,
    store,
)
from .config import load_config
from .db import backup, migrate, session, utcnow

BASE_DIR = Path(__file__).parent

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Apply migrations on boot. Never destructive: an existing database is left alone.

    Deliberately does NOT reconcile research_jobs here. The host-level runner that does
    a job's real work is a separate process on opti, independent of this container - an
    ordinary redeploy only replaces this container and never touches it, so a RUNNING
    job at container startup is not evidence of anything gone wrong. Staleness is judged
    purely by elapsed time (`research.reconcile_stale`, called from every job read),
    which is correct regardless of *why* nothing has reported back yet.
    """
    migrate()
    yield


app = FastAPI(title="Shopwatch", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

def _asset_version() -> str:
    """Cache-busting token derived from the asset bytes themselves.

    Caddy serves /static with a 30-day immutable cache, so a changed stylesheet only
    reaches a browser that has already loaded the page if the URL changes. The token
    used to be `__version__`, a hand-maintained constant set in the first commit and
    never bumped, which meant every CSS and JS change since was invisible to a
    returning visitor: deploy green, container healthy, file correct on disk, old page
    on screen, and nothing anywhere reporting it.

    A content hash cannot fall out of step with the file it describes, which is the
    whole point: the previous scheme depended on somebody remembering.
    """
    digest = hashlib.sha256()
    for path in sorted((BASE_DIR / "static").rglob("*")):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


#: Computed once at import. The container is recreated on deploy, so a changed asset
#: always gets a fresh token, and a restart that changes nothing keeps the old one.
ASSET_VERSION = _asset_version()

def _resolve_git_sha() -> tuple[str | None, bool]:
    """(sha, is_deploy). A real opti deploy sets GIT_SHA via the Dockerfile build arg.
    Otherwise, derive the checked-out commit for a local dev run - "local build" with
    no SHA at all should only mean literally no git info was available (e.g. a source
    tarball with no .git), not just "not built by the Deploy workflow"."""
    env_sha = os.environ.get("GIT_SHA")
    if env_sha:
        return env_sha, True
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR,
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip(), False
    except (OSError, subprocess.SubprocessError):
        pass
    return None, False


GIT_SHA, GIT_SHA_IS_DEPLOY = _resolve_git_sha()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def _money(value: Any) -> str:
    # "-" rather than an em dash. The escaped \u2014 form hid this from the dash
    # purge's grep, and this is the widest emitter of the three: every {{ x|money }}
    # with no value went through here, so the board showed a different placeholder
    # depending on which template rendered it.
    if value is None or value == "":
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"${number:,.0f}" if float(number).is_integer() else f"${number:,.2f}"


def _short_time(value: Any) -> str:
    if not value:
        return "never"
    return str(value)[:16].replace("T", " ")


templates.env.filters["money"] = _money
templates.env.filters["dt"] = _short_time



def jsonable(value: Any) -> Any:
    """Strip the internal Delivered objects and rank tuples out of API payloads."""
    if isinstance(value, dict):
        return {
            k: jsonable(v)
            for k, v in value.items()
            if k not in {"delivered", "rank", "best_listing"}
        }
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, pricing.Delivered):
        return {"value": value.value, "resolved": value.resolved}
    return value


# ------------------------------------------------------------------------------ HTML


@app.get("/", response_class=HTMLResponse)
def board(request: Request, sort: str = "delivered", status: str = "ACTIVE") -> Any:
    with session() as conn:
        products = store.list_products(
            conn, status=None if status == "ALL" else status, exclude_grouped=True
        )
        for product in products:
            product["listings"] = store.listings_for_product(conn, product, sort=sort)
        # Groups aren't ACTIVE/PURCHASED/PARKED themselves - they're a comparison of
        # products that mostly are. Shown on the ACTIVE and ALL tabs, where "still
        # deciding between candidates" actually belongs; not on PURCHASED/PARKED.
        groups = store.list_groups(conn) if status in ("ACTIVE", "ALL") else []
        counts = store.status_counts(conn)
        retailer_list = store.list_retailers(conn)
        # Whether the board is empty for THIS tab (nothing PARKED, say) is not the same
        # question as whether this is a brand-new install with nothing in it at all -
        # the onboarding panel belongs only to the second case, regardless of which tab
        # happens to be selected when someone lands here with an empty database.
        is_new_install = counts.get("ALL", 0) == 0 and not conn.execute(
            "SELECT 1 FROM watch_groups LIMIT 1"
        ).fetchone()
    return templates.TemplateResponse(
        request,
        "board.html",
        {
            "products": products,
            "groups": groups,
            "retailers": retailer_list,
            "sort": sort,
            "status": status,
            "counts": counts,
            "is_new_install": bool(is_new_install),
            "statuses": store.STATUSES,
            "config": load_config(),
            "classes": pricing.CLASS_LABELS,
            "version": ASSET_VERSION,
            "app_version": __version__,
            "git_sha": GIT_SHA,
            "git_sha_is_deploy": GIT_SHA_IS_DEPLOY,
        },
    )


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_page(request: Request, product_id: int, sort: str = "delivered") -> Any:
    with session() as conn:
        product = store.product_view(conn, product_id, sort=sort)
        if product is None:
            raise HTTPException(404, "no such product")
        retailer_list = store.list_retailers(conn)
        history = store.price_history(conn, product_id, limit=200)
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM alert_rules WHERE product_id = ?", (product_id,))]
        cats = store.categories(conn)
    return templates.TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "retailers": retailer_list,
            "history": history,
            "rules": rules,
            "categories": cats,
            "sort": sort,
            "classes": pricing.CLASS_LABELS,
            "conditions": pricing.CONDITIONS,
            "verdicts": store.VERDICTS,
            "statuses": store.STATUSES,
            "aspects": provenance.VERIFICATION_ASPECTS,
            "tracked_fields": provenance.TRACKED_FIELDS,
            "config": load_config(),
            "version": ASSET_VERSION,
            "app_version": __version__,
            "git_sha": GIT_SHA,
            "git_sha_is_deploy": GIT_SHA_IS_DEPLOY,
        },
    )


@app.get("/groups/{group_id}", response_class=HTMLResponse)
def group_page(request: Request, group_id: int, sort: str = "delivered") -> Any:
    with session() as conn:
        group = store.group_view(conn, group_id, sort=sort)
        if group is None:
            raise HTTPException(404, "no such group")
        retailer_list = store.list_retailers(conn)
    return templates.TemplateResponse(
        request,
        "group.html",
        {
            "group": group,
            "retailers": retailer_list,
            "sort": sort,
            "classes": pricing.CLASS_LABELS,
            "config": load_config(),
            "version": ASSET_VERSION,
            "app_version": __version__,
            "git_sha": GIT_SHA,
            "git_sha_is_deploy": GIT_SHA_IS_DEPLOY,
        },
    )


# ------------------------------------------------------------------------------- API


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    with session() as conn:
        products = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    return {"status": "ok", "version": __version__, "products": products, "at": utcnow()}


@app.get("/tools/llm-helper.py")
def download_llm_helper() -> Any:
    """Serves the one canonical copy of the LLM helper script (tools/llm-helper.py,
    same file this repo tests and documents) so "Set up your LLM" can offer a direct
    download instead of sending someone to clone the whole repo for one file."""
    path = BASE_DIR.parent / "tools" / "llm-helper.py"
    return FileResponse(path, media_type="text/x-python", filename="llm-helper.py")


#: Every launcher gets this one placeholder replaced with the real shopwatch URL, so
#: nobody downloading the bundle has to type or edit a command themselves - the whole
#: point of the bundle over the plain script.
LLM_HELPER_URL_PLACEHOLDER = "__SHOPWATCH_URL__"


def build_llm_helper_zip(base_url: str) -> bytes:
    """Builds the "just double-click it" bundle in memory: the one canonical
    llm-helper.py plus a README and a launcher per OS/backend combination, each with
    LLM_HELPER_URL_PLACEHOLDER substituted for the real URL.

    Kept separate from the route so it can be tested without a request object.
    """
    tools_dir = BASE_DIR.parent / "tools"
    bundle_dir = tools_dir / "llm-helper-bundle"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("llm-helper.py", (tools_dir / "llm-helper.py").read_bytes())
        zf.writestr("README.txt", (bundle_dir / "README.txt").read_bytes())
        for launcher in sorted(bundle_dir.glob("run-*")):
            content = launcher.read_text().replace(LLM_HELPER_URL_PLACEHOLDER, base_url)
            info = zipfile.ZipInfo(launcher.name)
            # rwxr-xr-x: Windows ignores unix permission bits on extraction, but a
            # .command/.sh launcher that lands non-executable on Mac/Linux is just a
            # text file to double-click - the entire point of the bundle would be lost.
            info.external_attr = 0o100755 << 16
            zf.writestr(info, content)
    return buf.getvalue()


@app.get("/tools/llm-helper.zip")
def download_llm_helper_zip(request: Request, url: str | None = Query(None)) -> Any:
    """The friendlier download: a zip with double-click launchers per OS and backend,
    so using this feature never requires typing a command. `url` is normally supplied
    by the "Set up your LLM" modal's own JS (window.location.origin, the same value it
    already shows in the plain-script command) - a direct request with no `url` falls
    back to the request's own host, which will be wrong if this is genuinely proxied
    without forwarded-host handling, but is still a reasonable default rather than a
    hard failure.
    """
    base_url = (url or str(request.base_url)).rstrip("/")
    zip_bytes = build_llm_helper_zip(base_url)
    return Response(
        content=zip_bytes, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="shopwatch-llm-helper.zip"'},
    )


@app.get("/api/products")
def api_products(include_archived: bool = False, status: str | None = None) -> Any:
    with session() as conn:
        return jsonable(store.list_products(conn, include_archived, status))


@app.get("/api/products/check-model")
def api_check_model(model: str = Query(...)) -> Any:
    """Deterministic model-confirmation check for the wizard.

    Free and instant: catches a typo'd duplicate before the wizard ever reaches its
    costed research step. Says nothing about whether the model NUMBER ITSELF is a real,
    correct SKU - only whether shopwatch already has a product matching it once
    punctuation and case are normalised (store.normalise_model).
    """
    with session() as conn:
        existing = store.product_by_model(conn, model)
    return {
        "normalised": store.normalise_model(model),
        "duplicate_of": (
            {"id": existing["id"], "name": existing["name"], "model": existing["model"]}
            if existing else None
        ),
    }


@app.get("/api/products/{product_id}/price-suggestion")
def api_price_suggestion(product_id: int) -> Any:
    """"Work it out for me": a same-day suggestion from whatever real listings exist.

    Returns null below pricing.suggest_price_target's floor - "not enough data yet" is
    the honest answer for a brand-new product, not a number from one listing dressed up
    as a target.
    """
    with session() as conn:
        product = store.get_product(conn, product_id)
        if product is None:
            raise HTTPException(404, "no such product")
        listings = store.listings_for_product(conn, dict(product))
    return pricing.suggest_price_target(listings)


# ------------------------------------------------------------------------ watch groups


@app.get("/api/groups")
def api_groups(include_archived: bool = False) -> Any:
    with session() as conn:
        return jsonable(store.list_groups(conn, include_archived))


@app.post("/api/groups", status_code=201)
def api_create_group(payload: dict = Body(...)) -> Any:
    with session() as conn:
        try:
            group_id = store.create_group(conn, payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable(store.group_view(conn, group_id))


@app.get("/api/groups/{group_id}")
def api_group(group_id: int, sort: str = "delivered") -> Any:
    with session() as conn:
        group = store.group_view(conn, group_id, sort=sort)
        if group is None:
            raise HTTPException(404, "no such group")
        return jsonable(group)


@app.patch("/api/groups/{group_id}")
def api_update_group(group_id: int, payload: dict = Body(...)) -> Any:
    with session() as conn:
        if store.get_group(conn, group_id) is None:
            raise HTTPException(404, "no such group")
        store.update_group(conn, group_id, payload)
        return jsonable(store.group_view(conn, group_id))


@app.post("/api/products/{product_id}/group")
def api_set_product_group(product_id: int, payload: dict = Body(...)) -> Any:
    """Attach a product to a group. `{"group_id": 1}` for an existing group, or
    `{"name": "Graphics cards"}` to create a new one and attach in the same call."""
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        group_id = payload.get("group_id")
        if not group_id and payload.get("name"):
            try:
                group_id = store.create_group(
                    conn, {"name": payload["name"], "notes": payload.get("notes")}
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        if not group_id:
            raise HTTPException(400, "group_id or name is required")
        if store.get_group(conn, group_id) is None:
            raise HTTPException(404, "no such group")
        store.set_product_group(conn, product_id, group_id)
        return jsonable(store.product_view(conn, product_id))


@app.delete("/api/products/{product_id}/group")
def api_remove_product_group(product_id: int) -> Any:
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        store.set_product_group(conn, product_id, None)
        return jsonable(store.product_view(conn, product_id))


@app.post("/api/products", status_code=201)
def api_create_product(payload: dict = Body(...)) -> Any:
    with session() as conn:
        try:
            product_id = store.create_product(conn, payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable(store.product_view(conn, product_id))


@app.get("/api/products/{product_id}")
def api_product(product_id: int, sort: str = "delivered") -> Any:
    with session() as conn:
        product = store.product_view(conn, product_id, sort=sort)
        if product is None:
            raise HTTPException(404, "no such product")
        return jsonable(product)


@app.patch("/api/products/{product_id}")
def api_update_product(product_id: int, payload: dict = Body(...)) -> Any:
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        store.update_product(conn, product_id, payload)
        return jsonable(store.product_view(conn, product_id))


@app.delete("/api/products/{product_id}")
def api_archive_product(product_id: int) -> Any:
    """Archive, never delete: the price history is the point of the exercise."""
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        store.update_product(conn, product_id, {"archived": 1})
    return {"archived": product_id}


@app.post("/api/products/{product_id}/purchase", status_code=201)
def api_record_purchase(product_id: int, payload: dict = Body(...)) -> Any:
    """Mark a product bought. Moves it to PURCHASED and stops its alerts.

    Set `price_protection_until` (YYYY-MM-DD) to keep watching inside a retailer's price
    guarantee window; leave it off and the watch stops for this product entirely.
    """
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        try:
            purchase = store.record_purchase(conn, product_id, payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"purchase": purchase, "product": jsonable(store.product_view(conn, product_id))}


@app.delete("/api/products/{product_id}/purchase")
def api_undo_purchase(product_id: int) -> Any:
    """Undo a purchase record. The price-history row it created is kept."""
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        if not store.undo_purchase(conn, product_id):
            raise HTTPException(404, "no purchase recorded for this product")
        return {"product": jsonable(store.product_view(conn, product_id))}


@app.get("/api/purchases")
def api_purchases() -> Any:
    with session() as conn:
        rows = conn.execute(
            "SELECT pu.*, p.name AS product_name, p.model FROM purchases pu"
            " JOIN products p ON p.id = pu.product_id"
            " ORDER BY pu.purchased_at DESC, pu.id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/products/{product_id}/retailers")
def api_product_retailers(product_id: int, sort: str = "delivered") -> Any:
    with session() as conn:
        product = store.product_view(conn, product_id, sort=sort)
        if product is None:
            raise HTTPException(404, "no such product")
        return jsonable(product["listings"])


@app.post("/api/products/{product_id}/retailers", status_code=201)
def api_create_listing(product_id: int, payload: dict = Body(...)) -> Any:
    name = (payload.get("retailer") or "").strip()
    if not name:
        raise HTTPException(400, "retailer name is required")
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        retailer = store.ensure_retailer(conn, name)
        listing_id = store.create_listing(
            conn,
            {
                "product_id": product_id,
                "retailer_id": retailer["id"],
                "url": payload.get("url"),
                "condition": (payload.get("condition") or "NEW").upper(),
            },
        )
        values = {k: v for k, v in payload.items() if k in provenance.TRACKED_FIELDS}
        if values:
            provenance.apply_values(
                conn, listing_id, values, state=provenance.MANUAL, source="ui"
            )
            store.record_observation(conn, listing_id, source="ui")
        provenance.sync_verification_from_provenance(conn, listing_id)
        row = conn.execute(
            "SELECT l.*, r.name AS retailer_name, r.slug AS retailer_slug,"
            " r.adapter AS retailer_adapter FROM listings l"
            " JOIN retailers r ON r.id = l.retailer_id WHERE l.id = ?",
            (listing_id,),
        ).fetchone()
        product = store.get_product(conn, product_id)
        return jsonable(
            store.enrich_listing(conn, row, dict(product), load_config().unresolved_freight_penalty)
        )


@app.patch("/api/retailers/{listing_id}")
def api_update_listing(listing_id: int, payload: dict = Body(...)) -> Any:
    """Inline edit. Fields written here are MANUAL and locked by default.

    Pass `"manual": false` to record a value without locking it (useful for bulk imports
    made through this endpoint).
    """
    manual = payload.pop("manual", True)
    source = payload.pop("source", "ui")
    record = payload.pop("record_history", True)
    values = {k: v for k, v in payload.items() if k in provenance.TRACKED_FIELDS}
    unknown = [k for k in payload if k not in provenance.TRACKED_FIELDS]
    if not values:
        raise HTTPException(400, f"no editable fields in payload; unknown keys: {unknown}")

    with session() as conn:
        row = conn.execute(
            "SELECT l.*, r.name AS retailer_name, r.slug AS retailer_slug,"
            " r.adapter AS retailer_adapter FROM listings l"
            " JOIN retailers r ON r.id = l.retailer_id WHERE l.id = ?",
            (listing_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "no such listing")
        try:
            applied = provenance.apply_values(
                conn,
                listing_id,
                values,
                state=provenance.MANUAL if manual else provenance.IMPORTED,
                source=source,
            )
        except provenance.FieldError as exc:
            raise HTTPException(400, str(exc)) from exc
        conn.execute(
            "UPDATE listings SET last_checked_at = ?, updated_at = ? WHERE id = ?",
            (utcnow(), utcnow(), listing_id),
        )
        provenance.sync_verification_from_provenance(conn, listing_id)
        if record:
            store.record_observation(conn, listing_id, source=source)
        product = store.get_product(conn, row["product_id"])
        fresh = conn.execute(
            "SELECT l.*, r.name AS retailer_name, r.slug AS retailer_slug,"
            " r.adapter AS retailer_adapter FROM listings l"
            " JOIN retailers r ON r.id = l.retailer_id WHERE l.id = ?",
            (listing_id,),
        ).fetchone()
        listing = store.enrich_listing(
            conn, fresh, dict(product), load_config().unresolved_freight_penalty
        )
        # The page leads with a sentence answering "should I buy this yet". Editing a
        # freight figure can change that answer, so the summary has to come back with
        # the row or the headline goes stale while the row under it says otherwise.
        return {
            "listing": jsonable(listing),
            "applied": applied,
            "product": product_summary(conn, row["product_id"]),
        }


def product_summary(conn, product_id: int) -> dict[str, Any] | None:
    """Just the headline parts of a product view: the verdict, the scale, the best price.

    Excludes the listings, which the caller already has and which would double the
    payload of every inline edit.
    """
    view = store.product_view(conn, product_id)
    if view is None:
        return None
    return {
        "id": view["id"],
        "tone": view["tone"],
        "verdict_line": view["verdict_line"],
        "scale": view["scale"],
        "best_delivered": view["best_delivered"],
        "best_retailer": view["best_retailer"],
        "best_resolved": view["best_resolved"],
        "best_classification": view["best_classification"],
    }


def _listing_view(conn, listing_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT l.*, r.name AS retailer_name, r.slug AS retailer_slug,"
        " r.adapter AS retailer_adapter FROM listings l"
        " JOIN retailers r ON r.id = l.retailer_id WHERE l.id = ?",
        (listing_id,),
    ).fetchone()
    if row is None:
        return None
    product = store.get_product(conn, row["product_id"])
    return store.enrich_listing(
        conn, row, dict(product), load_config().unresolved_freight_penalty
    )


@app.get("/api/retailers/{listing_id}")
def api_listing(listing_id: int) -> Any:
    with session() as conn:
        listing = _listing_view(conn, listing_id)
        if listing is None:
            raise HTTPException(404, "no such listing")
        return jsonable(listing)


@app.post("/api/retailers/{listing_id}/clear-override")
def api_clear_override(listing_id: int, payload: dict = Body(...)) -> Any:
    field = payload.get("field")
    with session() as conn:
        if conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone() is None:
            raise HTTPException(404, "no such listing")
        try:
            if field in (None, "*", "all"):
                for locked in provenance.locked_fields(conn, listing_id):
                    provenance.clear_override(conn, listing_id, locked)
                cleared = "all"
            else:
                provenance.clear_override(conn, listing_id, field)
                cleared = field
        except provenance.FieldError as exc:
            raise HTTPException(400, str(exc)) from exc
        provenance.sync_verification_from_provenance(conn, listing_id)
        listing = _listing_view(conn, listing_id)
        summary = product_summary(conn, listing["product_id"]) if listing else None
    return {
        "listing_id": listing_id,
        "cleared": cleared,
        "listing": jsonable(listing),
        "product": summary,
    }


@app.post("/api/retailers/{listing_id}/verification")
def api_set_verification(listing_id: int, payload: dict = Body(...)) -> Any:
    aspect = payload.get("aspect")
    status = (payload.get("status") or "").upper()
    with session() as conn:
        if conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone() is None:
            raise HTTPException(404, "no such listing")
        try:
            provenance.set_verification(conn, listing_id, aspect, status, payload.get("note"))
        except provenance.FieldError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "listing_id": listing_id,
            "verification": provenance.verification_map(conn, listing_id),
        }


@app.post("/api/retailers/{listing_id}/ruled-out")
def api_set_ruled_out(listing_id: int, payload: dict = Body(...)) -> Any:
    """Rule a listing out, or put it back in the running.

    Distinct from deactivating it. Deactivating means "this is not a real listing";
    ruling out means "this is real and I will not buy it", which the board still has to
    show you, and still has to exclude from the answer.
    """
    ruled_out = bool(payload.get("ruled_out", True))
    reason = (payload.get("reason") or "").strip() or None
    with session() as conn:
        if conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone() is None:
            raise HTTPException(404, "no such listing")
        if ruled_out:
            conn.execute(
                "UPDATE listings SET ruled_out = 1, ruled_out_reason = ?, ruled_out_at = ?,"
                " updated_at = ? WHERE id = ?",
                (reason, utcnow(), utcnow(), listing_id),
            )
        else:
            # Clear the flag, KEEP the reason and the date. The migration promised the
            # reason travels with the listing, and nulling it here meant un-ruling and
            # re-ruling silently destroyed the original reasoning with nothing recording
            # that it had existed. Putting something back in the running does not unmake
            # the decision to take it out, and next time you wonder why, that is the
            # answer you want.
            conn.execute(
                "UPDATE listings SET ruled_out = 0, updated_at = ? WHERE id = ?",
                (utcnow(), listing_id),
            )
        row = conn.execute(
            "SELECT ruled_out, ruled_out_reason, ruled_out_at FROM listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
    return {
        "listing_id": listing_id,
        "ruled_out": bool(row["ruled_out"]),
        "reason": row["ruled_out_reason"],
        "at": row["ruled_out_at"],
    }


@app.delete("/api/retailers/{listing_id}")
def api_deactivate_listing(listing_id: int) -> Any:
    with session() as conn:
        if conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone() is None:
            raise HTTPException(404, "no such listing")
        conn.execute(
            "UPDATE listings SET active = 0, updated_at = ? WHERE id = ?", (utcnow(), listing_id)
        )
    return {"deactivated": listing_id}


@app.get("/api/offers")
def api_offers(live: bool = True, matched: bool = False) -> Any:
    """Offers seen in retailer email. A lead, never a price."""
    with session() as conn:
        return offers.list_offers(conn, only_live=live, only_matched=matched)


@app.post("/api/offers")
def api_record_offer(payload: dict = Body(...)) -> Any:
    """Record an offer from outside the mail watcher (another machine, or by hand)."""
    if not payload.get("message_id"):
        raise HTTPException(400, "message_id is required; it is the dedupe key")
    with session() as conn:
        recorded = offers.record_offer(conn, payload)
        if recorded is None:
            return {"status": "already seen", "message_id": payload["message_id"]}
        return {"status": "recorded", "offer": recorded}


@app.post("/api/offers/{offer_id}/status")
def api_offer_status(offer_id: int, payload: dict = Body(...)) -> Any:
    status = (payload.get("status") or "").upper()
    if status not in {"NEW", "ACTED", "DISMISSED"}:
        raise HTTPException(400, "status must be NEW, ACTED or DISMISSED")
    with session() as conn:
        if conn.execute("SELECT 1 FROM offers WHERE id = ?", (offer_id,)).fetchone() is None:
            raise HTTPException(404, "no such offer")
        conn.execute("UPDATE offers SET status = ? WHERE id = ?", (status, offer_id))
        return offers.offer_view(conn, offer_id)


@app.get("/api/price-history/{product_id}")
def api_price_history(product_id: int, limit: int = Query(500, le=5000)) -> Any:
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        return store.price_history(conn, product_id, limit)


@app.post("/api/price-watch/run")
def api_price_watch(payload: dict = Body(default={})) -> Any:
    summary = price_watch.run(
        product_id=payload.get("product_id"),
        trigger=payload.get("trigger", "api"),
        send_alerts=payload.get("send_alerts", True),
    )
    return jsonable(summary)


@app.get("/api/price-watch/runs")
def api_price_watch_runs(limit: int = 20) -> Any:
    with session() as conn:
        runs = [dict(r) for r in conn.execute(
            "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT ?", (limit,))]
        for run in runs:
            run["results"] = [dict(r) for r in conn.execute(
                "SELECT sr.*, r.name AS retailer_name FROM scrape_results sr"
                " LEFT JOIN listings l ON l.id = sr.listing_id"
                " LEFT JOIN retailers r ON r.id = l.retailer_id"
                " WHERE sr.run_id = ? ORDER BY sr.id", (run["id"],))]
    return runs


# --------------------------------------------------------------- research jobs (wizard)
#
# Deliberately its own resource, not folded into /api/price-watch: that pair means a
# synchronous adapter scrape that always completes before the request returns. A
# research job is asynchronous, Claude-driven, and can take real minutes - conflating
# the two "a run happened" concepts under one prefix would cost every future reader.


@app.post("/api/research-jobs", status_code=202)
def api_create_research_job(payload: dict = Body(...)) -> Any:
    product_id = payload.get("product_id")
    retailer_ids = payload.get("retailer_ids") or []
    if not product_id:
        raise HTTPException(400, "product_id is required")
    with session() as conn:
        if store.get_product(conn, product_id) is None:
            raise HTTPException(404, "no such product")
        try:
            job_id = research.create_job(conn, product_id, retailer_ids)
        except research.JobAlreadyRunning as exc:
            raise HTTPException(
                409, f"a research job is already active for this product: job {exc.job_id}"
            ) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable(research.get_job(conn, job_id))


@app.get("/api/research-jobs/{job_id}")
def api_get_research_job(job_id: int) -> Any:
    with session() as conn:
        job = research.get_job(conn, job_id)
        if job is None:
            raise HTTPException(404, "no such research job")
        return jsonable(job)


@app.post("/api/research-jobs/claim")
def api_claim_research_job() -> Any:
    """Called only by the host-level research runner, never by the wizard UI.

    Atomically claims the oldest QUEUED job. Returns null when there is nothing to do -
    the runner is expected to poll this on its own interval, the same shape mailwatch
    already uses for its own host-side polling.
    """
    with session() as conn:
        job = research.claim_next_queued(conn)
        return jsonable(job)


@app.post("/api/research-jobs/{job_id}/results")
def api_report_research_result(job_id: int, payload: dict = Body(...)) -> Any:
    """Called only by the host-level research runner, one call per retailer outcome."""
    retailer_id = payload.get("retailer_id")
    status = payload.get("status")
    if not retailer_id or not status:
        raise HTTPException(400, "retailer_id and status are required")
    with session() as conn:
        if research.get_job(conn, job_id) is None:
            raise HTTPException(404, "no such research job")
        try:
            research.report_result(
                conn, job_id, retailer_id, status,
                listing_id=payload.get("listing_id"), note=payload.get("note"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable(research.get_job(conn, job_id))


@app.post("/api/research-jobs/{job_id}/complete")
def api_complete_research_job(job_id: int, payload: dict = Body(...)) -> Any:
    """Called only by the host-level research runner, exactly once per job."""
    status = payload.get("status")
    with session() as conn:
        if research.get_job(conn, job_id) is None:
            raise HTTPException(404, "no such research job")
        try:
            research.complete_job(conn, job_id, status, error=payload.get("error"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable(research.get_job(conn, job_id))


# ------------------------------------------------------------------- llm jobs (wizard)
#
# Same job-lifecycle shape as research jobs above, claimed by a completely different
# kind of runner: not a fixed host script on opti, but tools/llm-helper.py running on
# WHOEVER's own machine, using their own already-authenticated Claude Code or Codex CLI.
# This server never holds that credential and never needs one of its own.


@app.post("/api/llm-jobs", status_code=202)
def api_create_llm_job(payload: dict = Body(...)) -> Any:
    query = payload.get("query")
    with session() as conn:
        try:
            job_id = llm_jobs.create_job(conn, query)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable(llm_jobs.get_job(conn, job_id))


@app.get("/api/llm-jobs/{job_id}")
def api_get_llm_job(job_id: int) -> Any:
    with session() as conn:
        job = llm_jobs.get_job(conn, job_id)
        if job is None:
            raise HTTPException(404, "no such llm job")
        return jsonable(job)


@app.post("/api/llm-jobs/claim")
def api_claim_llm_job() -> Any:
    """Called only by a user's own tools/llm-helper.py, never by the wizard UI.

    Atomically claims the oldest QUEUED job. Returns null when there is nothing to do -
    the runner is expected to poll this on its own short interval while it is running.
    """
    with session() as conn:
        return jsonable(llm_jobs.claim_next_queued(conn))


@app.post("/api/llm-jobs/{job_id}/complete")
def api_complete_llm_job(job_id: int, payload: dict = Body(...)) -> Any:
    """Called only by tools/llm-helper.py, exactly once per job."""
    status = payload.get("status")
    with session() as conn:
        if llm_jobs.get_job(conn, job_id) is None:
            raise HTTPException(404, "no such llm job")
        try:
            llm_jobs.complete_job(
                conn, job_id, status,
                result=payload.get("result"), error=payload.get("error"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable(llm_jobs.get_job(conn, job_id))


@app.post("/api/alerts/evaluate")
def api_evaluate_alerts(payload: dict = Body(default={})) -> Any:
    """Dry run of the alert rules: what would fire right now, without sending anything."""
    with session() as conn:
        raised = alerts.evaluate_all(conn)
    return {"alerts": [a.to_dict() for a in raised]}


@app.post("/api/import")
def api_import(payload: Any = Body(...)) -> Any:
    """Accepts a single finding, a list of findings, or a full snapshot."""
    with session() as conn:
        if isinstance(payload, dict) and payload.get("format") == "shopwatch-snapshot":
            return ingest.import_snapshot(conn, payload)
        if isinstance(payload, dict) and "findings" in payload:
            return ingest.import_findings(
                conn,
                payload["findings"],
                source=payload.get("source"),
                create_missing_product=bool(payload.get("create_missing_product")),
            )
        findings = payload if isinstance(payload, list) else [payload]
        return ingest.import_findings(conn, findings)


@app.get("/api/export")
def api_export(history: bool = True) -> Any:
    with session() as conn:
        return JSONResponse(
            ingest.export_all(conn, include_history=history),
            headers={"Content-Disposition": 'attachment; filename="shopwatch-export.json"'},
        )


@app.get("/api/export.csv", response_class=PlainTextResponse)
def api_export_csv() -> Any:
    with session() as conn:
        return PlainTextResponse(
            ingest.csv_export(conn),
            headers={"Content-Disposition": 'attachment; filename="shopwatch.csv"'},
        )


@app.post("/api/backup")
def api_backup() -> Any:
    path = backup()
    return {"backup": str(path), "at": utcnow()}


@app.post("/api/retailers", status_code=201)
def api_create_retailer(payload: dict = Body(...)) -> Any:
    """Ensure a retailer exists with no listing attached yet.

    For the wizard: a retailer chosen for research doesn't have a price yet, so there is
    nothing to hang a listing off. store.ensure_retailer already makes this idempotent -
    naming an existing retailer just returns it.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    with session() as conn:
        row = dict(store.ensure_retailer(conn, name))
    row["adapter_available"] = row["adapter"] in retailers.available_adapters()
    return row


@app.get("/api/retailers")
def api_retailers() -> Any:
    """One place to read everything shopwatch knows about a retailer's automatability.

    Each fact still comes from its own authoritative source (the adapter registry for
    scraping, mailwatch's own domain map for mail alerts) rather than a hand-maintained
    copy in the database, so nothing here can drift out of sync with the code that
    actually does the work. This endpoint just merges them for a caller (the product
    wizard) that needs all three in one read.
    """
    with session() as conn:
        rows = store.list_retailers(conn)
    adapters = retailers.available_adapters()
    mail_parsed = mailwatch.mail_alert_retailers()
    for row in rows:
        cls = adapters.get(row["adapter"] or "")
        row["adapter_available"] = cls is not None
        row["never_scrapable"] = list(cls.never_scrapable) if cls else []
        row["mail_alerts_parsed"] = row["name"] in mail_parsed
    return rows


@app.get("/api/meta")
def api_meta() -> Any:
    with session() as conn:
        cats = store.categories(conn)
    return {
        "version": __version__,
        "conditions": pricing.CONDITIONS,
        "verdicts": store.VERDICTS,
        "statuses": store.STATUSES,
        "classifications": pricing.CLASS_LABELS,
        "provenance_states": provenance.STATES,
        "verification_aspects": provenance.VERIFICATION_ASPECTS,
        "tracked_fields": provenance.TRACKED_FIELDS,
        "categories": cats,
        "adapters": sorted(retailers.available_adapters()),
        "unresolved_freight_penalty": load_config().unresolved_freight_penalty,
    }


@app.get("/api/categories/{category}/fields")
def api_category_fields(category: str) -> Any:
    with session() as conn:
        return store.category_fields(conn, category)


@app.post("/api/categories/{category}/fields", status_code=201)
def api_add_category_field(category: str, payload: dict = Body(...)) -> Any:
    with session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO category_specifications"
            " (category, field_key, label, kind, options, sort) VALUES (?, ?, ?, ?, ?, ?)",
            (
                category, payload.get("field_key"), payload.get("label"),
                payload.get("kind", "text"),
                json.dumps(payload["options"]) if payload.get("options") else None,
                payload.get("sort", 0),
            ),
        )
        return store.category_fields(conn, category)
