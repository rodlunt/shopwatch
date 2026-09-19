-- 0011: URL-scoped research-job results - "paste a listing URL" (issue #94).
--
-- A job created from a pasted URL (app.main's from-url endpoint) asks the runner about
-- ONE specific page, not "search generically for this retailer" - the whole reason
-- pasting a URL beats typing a retailer name into the wizard is that the runner can
-- read the exact page instead of guessing which one it is. NULL here means the
-- ordinary retailer-name search this table has always supported; a job created any
-- other way (the wizard's retailer picker) never sets it.
ALTER TABLE research_job_results ADD COLUMN url TEXT;
