-- 0007: LLM helper jobs - free-text product description -> candidate model numbers.
--
-- Same shape as research_jobs (0005): the job's own lifecycle lives in this container,
-- but the actual LLM call never does. The difference from research_jobs is WHO claims
-- it: research_jobs is claimed by a fixed host-level script on opti using opti's own
-- shared Claude Code token; an llm_job is claimed by WHOEVER's own machine is running
-- tools/llm-helper.py, authenticated with THEIR OWN Claude Code or Codex CLI login.
-- Nothing here holds or bills for that credential - see the README's "Set up your LLM"
-- section for the client-side half of this.
--
-- One query, one answer: unlike research_jobs there is no per-retailer breakdown table,
-- because a model-suggestion job asks one question and gets one structured reply.
CREATE TABLE IF NOT EXISTS llm_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT    NOT NULL,   -- the free-text "what is it" the wizard sent
    status       TEXT    NOT NULL DEFAULT 'QUEUED',
                 -- QUEUED | RUNNING | DONE | FAILED
    result       TEXT,    -- JSON: {"candidates": [...], "note": "..."}, set on DONE
    error        TEXT,    -- set on FAILED
    requested_at TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_llm_jobs_status ON llm_jobs(status, id);
