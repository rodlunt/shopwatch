"""Research jobs: the wizard's "let's go" step.

A job's own lifecycle lives here, in this container. The actual research (a
credentialed subprocess call to `claude`, real internet egress, real shared quota) never
runs in this process or this container - see `deploy/research-runner.py` for the
host-level script that claims a job over this same API, invokes `claude`, and reports
back, exactly the way `app/mailwatch.py` already does for retailer marketing email. The
token never enters this container; this module only ever talks to sqlite and answers
HTTP calls from that host script.

Whatever a job finds still lands through the ordinary import path (`app/ingest.py`),
under the ordinary IMPORTED provenance state - a research job is not a second, parallel
way for prices to enter the database, only a new way to trigger `POST /api/import`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import utcnow

STATUSES = ("QUEUED", "RUNNING", "DONE", "FAILED")
RESULT_STATUSES = ("PENDING", "FOUND", "NEEDS_MANUAL_CHECK", "BLOCKED", "TIMED_OUT")

#: Hard backstop for a job that never reports back (host script crashed, opti rebooted
#: mid-run, network partition). Matches the per-job ceiling the host-level script is
#: expected to enforce on itself; this is the container-side proof of liveness for the
#: case where the host script cannot report its own failure at all.
JOB_CEILING_SECONDS = 600


class JobAlreadyRunning(RuntimeError):
    """Raised when a product already has an active (queued or running) job."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"a research job is already active for this product: {job_id}")
        self.job_id = job_id


def _seconds_since(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    from datetime import UTC, datetime

    then = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (datetime.now(UTC) - then).total_seconds()


def reconcile_stale(conn: sqlite3.Connection) -> list[int]:
    """Fail any job that has been RUNNING longer than the ceiling with nothing reporting.

    Called on app startup (catches a job orphaned by a crash/redeploy while nothing was
    running to update it) and opportunistically whenever a job is read, so a wedged host
    script is caught within one ceiling window rather than only at the next restart.
    """
    stale = conn.execute(
        "SELECT id FROM research_jobs WHERE status = 'RUNNING'"
    ).fetchall()
    reconciled = []
    for row in stale:
        job = conn.execute(
            "SELECT started_at FROM research_jobs WHERE id = ?", (row["id"],)
        ).fetchone()
        if _seconds_since(job["started_at"]) > JOB_CEILING_SECONDS:
            conn.execute(
                "UPDATE research_jobs SET status = 'FAILED', finished_at = ?,"
                " error = 'stale: no completion reported within the job ceiling'"
                " WHERE id = ?",
                (utcnow(), row["id"]),
            )
            reconciled.append(int(row["id"]))
    return reconciled


def create_job(
    conn: sqlite3.Connection,
    product_id: int,
    retailer_ids: list[int],
    urls: dict[int, str] | None = None,
) -> int:
    """Queue a job for one product across a fixed set of retailers.

    Default-deny by construction: a retailer id that is not already in the `retailers`
    table is silently dropped rather than passed through, so this can only ever ask
    about a retailer shopwatch already knows, never wherever a typo or a scraped page
    might lead the research pass.

    `urls` is optional and keyed by retailer_id: when a retailer id has an entry, the
    runner reads that exact page instead of searching generically for the product at
    that retailer (see deploy/research-runner.py's `research_one_retailer`). This is
    the "paste a listing URL" path (issue #94) - the whole point of having a URL in
    hand is that the runner does not have to guess which page is the right one. A
    retailer id with no entry behaves exactly as before.

    Refuses outright for an archived product - "give up on this" (or a group purchase
    that archived every other candidate) means stop watching, and a stray research job
    against something nobody is hunting any more is exactly the wasted spend that
    guarantee exists to prevent.
    """
    row = conn.execute("SELECT archived FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is not None and row["archived"]:
        raise ValueError("cannot start research on an archived product")
    if not retailer_ids:
        raise ValueError("at least one retailer is required")
    placeholders = ",".join("?" * len(retailer_ids))
    known_ids = [
        r["id"]
        for r in conn.execute(
            f"SELECT id FROM retailers WHERE id IN ({placeholders})", retailer_ids
        )
    ]
    if not known_ids:
        raise ValueError("no known retailers in the request")

    try:
        cur = conn.execute(
            "INSERT INTO research_jobs (product_id, status) VALUES (?, 'QUEUED')",
            (product_id,),
        )
    except sqlite3.IntegrityError as exc:
        existing = conn.execute(
            "SELECT id FROM research_jobs WHERE product_id = ?"
            " AND status IN ('QUEUED', 'RUNNING')",
            (product_id,),
        ).fetchone()
        if existing:
            raise JobAlreadyRunning(int(existing["id"])) from exc
        raise
    job_id = int(cur.lastrowid)
    urls = urls or {}
    for retailer_id in known_ids:
        conn.execute(
            "INSERT INTO research_job_results (job_id, retailer_id, status, url)"
            " VALUES (?, ?, 'PENDING', ?)",
            (job_id, retailer_id, urls.get(retailer_id)),
        )
    return job_id


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    reconcile_stale(conn)
    row = conn.execute("SELECT * FROM research_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    job = dict(row)
    job["results"] = [
        dict(r)
        for r in conn.execute(
            "SELECT rjr.*, r.name AS retailer_name, r.homepage AS retailer_homepage"
            " FROM research_job_results rjr"
            " JOIN retailers r ON r.id = rjr.retailer_id"
            " WHERE rjr.job_id = ? ORDER BY r.name",
            (job_id,),
        )
    ]
    return job


def get_latest_job_for_product(conn: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    """The most recent job for a product, terminal or not, so a caller can pre-fill a
    retry with whichever retailers did not come back FOUND last time - the whole point
    being that a retailer selection the wizard already made once is never something the
    person has to reconstruct from memory."""
    row = conn.execute(
        "SELECT id FROM research_jobs WHERE product_id = ? ORDER BY id DESC LIMIT 1",
        (product_id,),
    ).fetchone()
    return get_job(conn, row["id"]) if row else None


def claim_next_queued(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Atomically claim the oldest QUEUED job for the host-level runner.

    Flips it to RUNNING in the same statement a caller commits, so two overlapping
    polls from the host script (or a second host script) cannot both claim the same
    job - the UPDATE only affects a row still QUEUED, and `changes()` proves whether
    this call actually won it.
    """
    row = conn.execute(
        "SELECT id FROM research_jobs WHERE status = 'QUEUED' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE research_jobs SET status = 'RUNNING', started_at = ?"
        " WHERE id = ? AND status = 'QUEUED'",
        (utcnow(), row["id"]),
    )
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        return None  # lost the race to another claimer
    return get_job(conn, int(row["id"]))


def report_result(
    conn: sqlite3.Connection,
    job_id: int,
    retailer_id: int,
    status: str,
    listing_id: int | None = None,
    note: str | None = None,
) -> None:
    if status not in RESULT_STATUSES:
        raise ValueError(f"{status!r} is not a valid research-job result status")
    conn.execute(
        "UPDATE research_job_results SET status = ?, listing_id = ?, note = ?,"
        " updated_at = ? WHERE job_id = ? AND retailer_id = ?",
        (status, listing_id, note, utcnow(), job_id, retailer_id),
    )


def complete_job(
    conn: sqlite3.Connection, job_id: int, status: str, error: str | None = None
) -> None:
    if status not in ("DONE", "FAILED"):
        raise ValueError("a job can only complete as DONE or FAILED")
    conn.execute(
        "UPDATE research_jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
        (status, utcnow(), error, job_id),
    )
