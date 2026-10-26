-- 0016: the Raspberry Pi watch for Bark Marker.
--
-- Adds what a scheduled, multi-retailer stock and price watch needs and the board did
-- not have: a normalised availability next to the retailer's own words, the previous
-- price and when it moved, per-adapter health, a durable alert queue, and alert rules
-- that are not all "fire at or below a fixed price".

-- availability is the normalised enum (in_stock, limited, dispatch_later, backorder,
-- out_of_stock, unknown). The retailer's own words stay in stock_status, which is also
-- what the API reports as availability_text. NULL means "never normalised", not unknown.
ALTER TABLE listings ADD COLUMN availability TEXT;
ALTER TABLE listings ADD COLUMN unit_limit INTEGER;
ALTER TABLE listings ADD COLUMN previous_price REAL;
ALTER TABLE listings ADD COLUMN price_changed_at TEXT;

-- Rule kinds. TARGET is every rule that existed before this migration: a fixed
-- max_delivered. TRIGGER follows products.trigger_price live, so editing (or auto
-- deriving) the trigger moves the alert with it. BACK_IN_STOCK, PRICE_DROP and
-- NEW_LOWEST are event rules; max_delivered is unused (0) for them.
ALTER TABLE alert_rules ADD COLUMN kind TEXT NOT NULL DEFAULT 'TARGET';
ALTER TABLE alert_rules ADD COLUMN min_drop_abs REAL NOT NULL DEFAULT 3.0;
ALTER TABLE alert_rules ADD COLUMN min_drop_pct REAL NOT NULL DEFAULT 5.0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_rules_kind
    ON alert_rules(product_id, kind) WHERE kind != 'TARGET';

-- One row per retailer adapter. consecutive_failures counts runs in a row in which the
-- adapter could not produce a usable reading (fetch error, parse failure, no price).
CREATE TABLE IF NOT EXISTS adapter_health (
    adapter              TEXT PRIMARY KEY,
    last_run_at          TEXT,
    last_success_at      TEXT,
    last_error           TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_runs           INTEGER NOT NULL DEFAULT 0,
    total_failures       INTEGER NOT NULL DEFAULT 0,
    streak_alerted_at    TEXT
);

-- Durable alert queue for the event kinds. An event stays 'pending' until delivery is
-- confirmed, so a failed push is retried on the next run instead of being marked fired.
-- dedupe_key is unique: the same transition can never be queued twice.
CREATE TABLE IF NOT EXISTS alert_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    listing_id  INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    dedupe_key  TEXT    NOT NULL UNIQUE,
    payload     TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending', -- pending|sent|expired|suppressed
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TEXT    NOT NULL,
    sent_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_events_status ON alert_events(status, created_at);

-- Adapters for the Bark Marker retailers. Amazon AU is deliberately absent: see README,
-- "The Pi watch". Rows that do not exist yet are simply not touched.
UPDATE retailers SET adapter = 'core_electronics'      WHERE slug = 'core_electronics';
UPDATE retailers SET adapter = 'pb_tech'               WHERE slug = 'pb_tech';
UPDATE retailers SET adapter = 'pakronics'             WHERE slug = 'pakronics';
UPDATE retailers SET adapter = 'small_devices'         WHERE slug = 'small_devices';
UPDATE retailers SET adapter = 'zaitronics'            WHERE slug = 'zaitronics';
UPDATE retailers SET adapter = 'raspberry_pi_australia' WHERE slug = 'raspberry_pi_australia';

-- The Pi prices and stock text were typed in by hand on 26 Oct 2026, and an inline edit
-- locks the field as MANUAL. A locked field is never overwritten by an adapter, so without
-- this the watch would run, report success and change nothing. Release the lock on the two
-- fields an adapter now owns, for Pi listings that have one. (Amazon AU has no adapter, so
-- its hand-typed values stay locked.)
UPDATE field_provenance
   SET manual_locked = 0, state = 'UNVERIFIED',
       note = '0016: released, an adapter now watches this field'
 WHERE field IN ('advertised_price', 'stock_status') AND manual_locked = 1
   AND listing_id IN (
       SELECT l.id FROM listings l
         JOIN retailers r ON r.id = l.retailer_id
         JOIN products p ON p.id = l.product_id
        WHERE lower(p.category) = 'barkmarker' AND r.adapter IS NOT NULL);

-- Alert rules for the Pi products already on the board (category 'Barkmarker'). Products
-- added later get theirs from app/pi_events.ensure_rules() at the start of each run.
-- require_complete and require_resolved are 0: a bare board has no "included components"
-- to record and no retailer shows a confirmed freight figure, so the defaults would
-- silence every Pi listing for ever.
INSERT OR IGNORE INTO alert_rules
    (product_id, name, kind, conditions, max_delivered, require_complete, require_resolved, min_change)
SELECT id, 'At or below trigger price', 'TRIGGER', 'NEW', 0, 0, 0, 1.0
  FROM products WHERE lower(category) = 'barkmarker' AND status = 'ACTIVE';
INSERT OR IGNORE INTO alert_rules
    (product_id, name, kind, conditions, max_delivered, require_complete, require_resolved, min_change)
SELECT id, 'Back in stock', 'BACK_IN_STOCK', 'NEW', 0, 0, 0, 0
  FROM products WHERE lower(category) = 'barkmarker' AND status = 'ACTIVE';
INSERT OR IGNORE INTO alert_rules
    (product_id, name, kind, conditions, max_delivered, require_complete, require_resolved, min_change)
SELECT id, 'Price drop', 'PRICE_DROP', 'NEW', 0, 0, 0, 0
  FROM products WHERE lower(category) = 'barkmarker' AND status = 'ACTIVE';
INSERT OR IGNORE INTO alert_rules
    (product_id, name, kind, conditions, max_delivered, require_complete, require_resolved, min_change)
SELECT id, 'New lowest in-stock price', 'NEW_LOWEST', 'NEW', 0, 0, 0, 1.0
  FROM products WHERE lower(category) = 'barkmarker' AND status = 'ACTIVE';
