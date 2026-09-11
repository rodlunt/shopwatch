-- 0003: offers seen in retailer marketing email.
--
-- An offer is a LEAD, never a price. It never touches a listing's delivered_price and
-- is never applied as a coupon automatically: "20% off a huge range" with three
-- paragraphs of exclusions is not a fact about your soundbar until someone checks.
-- Same discipline as unresolved freight - say what is known, flag what is not.

CREATE TABLE IF NOT EXISTS offers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id       TEXT    NOT NULL UNIQUE,  -- RFC822 Message-ID, the dedupe key
    source           TEXT    NOT NULL DEFAULT 'email',
    retailer_id      INTEGER REFERENCES retailers(id) ON DELETE SET NULL,
    retailer_name    TEXT,
    sender           TEXT,
    subject          TEXT,
    received_at      TEXT,

    kind             TEXT,     -- percent_off | dollar_off | cashback | store_credit
                               -- | bundle | finance | other | none
    amount           REAL,
    spend_threshold  REAL,
    applies_to       TEXT,     -- scope in the email's own words
    categories       TEXT,     -- JSON array of normalised categories
    excludes         TEXT,
    code             TEXT,
    expires_at       TEXT,
    requires_signup  INTEGER NOT NULL DEFAULT 0,
    confidence       TEXT,     -- high | medium | low, as judged by the extractor
    summary          TEXT,
    extracted_by     TEXT,     -- model id, or 'gate' when no extraction ran
    raw_excerpt      TEXT,

    status           TEXT    NOT NULL DEFAULT 'NEW',  -- NEW | ACTED | DISMISSED
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status, received_at);

-- Which tracked products an offer might touch, and what it would do to the price.
-- `projected_delivered` is explicitly a projection, never stored on the listing.
CREATE TABLE IF NOT EXISTS offer_matches (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id             INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    product_id           INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    listing_id           INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    basis_delivered      REAL,   -- the price it was projected from
    projected_delivered  REAL,
    crosses_trigger      INTEGER NOT NULL DEFAULT 0,
    rationale            TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (offer_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_product ON offer_matches(product_id);

-- Where the mail reader got to, so a re-run does not re-read the whole mailbox.
CREATE TABLE IF NOT EXISTS mail_cursor (
    source        TEXT PRIMARY KEY,
    last_seen_at  TEXT,
    last_run_at   TEXT,
    messages_seen INTEGER NOT NULL DEFAULT 0,
    notes         TEXT
);
