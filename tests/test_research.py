"""Research-job state machine: concurrency guard, default-deny, and staleness recovery.

Pure unit tests against sqlite - no subprocess, no `claude` CLI, nothing that spends
real quota. That boundary is deliberate: the host-level runner is a separate process
this suite never touches (see app/research.py's module docstring).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import research, store


@pytest.fixture()
def product_id(conn):
    pid = store.create_product(conn, {"name": "Test TV", "model": "TEST-MODEL-1"})
    conn.commit()
    return pid


@pytest.fixture()
def retailer_ids(conn):
    ids = [
        store.ensure_retailer(conn, "JB Hi-Fi")["id"],
        store.ensure_retailer(conn, "Harvey Norman")["id"],
    ]
    conn.commit()
    return ids


def test_create_job_queues_a_result_row_per_known_retailer(conn, product_id, retailer_ids):
    job_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()

    job = research.get_job(conn, job_id)
    assert job["status"] == "QUEUED"
    assert {r["retailer_id"] for r in job["results"]} == set(retailer_ids)
    assert all(r["status"] == "PENDING" for r in job["results"])


def test_create_job_silently_drops_unknown_retailer_ids(conn, product_id, retailer_ids):
    """Default-deny: an id that isn't a real retailer never reaches the job at all."""
    bogus_id = 999999
    job_id = research.create_job(conn, product_id, [*retailer_ids, bogus_id])
    conn.commit()

    job = research.get_job(conn, job_id)
    assert {r["retailer_id"] for r in job["results"]} == set(retailer_ids)


def test_create_job_rejects_all_unknown_retailers(conn, product_id):
    with pytest.raises(ValueError, match="no known retailers"):
        research.create_job(conn, product_id, [999999])


def test_second_active_job_for_same_product_is_rejected(conn, product_id, retailer_ids):
    """The concurrency guard: a double-click must not spend the shared quota twice."""
    first_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()

    with pytest.raises(research.JobAlreadyRunning) as exc_info:
        research.create_job(conn, product_id, retailer_ids)
    assert exc_info.value.job_id == first_id


def test_a_completed_job_does_not_block_a_new_one(conn, product_id, retailer_ids):
    first_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()
    research.complete_job(conn, first_id, "DONE")
    conn.commit()

    second_id = research.create_job(conn, product_id, retailer_ids)  # must not raise
    assert second_id != first_id


def test_claim_next_queued_flips_status_and_sets_started_at(conn, product_id, retailer_ids):
    job_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()

    claimed = research.claim_next_queued(conn)
    conn.commit()

    assert claimed["id"] == job_id
    assert claimed["status"] == "RUNNING"
    assert claimed["started_at"] is not None


def test_claim_next_queued_returns_none_when_nothing_queued(conn):
    assert research.claim_next_queued(conn) is None


def test_report_result_then_complete_marks_the_job_done(conn, product_id, retailer_ids):
    job_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()
    research.claim_next_queued(conn)
    conn.commit()

    research.report_result(conn, job_id, retailer_ids[0], "FOUND", note="found it")
    research.report_result(conn, job_id, retailer_ids[1], "NEEDS_MANUAL_CHECK", note="blocked")
    research.complete_job(conn, job_id, "DONE")
    conn.commit()

    job = research.get_job(conn, job_id)
    assert job["status"] == "DONE"
    by_retailer = {r["retailer_id"]: r["status"] for r in job["results"]}
    assert by_retailer[retailer_ids[0]] == "FOUND"
    assert by_retailer[retailer_ids[1]] == "NEEDS_MANUAL_CHECK"


def test_report_result_rejects_an_unknown_status(conn, product_id, retailer_ids):
    job_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()
    with pytest.raises(ValueError):
        research.report_result(conn, job_id, retailer_ids[0], "MADE_UP_STATUS")


def test_a_job_stuck_running_past_the_ceiling_is_reconciled_to_failed(
    conn, product_id, retailer_ids
):
    """The control this test exists for: a wedged host script must not look alive forever."""
    job_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()
    long_ago = (datetime.now(UTC) - timedelta(seconds=research.JOB_CEILING_SECONDS + 60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn.execute(
        "UPDATE research_jobs SET status = 'RUNNING', started_at = ? WHERE id = ?",
        (long_ago, job_id),
    )
    conn.commit()

    job = research.get_job(conn, job_id)  # get_job calls reconcile_stale itself

    assert job["status"] == "FAILED"
    assert "stale" in job["error"]


def test_a_job_running_within_the_ceiling_is_left_alone(conn, product_id, retailer_ids):
    """The same control must NOT fail a job that is still genuinely in progress."""
    job_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()
    research.claim_next_queued(conn)
    conn.commit()

    job = research.get_job(conn, job_id)

    assert job["status"] == "RUNNING"


def test_reconciling_a_stale_running_job_frees_the_product_for_a_new_one(
    conn, product_id, retailer_ids
):
    job_id = research.create_job(conn, product_id, retailer_ids)
    conn.commit()
    long_ago = (datetime.now(UTC) - timedelta(seconds=research.JOB_CEILING_SECONDS + 60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn.execute(
        "UPDATE research_jobs SET status = 'RUNNING', started_at = ? WHERE id = ?",
        (long_ago, job_id),
    )
    conn.commit()
    research.reconcile_stale(conn)
    conn.commit()

    new_job_id = research.create_job(conn, product_id, retailer_ids)  # must not raise
    assert new_job_id != job_id
