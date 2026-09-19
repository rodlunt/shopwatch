-- 0010: a second question the research job pipeline can ask.
--
-- Everything in 0005 assumed one question: "what's this retailer selling it for
-- today", answered once per selected retailer. Issue #93 asks a genuinely different
-- question - "has this ever been cheaper, before shopwatch was tracking it at all" -
-- which is not per-retailer (it's a single web research pass across price-history
-- trackers, cached listings, whatever's findable) and must never auto-write a
-- product's lowest_known_* fields the way a confirmed delivered price does
-- (store.maybe_lower_known_low). An LLM's best-effort historical guess is not a
-- confirmed listing and must never be presented, or stored, as one.
--
-- `kind` distinguishes the two without a second job table: the lifecycle (queue,
-- claim, staleness reconciliation, one-active-job-per-product) is identical, only the
-- question and the shape of the answer differ. Same reasoning llm_jobs (0007) already
-- used for its own two kinds.
--
-- The historical_low_* columns hold the job's own proposed finding - an estimate for
-- a human to confirm or discard via the ordinary product-edit form (PATCH
-- /api/products/{id}, the same endpoint a manual edit already uses), never applied to
-- the product directly by this table or by app/research.py. That is the whole point:
-- there is no code path from these columns to products.lowest_known_price other than
-- a person choosing to copy the estimate into the edit form and hitting Save.
ALTER TABLE research_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'price';
                           -- price | historical_low
ALTER TABLE research_jobs ADD COLUMN historical_low_price REAL;
ALTER TABLE research_jobs ADD COLUMN historical_low_date TEXT;
ALTER TABLE research_jobs ADD COLUMN historical_low_retailer TEXT;
ALTER TABLE research_jobs ADD COLUMN historical_low_notes TEXT;
ALTER TABLE research_jobs ADD COLUMN historical_low_confidence TEXT;
                           -- LOW | MEDIUM | HIGH, the model's own stated confidence -
                           -- also never used to bypass the "confirm or discard" step.
