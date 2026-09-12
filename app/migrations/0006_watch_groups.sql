-- 0006: watch groups. Several genuinely different products (different brands, different
-- models) that satisfy the same underlying want, tracked together because you'll buy
-- whichever wins, not all of them.
--
-- Deliberately no shared price targets here: a $500 GPU and a $2,000 TV would never
-- share a trigger/excellent/historical-low, so a group carries no pricing columns of
-- its own. Each member product keeps its own targets exactly as today; the group is
-- just a grouping, not a second pricing entity.
CREATE TABLE IF NOT EXISTS watch_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    notes       TEXT,
    -- Set true once a purchase in this group archives every other candidate. Stored
    -- rather than derived from "are all members archived" so the board's query stays
    -- a plain WHERE clause, same as products.archived already is.
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- A product belongs to at most one group. SET NULL rather than CASCADE: deleting a
-- group (which nothing in the API actually does today) must not take its member
-- products' price history down with it.
ALTER TABLE products ADD COLUMN group_id INTEGER REFERENCES watch_groups(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_products_group ON products(group_id);
