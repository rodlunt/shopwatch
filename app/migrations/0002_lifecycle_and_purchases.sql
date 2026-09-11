-- 0002: product lifecycle status and purchase records.
--
-- Two separate axes, deliberately not merged:
--   verdict  - the judgement  (BUY / MAYBE / IGNORE)
--   status   - where the product sits in the process (ACTIVE / PURCHASED / PARKED)
-- A product can be verdict=BUY status=ACTIVE (want it, still hunting) or
-- verdict=MAYBE status=PURCHASED (bought it anyway). Collapsing them loses that.

ALTER TABLE products ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE';

CREATE TABLE IF NOT EXISTS purchases (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id             INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    listing_id             INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    retailer_id            INTEGER REFERENCES retailers(id) ON DELETE SET NULL,
    retailer_name          TEXT,          -- denormalised: survives a listing being removed
    purchased_at           TEXT NOT NULL,
    price_paid             REAL NOT NULL, -- delivered price actually paid, the number that matters
    advertised_paid        REAL,
    freight_paid           REAL,
    condition              TEXT NOT NULL DEFAULT 'NEW',
    order_reference        TEXT,
    warranty_months        INTEGER,
    -- Optional. When set, the watch keeps running on this product and alerts if the
    -- delivered price drops below what was paid, for retailer price guarantees.
    price_protection_until TEXT,
    last_alert_price       REAL,
    notes                  TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_purchases_product ON purchases(product_id);
