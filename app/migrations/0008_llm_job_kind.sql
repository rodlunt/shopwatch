-- llm_jobs (0007) only ever asked one question: "suggest models for this description".
-- The wizard's retailers step now queues a second kind of question through the same
-- job queue - "who else sells this, beyond the retailers already listed" - answered by
-- the same user-run tools/llm-helper.py using the same CLI login. `kind` is how the
-- helper picks which prompt template and reply schema to use; existing/omitted rows
-- default to the only kind that existed before this migration.
ALTER TABLE llm_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'model_suggestion';
