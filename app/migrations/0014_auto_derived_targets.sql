-- 0014: mark trigger_price/excellent_price/historical_low_price as system-derived
-- versus hand-typed (issue #101).
--
-- All three columns already exist and default to NULL, meaning "no target set". These
-- new flags do not change that meaning - a NULL target is still exactly as unset as it
-- was before this migration. What they add is a way to tell, for a target that DOES
-- have a value, whether a human typed it in or app/store.py's maybe_derive_price_targets
-- filled it in from lowest_known_price. That distinction matters for display (the
-- product-edit dialog labels a derived value "auto" per issue #101's UI requirement) and
-- for the one write rule this feature has to respect: never overwrite a value the user
-- set by hand. A plain boolean per field is enough for that - unlike field_provenance,
-- which exists because LISTINGS have many auto-writers racing a human edit (adapters,
-- imports, research runs) and need state/source/notes to arbitrate between them, a
-- product has exactly one auto-writer for these three fields and the only question ever
-- asked is "is the current value mine to touch", which a single flag answers.
ALTER TABLE products ADD COLUMN trigger_price_auto INTEGER NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN excellent_price_auto INTEGER NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN historical_low_price_auto INTEGER NOT NULL DEFAULT 0;
