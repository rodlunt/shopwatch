# Shopwatch

A self-hosted shopping comparison and price-watch board for a homelab. One product, many
retailer listings, ranked by **delivered price** rather than headline price, with per-field
provenance so hand-confirmed values are never clobbered by an automated refresh.

Built to replace a single-file HTML comparison board. It is a research tool, not a shop.

---

## What it actually does

* **A product exists once.** `Samsung Q-Series 9.1.4ch Soundbar`, model `HW-Q930H/XY`, with
  a listing under each of Crowdshop, Harvey Norman, JB Hi-Fi, The Good Guys, Appliance
  Central, and anyone else found later.
* **Delivered price is the ranking metric.**
  `advertised + freight - cashback - rebate - coupon`.
* **Unresolved freight is unresolved, never free.** A NULL freight yields a *provisional*
  delivered price, marked `PROV`, classified `UNRESOLVED`, and ranked with a configurable
  penalty (default $60) so it cannot silently outrank a slightly dearer listing whose
  delivered price is confirmed.
* **Provenance is per field, not per listing.** Every editable field carries a state
  (`LIVE`, `MANUAL`, `IMPORTED`, `UNVERIFIED`, `STALE`), a source, a timestamp, and a
  manual lock. A locked field survives every scrape and every import until you clear it.
* **Verification is tracked per aspect** (model, price, stock, freight, condition,
  warranty, contents), not as one vague boolean.
* **History is append-only.** Prices are never deleted because the market moved. The
  recorded historical low is lowered automatically by a confirmed better price and is
  never raised automatically.

### Price classification

Thresholds are inclusive, evaluated best first, and expressed as delivered prices:

| Label | Condition |
|---|---|
| `HISTORICAL LOW TERRITORY` | delivered ≤ `historical_low_price` |
| `EXCELLENT` | delivered ≤ `excellent_price` |
| `TRIGGER MET` | delivered ≤ `trigger_price` |
| `ABOVE TARGET` | above the trigger |
| `UNRESOLVED` | no price, or freight unconfirmed on a listing that would otherwise rate |

An unresolved listing that is *above* target still reads `ABOVE TARGET`, because freight
can only make it worse.

---

## Architecture

```
app/
  main.py            FastAPI: HTML board + JSON API
  config.py          environment-driven configuration
  db.py              SQLite connect/migrate/backup/restore (WAL)
  migrations/*.sql   forward-only, applied in filename order, never destructive
  pricing.py         delivered price, classification, ranking
  provenance.py      per-field state and manual locks: the single write path
  store.py           queries and view assembly
  ingest.py          findings import, snapshot import/export, CSV export
  price_watch.py     the watcher (CLI / cron / API)
  alerts.py          rule evaluation, ntfy / webhook / console delivery
  seed.py            category profiles, retailers, HW-Q930H/XY board
  retailers/
    base.py          adapter framework, JSON-LD reader, Observation
    crowdshop.py  harvey_norman.py  jb_hifi.py  the_good_guys.py  appliance_central.py
  templates/  static/
tests/
```

Stack: Python 3.12, FastAPI, Jinja2, vanilla JavaScript, stdlib `sqlite3`. No ORM, no
build step, no cloud dependency.

---

## Deploy with Docker

```bash
cd ~/Projects/shopwatch
cp .env.example .env          # edit ntfy URL etc.
docker compose up -d --build
docker compose logs -f shopwatch
```

Then open `http://SERVER-IP:8477/`.

Day-to-day:

```bash
docker compose ps                                  # status and health
docker compose restart shopwatch
docker compose down                                # stop (the volume survives)
docker compose up -d --build                       # after a code change
docker compose exec shopwatch python -m app.price_watch          # manual watch run
docker compose exec shopwatch python -m app.seed                 # idempotent re-seed
docker compose exec shopwatch python -c "from app.db import backup; print(backup())"
```

### Changing the port

`SHOPWATCH_PORT` in `.env` sets both the published port and the port uvicorn binds inside
the container, so one variable moves both. To publish on a different LAN port from the
container port, edit the `ports:` line in `docker-compose.yml` to `"9000:8477"`.

### Where the data lives

The named volume `shopwatch-data` is mounted at `/data`, with the database at
`/data/shopwatch.db`. Find it on disk with:

```bash
docker volume inspect shopwatch_shopwatch-data --format '{{ .Mountpoint }}'
```

Running outside Docker, the default is `data/shopwatch.db` relative to the working
directory; override with `SHOPWATCH_DB`.

### Backup

```bash
# writes /data/backups/shopwatch-YYYYmmdd-HHMMSS.db using SQLite's online backup API,
# which is consistent while the app is running
docker compose exec shopwatch python -c "from app.db import backup; print(backup())"

# or over HTTP
curl -X POST http://SERVER-IP:8477/api/backup

# and pull a copy out of the volume
docker compose cp shopwatch:/data/backups ./backups
```

A JSON export (`GET /api/export`) is the portable alternative and survives schema changes,
where a `.db` copy is exact but version-tied. Take both.

### Restore

Restore is an **offline** operation. SQLite will not notice the file changing underneath an
open connection.

```bash
docker compose stop shopwatch
docker compose cp ./backups/shopwatch-20260911-090000.db shopwatch:/data/restore.db
docker compose start shopwatch
docker compose exec shopwatch python -c \
  "from app.db import restore; print(restore('/data/restore.db'))"
docker compose restart shopwatch
```

`restore()` keeps the database it replaced as `shopwatch.replaced-<timestamp>.db` next to
the live file, and removes the stale `-wal`/`-shm` pair.

---

## Running without Docker

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m app.seed
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8477
```

---

## The price watch

```bash
python -m app.price_watch                 # everything
python -m app.price_watch --product 1     # one product
python -m app.price_watch --no-alerts     # check prices, send nothing
python -m app.price_watch --json          # machine-readable summary
curl -X POST http://SERVER-IP:8477/api/price-watch/run -d '{}' \
     -H 'Content-Type: application/json'
```

Each run: fetches every active listing that has both an adapter and a URL, verifies the
model, writes the fields that are not manually locked, appends a history observation,
downgrades fields that have not refreshed inside `SHOPWATCH_STALE_AFTER_DAYS` to `STALE`,
then evaluates the alert rules.

**Exit codes matter.** The command exits non-zero when every attempted check errored, or
when an alert could not be delivered. A run that exits 0 genuinely did something.

### cron

```cron
# /etc/cron.d/shopwatch — twice a day, output captured, failures mailed
MAILTO=you@example.com
17 7,19 * * * root cd /opt/shopwatch && docker compose exec -T shopwatch \
  python -m app.price_watch --trigger cron >> /var/log/shopwatch.log 2>&1
```

Set `MAILTO` or pipe to something that reads the exit code. A cron line that redirects
everything to a logfile nobody reads is how a dead watcher stays dead.

### systemd timer

`/etc/systemd/system/shopwatch-watch.service`:

```ini
[Unit]
Description=Shopwatch price watch
[Service]
Type=oneshot
WorkingDirectory=/opt/shopwatch
ExecStart=/usr/bin/docker compose exec -T shopwatch python -m app.price_watch --trigger cron
# A failed run is visible rather than silent.
OnFailure=status-email@%n.service
```

`/etc/systemd/system/shopwatch-watch.timer`:

```ini
[Unit]
Description=Run the Shopwatch price watch twice a day
[Timer]
OnCalendar=*-*-* 07,19:17:00
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload && systemctl enable --now shopwatch-watch.timer
systemctl list-timers shopwatch-watch.timer     # proves it is scheduled
journalctl -u shopwatch-watch.service -n 50     # proves it ran
```

---

## Alerts (ntfy)

```dotenv
SHOPWATCH_NTFY_URL=https://ntfy.example.com/shopwatch
SHOPWATCH_NTFY_TOKEN=tk_...          # omit for an unauthenticated topic
SHOPWATCH_NTFY_PRIORITY=high
SHOPWATCH_WEBHOOK_URL=               # optional, receives the alert as JSON
SHOPWATCH_ALERTS_ENABLED=true
```

Console output always happens. A delivery failure is printed as `[ALERT-FAILURE]`, logged
at ERROR, returned in the run summary, and makes the CLI exit non-zero. An ntfy 2xx means
ntfy accepted the publish, not that a device displayed it.

Rules live in the `alert_rules` table, one row per rule:

| Column | Meaning |
|---|---|
| `conditions` | comma-separated allowlist, e.g. `NEW` or `FACTORY_SECOND,CARTON_DAMAGED` |
| `max_delivered` | fire at or below this **delivered** price |
| `require_resolved` | ignore listings whose freight is unconfirmed (default on) |
| `require_complete` | ignore listings with no recorded included components |
| `min_change` | suppress a re-alert when the price moved less than this |

The seeded Q930H rules are *new stock ≤ $900 delivered* and *secondary stock ≤ $800
delivered, complete systems only*. `POST /api/alerts/evaluate` is a dry run: it reports
what would fire without sending anything.

---

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/products` | every product with its assembled matrix |
| `POST` | `/api/products` | `{name, model, category, ...}` |
| `GET` | `/api/products/{id}` | `?sort=delivered\|headline\|retailer\|stock\|condition\|verification\|diff` |
| `PATCH` | `/api/products/{id}` | targets, specs, dimensions, verdict |
| `DELETE` | `/api/products/{id}` | archives, never deletes |
| `GET` | `/api/products/{id}/retailers` | the listings |
| `POST` | `/api/products/{id}/retailers` | add a listing |
| `GET` | `/api/retailers/{listing_id}` | one enriched listing |
| `PATCH` | `/api/retailers/{listing_id}` | inline edit; **locks the field as MANUAL** |
| `POST` | `/api/retailers/{listing_id}/clear-override` | `{"field": "freight"}` or `{"field": "all"}` |
| `POST` | `/api/retailers/{listing_id}/verification` | `{"aspect": "freight", "status": "VERIFIED"}` |
| `DELETE` | `/api/retailers/{listing_id}` | deactivates the listing |
| `GET` | `/api/price-history/{product_id}` | observations, newest first |
| `POST` | `/api/price-watch/run` | `{"product_id": 1, "send_alerts": true}` |
| `GET` | `/api/price-watch/runs` | recent runs with per-listing results |
| `POST` | `/api/alerts/evaluate` | dry run |
| `POST` | `/api/import` | findings, a list of findings, or a snapshot |
| `GET` | `/api/export` / `/api/export.csv` | snapshot / flat comparison |
| `POST` | `/api/backup` | server-side database snapshot |
| `GET` | `/api/meta` | enums, categories, adapters |
| `GET` | `/healthz` | touches the database, not just the port |

`PATCH /api/retailers/{id}` accepts `{"manual": false}` to record a value without locking
it, and `{"record_history": false}` to skip the history row.

---

## Importing external research

The import path exists so research done elsewhere can land on the board without hand
retyping. Post one finding, a list of them, or `{"findings": [...], "source": "..."}`:

```json
[{
  "model": "HW-Q930H/XY",
  "retailer": "JB Hi-Fi",
  "price": 1699,
  "freight": null,
  "stock": "Available",
  "condition": "New",
  "warranty": "1 year",
  "source_url": "https://www.jbhifi.com.au/...",
  "checked_at": "2026-09-11T02:00:00Z",
  "verification": {"model": true, "price": true, "stock": true}
}]
```

```bash
curl -X POST http://SERVER-IP:8477/api/import \
     -H 'Content-Type: application/json' --data @findings.json
```

On import the app matches the product by exact model (case and punctuation insensitive,
region suffix significant: `/XY` ≠ `/XU`), matches or creates the retailer, creates the
listing if it is new, writes only the fields that are not manually locked, stores a price
history row, and updates `last_checked_at`. The response lists `updated` and
`preserved_manual` per finding, so you can see exactly what a lock stopped.

An unknown model is rejected rather than guessed at. Pass
`{"findings": [...], "create_missing_product": true}` if you want it created.

`"freight": null` means unresolved. Do not send `0` unless free shipping is confirmed.

---

## Adding a retailer adapter

1. Create `app/retailers/my_retailer.py`:

```python
from .base import Observation, RetailerAdapter, observation_from_json_ld, register

@register
class MyRetailerAdapter(RetailerAdapter):
    slug = "my_retailer"
    name = "My Retailer"
    homepage = "https://example.com"
    # Fields this retailer structurally cannot expose to a scraper.
    never_scrapable = ("freight", "pickup_status")

    def parse(self, html: str, expected_model: str | None = None) -> Observation:
        obs = observation_from_json_ld(html, expected_model)
        # retailer-specific fallbacks here; leave anything you cannot read as None
        return obs
```

2. Import it in `app/retailers/__init__.py` so registration happens.
3. Point the retailer row at it: `UPDATE retailers SET adapter = 'my_retailer' WHERE ...`,
   or set it when the retailer is first created.
4. Add a test with a saved fragment of the real page.

Rules for adapters: return `None` for anything you could not determine, never a plausible
guess and never `0`. Do not defeat CAPTCHAs or anti-bot measures. Keep `never_scrapable`
honest, it is what tells the UI a field is a manual one. If the retailer serves a
challenge page with HTTP 200, add its marker to `BLOCK_MARKERS` in `retailers/base.py`
so the block surfaces as an error rather than as an empty product page.

## Adding a category

Categories are rows, not schema. Either:

```bash
curl -X POST http://SERVER-IP:8477/api/categories/espresso_machine/fields \
  -H 'Content-Type: application/json' \
  -d '{"field_key":"boiler_type","label":"Boiler type","kind":"text","sort":1}'
```

or add an entry to `CATEGORY_PROFILES` in `app/seed.py` and re-run `python -m app.seed`
(idempotent). Product values live in the `specs_json` object, so no migration is needed.
`kind` is one of `text`, `number`, `bool`, `select`.

---

## Tests

```bash
.venv/bin/python -m pytest        # 81 tests
.venv/bin/python -m ruff check .
```

They cover the behaviour that is easy to break quietly: delivered-price arithmetic,
cashback, threshold classification, ranking with unresolved freight, manual-override
preservation through both scrapes and imports, import merge behaviour, model matching,
stale-data handling, adapter normalisation, fetch failures not destroying stored values,
alert suppression on trivial moves, and migration/backup safety.

---

## Retailer scraping limitations

Read this before trusting an empty field.

### What was actually measured

Probed from an Australian residential IP on 2026-09-11 with the adapters' own `fetch()`.
This is a snapshot, not a permanent fact: re-run `python -m app.price_watch --json` and
read `/api/price-watch/runs` rather than trusting this table.

| Retailer | Result | Meaning |
|---|---|---|
| Crowdshop | 200, 273 KB | fetches fine |
| Harvey Norman | 200 carrying an **Imperva/Incapsula challenge** | blocked |
| Appliance Central | **403** | blocked |
| JB Hi-Fi | not established | the URL probed was a guess and 404'd |
| The Good Guys | not established | as above |

**Harvey Norman is the instructive one.** It returns HTTP 200 with a "Pardon Our
Interruption" interstitial, so a naive adapter parses it, finds no price, and reports
`unresolved` — identical to what it reports for a product page that genuinely has no
price. `retailers.base.detect_block()` catches that family of pages and raises
`FetchError` instead, so a block reaches the run as an **error**, which is what it is.
Add a marker there if a new retailer starts doing the same.

### Structural limits, which no amount of scraping fixes

* **Freight is not scrapable at any of the seeded retailers.** Every one quotes delivery
  at checkout against a postcode. Freight is a manual field by design, which is why an
  unresolved freight is ranked with a penalty rather than assumed to be zero.
* **Store pickup is not scrapable** for the same reason: it needs a store selection.
* **Crowdshop quotes a price guide range** on some listings. The low end becomes the
  headline figure and the full range is kept in `price_guide`. Its displayed `$0` delivery
  is not treated as confirmed free shipping.
* **Appliance Central's headline price is pre-coupon.** Record the coupon in
  `coupon_discount`, not by editing the advertised price down, or the history becomes a
  fiction.
* **Search-engine snippets and cached prices are not a source.** The live product page
  wins. The older ~$999 Q930H snippets floating around are stale.
* **A model mismatch flags the listing** (`model: FLAGGED`) rather than updating it
  quietly.
* **Playwright is not used.** If a retailer genuinely needs a headless browser, add it as
  an optional dependency in that adapter alone; the rest of the stack stays on
  `requests` + `BeautifulSoup`.

### Filling a blocked retailer by hand, with a browser

A blocked retailer is filled by a person reading the page in a normal browser and posting
what they saw. Claude-in-Chrome is a convenient way to do that leg, but it is a **manual
research lane, not an adapter**: it needs a live session and a desktop browser, and the
watch runs headless on the server from cron, so it can never be what fills these on a
schedule.

The distinction that matters: a person driving a browser occasionally to read a public
product page is ordinary use. Wiring a *scheduled* job to drive a real browser so it stops
looking like automation is anti-bot evasion, and this project does not do it. That is also
the route that gets an account blocked rather than a price.

The values land through the normal import path, so they are recorded honestly:

```bash
curl -X POST http://SERVER-IP:8477/api/import \
  -H 'Content-Type: application/json' -d '{
    "source": "claude-in-chrome",
    "findings": [{
      "model": "HW-Q930H/XY",
      "retailer": "Harvey Norman",
      "price": 1695,
      "freight": null,
      "stock": "In stock",
      "source_url": "https://www.harveynorman.com.au/...",
      "checked_at": "2026-09-11T12:00:00Z",
      "verification": {"model": true, "price": true}
    }]
  }'
```

That writes state `IMPORTED` with `source = claude-in-chrome`, **not** `LIVE`. The
distinction is the point: `LIVE` means an adapter read the page itself, and a value a
human transcribed should never claim to be that. It also leaves the field unlocked, so if
the retailer ever becomes scrapable the automated run takes it back. Lock it only when the
value is one a scraper could never get right anyway, such as a negotiated price or a
freight figure confirmed at checkout.
