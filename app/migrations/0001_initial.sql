-- 0001_initial: core schema for the shopping comparison / price-watch board.
-- Migrations are applied in filename order and are never re-run. Never destructive.

CREATE TABLE IF NOT EXISTS products (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT    NOT NULL,
    model                   TEXT    NOT NULL UNIQUE,   -- exact model number, the match key for imports
    brand                   TEXT,
    category                TEXT    NOT NULL DEFAULT 'general',
    generation              TEXT,                      -- generation / model year
    verdict                 TEXT    NOT NULL DEFAULT 'MAYBE',  -- BUY | MAYBE | IGNORE
    notes                   TEXT,

    -- price targets, all expressed as DELIVERED price
    trigger_price           REAL,
    excellent_price         REAL,
    historical_low_price    REAL,                      -- "historical-low territory" threshold
    lowest_known_price      REAL,
    lowest_known_date       TEXT,
    lowest_known_retailer   TEXT,
    lowest_known_notes      TEXT,

    -- physical fit (generic, applies to every category)
    width_mm                REAL,
    height_mm               REAL,
    depth_mm                REAL,
    weight_kg               REAL,
    packaged_width_mm       REAL,
    packaged_height_mm      REAL,
    packaged_depth_mm       REAL,
    packaged_weight_kg      REAL,
    mounting_notes          TEXT,
    vesa                    TEXT,
    fit_notes               TEXT,

    -- category-specific specs and optional component dimensions, JSON objects
    specs_json              TEXT    NOT NULL DEFAULT '{}',
    components_json         TEXT    NOT NULL DEFAULT '{}',

    archived                INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS retailers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    slug        TEXT    NOT NULL UNIQUE,
    adapter     TEXT,                 -- module name under app/retailers, NULL = manual only
    homepage    TEXT,
    notes       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS listings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    retailer_id         INTEGER NOT NULL REFERENCES retailers(id) ON DELETE CASCADE,
    url                 TEXT,
    model_on_page       TEXT,                        -- exact model the retailer page shows
    advertised_price    REAL,
    freight             REAL,                        -- NULL means UNRESOLVED, not free
    cashback            REAL,
    rebate              REAL,
    coupon_discount     REAL,
    condition           TEXT NOT NULL DEFAULT 'NEW', -- NEW|FACTORY_SECOND|CARTON_DAMAGED|USED|EX_DISPLAY|REFURBISHED
    stock_status        TEXT,
    pickup_status       TEXT,
    pickup_location     TEXT,
    warranty            TEXT,
    included_components TEXT,
    seller_notes        TEXT,
    price_guide         TEXT,                        -- free text range when a page quotes a band
    active              INTEGER NOT NULL DEFAULT 1,
    last_checked_at     TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (product_id, retailer_id, url)
);
CREATE INDEX IF NOT EXISTS idx_listings_product ON listings(product_id);

-- Provenance is stored PER FIELD, not per listing.
CREATE TABLE IF NOT EXISTS field_provenance (
    listing_id    INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    field         TEXT    NOT NULL,
    state         TEXT    NOT NULL DEFAULT 'UNVERIFIED', -- LIVE|MANUAL|UNVERIFIED|STALE|IMPORTED
    source        TEXT,                                  -- adapter name, 'ui', 'import', url, phone call...
    manual_locked INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (listing_id, field)
);

-- Verification is tracked per aspect, never as one vague boolean.
CREATE TABLE IF NOT EXISTS listing_verification (
    listing_id  INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    aspect      TEXT    NOT NULL,   -- model|price|stock|freight|condition|warranty|contents
    status      TEXT    NOT NULL DEFAULT 'UNVERIFIED', -- VERIFIED|LIVE|MANUAL|IMPORTED|UNVERIFIED|STALE|FLAGGED
    note        TEXT,
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (listing_id, aspect)
);

-- Observations are append-only. Never deleted because the current price moved.
CREATE TABLE IF NOT EXISTS price_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    listing_id       INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    retailer_id      INTEGER REFERENCES retailers(id) ON DELETE SET NULL,
    observed_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    advertised_price REAL,
    delivered_price  REAL,
    freight          REAL,
    freight_resolved INTEGER NOT NULL DEFAULT 0,
    cashback         REAL,
    stock_status     TEXT,
    condition        TEXT,
    source           TEXT,   -- 'ui' | 'import' | adapter slug | 'seed'
    note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_product ON price_history(product_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_history_listing ON price_history(listing_id, observed_at);

CREATE TABLE IF NOT EXISTS alert_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,
    conditions          TEXT    NOT NULL DEFAULT 'NEW',  -- comma separated condition allowlist
    max_delivered       REAL    NOT NULL,                -- fire at or below this delivered price
    require_complete    INTEGER NOT NULL DEFAULT 1,      -- ignore listings missing components
    require_resolved    INTEGER NOT NULL DEFAULT 1,      -- ignore unresolved freight
    min_change          REAL    NOT NULL DEFAULT 20.0,   -- suppress trivial re-alerts
    enabled             INTEGER NOT NULL DEFAULT 1,
    last_fired_at       TEXT,
    last_fired_price    REAL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    trigger     TEXT    NOT NULL DEFAULT 'manual',  -- manual|cli|api|cron
    status      TEXT    NOT NULL DEFAULT 'running', -- running|ok|partial|failed
    checked     INTEGER NOT NULL DEFAULT 0,
    updated     INTEGER NOT NULL DEFAULT 0,
    errors      INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS scrape_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    status     TEXT    NOT NULL,  -- ok|unresolved|error|skipped
    message    TEXT,
    payload    TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_results_run ON scrape_results(run_id);

-- Category profiles: which optional spec fields a category offers. Adding a category
-- is inserting rows here, not a schema change.
CREATE TABLE IF NOT EXISTS category_specifications (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    category  TEXT    NOT NULL,
    field_key TEXT    NOT NULL,
    label     TEXT    NOT NULL,
    kind      TEXT    NOT NULL DEFAULT 'text',  -- text|number|bool|select
    options   TEXT,                             -- JSON array for select
    sort      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (category, field_key)
);
