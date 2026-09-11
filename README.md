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

## Where things live

| | |
|---|---|
| Live | https://shop.home.lunt.au (LAN only, `basic_auth`) |
| Code | GitHub `rodlunt/shopwatch` (private) |
| Deploy | push to the `opti` remote; see **Deployed on opti** |
| Secrets | `SECURITY.md` names every lane |
| Tests | `.venv/bin/python -m pytest` and `.venv/bin/python -m ruff check .` |

**Two remotes, on purpose.** `origin` is GitHub and holds the history, issues and CI.
`opti` is a bare repo on the server whose `post-receive` hook rebuilds the container.
Pushing to `opti` deploys; pushing to `origin` does not.

⚠ **CI does not gate the deploy.** The house standard is a `workflow_run` gate so a push
that fails lint or tests can never reach production. That is not possible here while opti
deploys from its own bare repo rather than from GitHub: CI is advisory, and a broken push
to `opti` will deploy. Closing that means making opti pull from GitHub instead, which is
a deliberate change nobody has made yet.

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

## Watching retailer email for offers

**Who actually sends.** JB Hi-Fi (341 messages) and The Good Guys (66) are the bulk.
Harvey Norman was subscribed to on 2026-09-11 and sends from the bare
`harveynorman.com.au`. Appliance Central, Bing Lee and Crowdshop send nothing yet and
sit in the allowlist inert; Appliance Central is worth subscribing to, since they hold
the best confirmed price on the board.

**A run says what it saw at every stage**, because "scanned 0" on its own cannot tell an
empty mailbox from a broken one from a mailbox full of brand noise:

```
looked in: INBOX holds 15
2 retailer email(s) carried no offer:
    Harvey Norman: Please confirm your Harvey Norman account
    Harvey Norman: Welcome to Harvey Norman
scanned 0 (seen before 0), extracted 0, not offers 0, recorded 0, errors 0
```

A sender whose display name is a watched retailer but whose domain is not on the
allowlist is reported too - the shape a campaign sent through a third-party ESP takes,
and otherwise a silent miss forever.


The price scrapers can only see product pages, and the discounts that matter are not on
them. Measured on a real corpus of 204 retailer emails: **not one mentioned a tracked
model**, but 67 carried a quantified offer, and those offers are where the money is -
"Spend $2000 or more on TVs & get $500 OFF" never touches a product page.

Keyword matching is not enough. On that corpus it flagged 44 emails as relevant when a
handful were: a catalogue blast mentions dozens of products and several dollar figures,
and "$400 off" next to the word "TV" somewhere in 6,000 characters means nothing.
Working out what an offer *covers* means reading it, so that step goes to a model with a
fixed output schema.

```bash
python -m app.mailwatch --dry-run          # what it would read; makes no API calls
python -m app.mailwatch                    # extract and post to the board
python -m app.mailwatch --since 2026-09-01 --limit 20
```

### How it is wired

It runs **on opti**, reusing credentials that were already there for the job-search
`/check-seek` pipeline, so nothing new is stored anywhere:

| Needs | Where it already lives | Why |
|---|---|---|
| Mail access | `ICLOUD_EMAIL` / `ICLOUD_APP_PASSWORD` in `/srv/prod/career/runner.env` | Proven: that runner has been polling on it every 15 minutes |
| The model | `CLAUDE_BIN` + `CLAUDE_CODE_OAUTH_TOKEN`, same file | career drives headless Claude Code, so extraction costs nothing beyond the subscription and needs **no `ANTHROPIC_API_KEY`** |

```bash
ssh root@100.115.75.8
set -a; . /srv/prod/career/runner.env; set +a
cd /srv/prod/shopwatch/repo
export PYTHONPATH=$PWD SHOPWATCH_DB=/tmp/mw.db \
       SHOPWATCH_URL="http://$(docker inspect shopwatch --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'):8477"
/srv/prod/shopwatch/mailwatch-venv/bin/python -m app.mailwatch --imap --cli --since 2026-09-01
```

Caddy holds the basic_auth, so on the docker network the app answers directly and the
job needs no password of its own.

Three things learned the hard way against the real account, all of them now in the code:

* **INBOX only, by choice.** `/check-seek` also reads Trash because Seek alerts get
  swiped away before it runs. Deal mail is different: keep what you want watched in the
  inbox and the job stays small. Trawling 4,800 deleted messages every run is work
  nobody asked for and a wider reach into the mailbox than the task needs. For a one-off
  backfill of things already deleted, `ICLOUD_FOLDERS=INBOX,Trash`.
* **Search on the server.** The first live run fetched every message in both folders just
  to read a From header and never finished. One SEARCH per retailer domain, then fetch
  only the matches.
* **Search by token, never by domain.** iCloud will not match a bare domain sitting
  directly after the `@`:

  ```
  FROM "harveynorman.com.au"              -> 0 hits
  FROM "harveynorman"                     -> 2 hits
  FROM "do_not_reply@harveynorman.com.au" -> 2 hits
  ```

  JB Hi-Fi only ever worked by accident, because they send from
  `email.jbhifi.com.au` where the domain follows a dot. Every retailer using their
  bare domain was searched for and never found, with the run reporting a clean zero.
  `SEARCH_TOKENS` is deliberately broader than the allowlist; `retailer_for()` still
  does the precise domain check on the results.
* **A `None` result set is ambiguous on iCloud** - it means both "no matches" and "that
  search was malformed". Each folder now runs a control search that must return
  something before an empty per-domain result is believed to be a real zero.

The local Thunderbird mbox still works (`--dry-run` with no `--imap`) and is the better
source for a one-off backfill of history, since the server copy only holds what has not
been cleared out.

### Reading the artwork

Retailer marketing puts the numbers in pictures, so `--render` (or `SHOPWATCH_RENDER=1`)
adds a second pass: render the email with headless Chrome and read the offer off the
screenshot.

Measured on a live Good Guys email. Extracted text is 4,301 characters containing `20%`
three times and **zero** occurrences of `Ends`, `13/09/2026` or `11.59` - those are
pixels. Side by side:

| | text pass | render pass |
|---|---|---|
| amount | 20 | 20 |
| expires | *nothing* | **2026-09-13** |
| confidence | medium | high |

Without it the board recorded that offer as never expiring, when it actually died two
days later.

It only runs when the text pass comes back **weak** - a real offer with no amount or no
deadline. A complete offer never renders, and a product announcement never renders
however prettily it is drawn, so most mail still costs a single text call. A failed
render degrades to the text answer rather than discarding it.

Chrome runs in a container (`zenika/alpine-chrome`), so nothing is installed on the host
and it can see only the one directory it is handed. The screenshot is deleted as soon as
it has been read.

Two limits, both found by trying:

* **It only works while the offer is live.** The hero images are served from a live URL
  and swapped when the offer ends - an August email now renders as "This offer has
  ended" rather than what it once said. Useless for a backfill, fine for a daily job.
* **It cannot avoid the tracking pixel.** The images carry the offer, so they have to
  load, and loading them tells the retailer the mail was opened. On a schedule, that is
  a slightly different signal from opening it yourself.

There is no text shortcut, either: the "View Online" link was checked and its hosted page
is the same image-based email, 1,427 characters of text with none of the offer in it.

### Clearing the inbox as it goes

`--cleanup` (or `SHOPWATCH_MAIL_CLEANUP=1`) moves messages it has processed to Trash,
the same as swiping them away. It is **off unless asked for**, so a manual run never
touches the mailbox.

Three constraints, all copied from `extract-seek-alerts.py` because the failure modes
are the same:

* **Only processed messages move.** Anything the extractor choked on stays in the inbox.
  That is not politeness, it is the alarm: a broken extractor that binned its own
  evidence would look exactly like a quiet week.
* **INBOX only.** Never Trash, never any other folder.
* **It never expunges.** iCloud purges Trash after 30 days by itself, so an interrupted
  run is always recoverable.

Messages are addressed by UID, not sequence number - sequence numbers shift the instant
a message moves, and a cleanup keyed on them deletes the wrong mail.

### Two rules it will not break

**An offer is a lead, never a price.** Nothing in this path writes to a listing's
advertised price, freight or coupon. It produces a suggestion with the arithmetic done
and says plainly that it has not been applied.

**An offer only discounts the retailer that sent it.** A Good Guys code projected from
Crowdshop's cheaper price produces a number you cannot buy at any counter. If the sending
retailer is not on a product's board there is no match, even though they may well sell
the thing - add their listing and the offer becomes visible.

### Cost

A regex gate runs first, so only emails carrying an actual offer reach the model - 137 of
204 never do. At roughly seven offer-emails a week that is a few dollars a year on
`claude-opus-5`; `--model claude-haiku-4-5` is cheaper again. Extraction runs at effort
`low`, which is the right setting for reading marketing copy.

### When it runs, and why

Once a day at **10:00 Brisbane**, chosen from 383 retailer emails spanning 163 days
rather than picked out of the air.

```
BY HOUR (Brisbane)                    BY DAY
  06:00    4  #                         Mon   45  ###########################
  07:00   24  #####                     Tue   44  ###########################
  08:00  202  ####################      Wed   44  ###########################
  09:00   44  ##########                Thu   71  ###########################################
  10:00   14  ###                       Fri   73  ############################################
  12:00   18  ####                      Sat   67  ########################################
  17:00   12  ###                       Sun   39  ########################
  20:00   14  ###
```

**70% arrive between 07:00 and 09:59, and 202 of 383 at 08:00 exactly.** Nothing at all
lands between 21:00 and 06:00. Both retailers behave the same way: JB Hi-Fi peaks at
08:00 (150 of 317), The Good Guys at 08:00 (52 of 66).

A run at 10:00 puts the entire morning batch through within three hours of arrival. The
afternoon stragglers wait until tomorrow, which costs nothing: these offers run for days,
not hours.

Thursday to Saturday is the promo window and Sunday is quietest, but every weekday still
carries 39-73 emails over the period. **Skipping days is not worth it** - restricting to
Thu-Sat would have missed 133 of 383.

### Running it on a timer

```ini
# ~/.config/systemd/user/shopwatch-mail.timer
[Unit]
Description=Read retailer email for offers
[Timer]
OnCalendar=*-*-* 08,18:00:00
Persistent=true          # catches up after the lid has been shut
[Install]
WantedBy=timers.target
```

## Deployed on opti

Live at **https://shop.home.lunt.au** (LAN only, trusted `*.home.lunt.au` wildcard cert).

| Thing | Where |
|---|---|
| Bare repo (push target) | `root@100.115.75.8:/root/shopwatch.git` |
| Stack (Dockge-managed) | `/srv/prod/shopwatch` |
| Working clone | `/srv/prod/shopwatch/repo` |
| Database | docker volume `shopwatch_shopwatch-data` at `/data/shopwatch.db` |
| Secrets | `/srv/prod/shopwatch/.env` (0600, opti-only, never in the repo) |
| Caddy vhost | `opti-stacks/caddy/Caddyfile` in the `smart-home` repo |
| DNS record | `dns.hosts` in `/srv/prod/pihole/etc-pihole/pihole.toml` |

The container publishes **no host port**. Caddy reaches it by container name on the `web`
network, which is what supplies the certificate and keeps it off the LAN without a
hostname.

### Push to deploy

```bash
git remote add opti root@100.115.75.8:/root/shopwatch.git   # once
B=$(git branch --show-current) && git push origin "$B"      # GitHub, if one is added
B=$(git branch --show-current) && git push opti "$B"        # deploys
```

The `post-receive` hook pulls the clone, copies `deploy/docker-compose.opti.yml` into
place, and rebuilds **only** when `app/`, `Dockerfile`, `requirements.txt` or the compose
file changed — a README-only push updates the clone and leaves the container running.
Migrations are forward-only and run on boot, so a deploy never wipes the database.

### Alerting is off until you turn it on

`/srv/prod/shopwatch/.env` ships with `SHOPWATCH_NTFY_URL` empty, so nothing publishes
anywhere. To switch it on, create a topic and fill in the URL plus the publish token from
`/root/.ntfy_pub_token` (the server rejects unauthenticated publishes with a 403, so a
missing token means silent failure at the server, which the app reports as
`[ALERT-FAILURE]` and a non-zero exit).

Note this cuts across the house "ntfy is for faults only" policy: a price alert is not a
fault. That is a deliberate decision to make, not a default to inherit, which is why the
value ships empty.

### Scheduling the watch

There is no timer yet, deliberately: three of the five seeded retailers cannot be scraped
at all (see **Retailer scraping limitations**), so a schedule would currently be a no-op
that looks like coverage. Add one once at least one adapter reliably returns a price:

```bash
ssh root@100.115.75.8 'docker compose -f /srv/prod/shopwatch/docker-compose.yml \
  exec -T shopwatch python -m app.price_watch --trigger cron'
```

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

## Running several products at once

A product carries two independent fields, deliberately not merged:

| Field | Question it answers | Values |
|---|---|---|
| `verdict` | Is this worth buying? | `BUY` / `MAYBE` / `IGNORE` |
| `status` | Where is it in the process? | `ACTIVE` / `PURCHASED` / `PARKED` |

You can be `verdict=BUY status=ACTIVE` (want it, still hunting) or `verdict=MAYBE
status=PURCHASED` (bought it anyway). Collapsing the two loses that.

The board defaults to `ACTIVE`, with counts per status in the filter row, and always sorts
ACTIVE first so a new research target never buries the thing you are actually hunting. Add
as many products as you like: `POST /api/products` or the **New product** button needs only
a name and an exact model, and everything else can be filled in later.

`PARKED` is for a product you have not given up on but do not want notifications about. It
keeps every listing, price and history row, and stops the watch checking it.

## Marking a purchase

**Mark purchased** on the product page, or:

```bash
curl -X POST http://SERVER-IP:8477/api/products/1/purchase \
  -H 'Content-Type: application/json' -d '{
    "listing_id": 1,
    "price_paid": 894,
    "advertised_paid": 869,
    "freight_paid": 25,
    "order_reference": "CS-12345",
    "warranty_months": 12,
    "price_protection_until": "2026-10-11"
  }'
```

`price_paid` is the **delivered** figure and is the only required field, because it is the
only number that settles the question. `listing_id` is optional: plenty of things get
bought in a shop or from someone who was never on the board, so pass `retailer_name`
instead and it still records cleanly.

Recording a purchase:

* moves the product to `PURCHASED`, which **stops its alerts** and takes it out of the
  watch, so a bought item does not keep telling you its price is good;
* writes a `price_history` row with source `purchase` and `freight_resolved = 1` — a price
  someone actually paid is the most trustworthy observation there is;
* keeps everything else. `DELETE /api/products/{id}/purchase` undoes the record and returns
  the product to `ACTIVE`, deliberately leaving the history row behind: it records a price
  that really was paid, and history is append-only even when the bookkeeping was wrong.

### Price protection

`price_protection_until` (a `YYYY-MM-DD` date) is optional and off by default. Set it and
the watch keeps running on that product and raises a **Price protection** alert if a
*confirmed* delivered price drops below what you paid, which is what you need to claim
against a retailer's price guarantee. Unconfirmed prices are ignored: sending someone to a
checkout to discover it was never actually cheaper is worse than saying nothing. Leave the
field empty and buying simply stops the watch.

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
.venv/bin/python -m pytest        # 144 tests
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

Probed 2026-09-11 from an Australian residential IP: first with the adapters' own
`fetch()`, then the same products read in a signed-in desktop browser. Re-run rather than
trust this table; it is a snapshot.

| Retailer | Plain adapter | Browser | What the page gives up |
|---|---|---|---|
| Crowdshop | 200, 273 KB | n/a | price, stock; freight needs checkout |
| Harvey Norman | **Incapsula challenge** (HTTP 200) | reads fine | price, model, warranty, GTIN; no freight or stock |
| JB Hi-Fi | untested URL | reads fine | price, model, SKU/PLU, store stock, C&C; **no freight figure** |
| The Good Guys | untested URL | reads fine | price, model, **freight $28 quoted on-page**, C&C, in-store stock |
| Appliance Central | **403** | reads fine | price, model, checkout coupon, stock, warranty; freight conditional |

**Harvey Norman is the instructive one.** It returns HTTP 200 with a "Pardon Our
Interruption" interstitial, so a naive adapter parses it, finds no price, and reports
`unresolved` — identical to what it reports for a product page that genuinely has no
price. `retailers.base.detect_block()` catches that family of pages and raises
`FetchError` instead, so a block reaches the run as an **error**, which is what it is.
Add a marker there if a new retailer starts doing the same.

**The Good Guys is the surprise.** It publishes a real freight figure on the product page,
but only against the browser's remembered preferred store. A headless scraper carrying no
store cookie sees nothing, so this stays a browser-assisted field rather than an adapter
one.

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

### Known gap: the historical low latches

`store.maybe_lower_known_low()` lowers a product's recorded low whenever a **confirmed**
delivered price beats it, and never raises it again. That is right for a market that moves
and wrong for a typo: a mistyped freight or price that produces a resolved delivered figure
sets the low permanently, and every later listing then reads as dearer than a price that
never existed. This bit during development — a `$25` freight typed into a persistence test
set the low to `$894`.

There is no heuristic guarding it, deliberately: any rule that rejects "implausible" lows
would also reject the genuine bargain the tool exists to catch. The low is editable in the
product dialog, and `GET /api/price-history/{id}` shows which observation produced it. If a
low looks wrong, check the history row's `source` before believing it.

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
