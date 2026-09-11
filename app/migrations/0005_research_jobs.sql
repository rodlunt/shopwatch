-- 0005: research jobs, the wizard's "let's go" step.
--
-- A job is a host-triggered, credentialed research pass over one product's chosen
-- retailers, run outside this container by a host-level script on opti (see README's
-- mailwatch section for the precedent this follows: the token never enters the
-- container that serves this API). This table only ever records the job's own
-- lifecycle; every price it finds still lands through the ordinary import path
-- (app/ingest.py) and its ordinary IMPORTED provenance, so a research job carries no
-- new pricing columns of its own.
--
-- Only one ACTIVE (queued or running) job per product at a time: a double-click or a
-- retried request must not queue a second spend behind the first, let alone run one
-- concurrently. A terminal job (DONE/FAILED) never blocks a new one.
CREATE TABLE IF NOT EXISTS research_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    status        TEXT    NOT NULL DEFAULT 'QUEUED',
                  -- QUEUED | RUNNING | DONE | FAILED
    requested_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at    TEXT,
    finished_at   TEXT,
    error         TEXT,   -- set on FAILED: timeout, crash, dead token, etc.
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_research_jobs_one_active
    ON research_jobs(product_id) WHERE status IN ('QUEUED', 'RUNNING');
CREATE INDEX IF NOT EXISTS idx_research_jobs_product ON research_jobs(product_id, id DESC);

-- One row per retailer the job was asked to check, so the wizard can render "3 found,
-- 2 need manual checking" without re-parsing a blob, and so a slow retailer never blocks
-- rendering the ones that already finished.
CREATE TABLE IF NOT EXISTS research_job_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    retailer_id INTEGER NOT NULL REFERENCES retailers(id) ON DELETE CASCADE,
    status      TEXT    NOT NULL DEFAULT 'PENDING',
                -- PENDING | FOUND | NEEDS_MANUAL_CHECK | BLOCKED | TIMED_OUT
    listing_id  INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (job_id, retailer_id)
);
CREATE INDEX IF NOT EXISTS idx_research_results_job ON research_job_results(job_id);
