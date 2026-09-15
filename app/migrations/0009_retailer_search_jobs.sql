-- 0009: retailer search jobs - "who else, beyond what's already selected, sells this",
-- answered by a LIVE web search rather than an LLM's training knowledge.
--
-- Same one-question-one-answer shape as llm_jobs (0007), but a different claimant: this
-- queue is polled by deploy/research-runner.py on opti (same host-level script and
-- systemd timer that already claims research_jobs), which calls the self-hosted
-- Firecrawl instance running on opti's loopback (127.0.0.1:3002, not reachable from
-- this container's own docker network - that's WHY this is a host-level job queue and
-- not a direct HTTP call from app/main.py). llm_jobs' retailer_discovery kind stays as
-- the zero-infrastructure fallback: this table exists for the strictly better, live
-- version, not to replace it.
--
-- query is JSON: {"product_name": ..., "model": ..., "excluded_names": [...],
-- "excluded_homepages": [...]} - structured, not free text, since the runner needs
-- discrete fields to build a search query and to filter results, not a sentence to
-- re-parse.
CREATE TABLE IF NOT EXISTS retailer_search_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'QUEUED',
                 -- QUEUED | RUNNING | DONE | FAILED
    result       TEXT,    -- JSON: {"retailers": [{"name", "homepage"}...], "note": ...}
    error        TEXT,
    requested_at TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_retailer_search_jobs_status ON retailer_search_jobs(status, id);
