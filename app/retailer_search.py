"""Retailer search jobs: "who else sells this, beyond what's already selected" -
answered by a LIVE web search, for the "Track something new" wizard's retailers step.

Same job-lifecycle shape as app/llm_jobs.py, but a different claimant. llm_jobs is
claimed by WHOEVER's own machine runs tools/llm-helper.py, using their own CLI login -
appropriate for a knowledge-only question an LLM can answer without browsing. This
queue needs an actual live search, which means the self-hosted Firecrawl instance on
opti (127.0.0.1:3002) - reachable only from opti's own host network, not from this
container's docker network. So this queue is claimed by deploy/research-runner.py, the
same fixed host-level script (and systemd timer) that already claims research_jobs,
extended to also poll this queue each cycle. Nothing about Firecrawl's location or
credentials ever needs to exist in this container.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import utcnow

STATUSES = ("QUEUED", "RUNNING", "DONE", "FAILED")

#: Same order of magnitude as llm_jobs' ceiling: a live search plus a handful of page
#: reads, not a multi-retailer research pass - a runner that hasn't reported back
#: inside two minutes is almost certainly gone, not merely slow.
JOB_CEILING_SECONDS = 120


def _seconds_since(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    from datetime import UTC, datetime

    then = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (datetime.now(UTC) - then).total_seconds()


def reconcile_stale(conn: sqlite3.Connection) -> list[int]:
    """Fail any job that has been RUNNING longer than the ceiling with nothing reporting.

    Same discipline as llm_jobs.reconcile_stale: called on every read, so a wedged or
    killed runner is caught within one ceiling window rather than left QUEUED-looking
    forever from the wizard's point of view.
    """
    stale = conn.execute(
        "SELECT id, started_at FROM retailer_search_jobs WHERE status = 'RUNNING'"
    ).fetchall()
    reconciled = []
    for row in stale:
        if _seconds_since(row["started_at"]) > JOB_CEILING_SECONDS:
            conn.execute(
                "UPDATE retailer_search_jobs SET status = 'FAILED', finished_at = ?,"
                " error = 'stale: no completion reported within the job ceiling'"
                " WHERE id = ?",
                (utcnow(), row["id"]),
            )
            reconciled.append(int(row["id"]))
    return reconciled


def create_job(conn: sqlite3.Connection, query: str) -> int:
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        raise ValueError("query is required")
    cur = conn.execute(
        "INSERT INTO retailer_search_jobs (query, status) VALUES (?, 'QUEUED')", (query,)
    )
    return int(cur.lastrowid)


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    reconcile_stale(conn)
    row = conn.execute("SELECT * FROM retailer_search_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def claim_next_queued(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Atomically claim the oldest QUEUED job for a runner.

    Same race-safety as llm_jobs.claim_next_queued: the UPDATE only affects a row still
    QUEUED, and changes() proves whether this call actually won it.
    """
    row = conn.execute(
        "SELECT id FROM retailer_search_jobs WHERE status = 'QUEUED' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE retailer_search_jobs SET status = 'RUNNING', started_at = ?"
        " WHERE id = ? AND status = 'QUEUED'",
        (utcnow(), row["id"]),
    )
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        return None  # lost the race to another claimer
    return get_job(conn, int(row["id"]))


def complete_job(
    conn: sqlite3.Connection, job_id: int, status: str,
    result: str | None = None, error: str | None = None,
) -> None:
    if status not in ("DONE", "FAILED"):
        raise ValueError("a job can only complete as DONE or FAILED")
    conn.execute(
        "UPDATE retailer_search_jobs SET status = ?, result = ?, error = ?, finished_at = ?"
        " WHERE id = ?",
        (status, result, error, utcnow(), job_id),
    )
