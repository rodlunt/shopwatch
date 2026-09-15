"""Retailer search job state machine: claim/complete race-safety and staleness
recovery. Same discipline as test_llm_jobs.py - pure unit tests against sqlite, no
network, no Firecrawl. deploy/research-runner.py (the thing that actually claims and
answers a job) is a separate process this suite never touches - see
app/retailer_search.py's own module docstring.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app import retailer_search


def test_create_job_requires_a_query(conn):
    with pytest.raises(ValueError, match="query"):
        retailer_search.create_job(conn, "  ")


def test_create_job_starts_queued(conn):
    job_id = retailer_search.create_job(conn, json.dumps({"product_name": "Dreame RoboMower"}))
    conn.commit()

    job = retailer_search.get_job(conn, job_id)
    assert job["status"] == "QUEUED"
    assert job["result"] is None


def test_claim_next_queued_flips_status_and_sets_started_at(conn):
    job_id = retailer_search.create_job(conn, json.dumps({"product_name": "Dreame RoboMower"}))
    conn.commit()

    claimed = retailer_search.claim_next_queued(conn)
    conn.commit()

    assert claimed["id"] == job_id
    assert claimed["status"] == "RUNNING"
    assert claimed["started_at"] is not None


def test_claim_next_queued_is_empty_when_nothing_is_queued(conn):
    assert retailer_search.claim_next_queued(conn) is None


def test_claiming_twice_never_hands_out_the_same_job(conn):
    """The control this test exists for: two overlapping runner polls must not both
    walk away thinking they own the same job."""
    job_id = retailer_search.create_job(conn, json.dumps({"product_name": "Dreame RoboMower"}))
    conn.commit()

    first = retailer_search.claim_next_queued(conn)
    conn.commit()
    second = retailer_search.claim_next_queued(conn)

    assert first["id"] == job_id
    assert second is None


def test_complete_job_stores_the_result(conn):
    job_id = retailer_search.create_job(conn, json.dumps({"product_name": "Dreame RoboMower"}))
    conn.commit()
    retailer_search.claim_next_queued(conn)
    conn.commit()

    payload = json.dumps({"retailers": [{"name": "Bunnings", "homepage": "https://bunnings.com.au"}]})
    retailer_search.complete_job(conn, job_id, "DONE", result=payload)
    conn.commit()

    job = retailer_search.get_job(conn, job_id)
    assert job["status"] == "DONE"
    assert json.loads(job["result"])["retailers"][0]["name"] == "Bunnings"


def test_complete_job_rejects_a_non_terminal_status(conn):
    job_id = retailer_search.create_job(conn, json.dumps({"product_name": "Dreame RoboMower"}))
    conn.commit()
    with pytest.raises(ValueError, match="DONE or FAILED"):
        retailer_search.complete_job(conn, job_id, "RUNNING")


def test_a_job_stuck_running_past_the_ceiling_is_reconciled_to_failed(conn):
    """The control this test exists for: a killed runner must not look alive forever."""
    job_id = retailer_search.create_job(conn, json.dumps({"product_name": "Dreame RoboMower"}))
    conn.commit()
    long_ago = (
        datetime.now(UTC) - timedelta(seconds=retailer_search.JOB_CEILING_SECONDS + 30)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE retailer_search_jobs SET status = 'RUNNING', started_at = ? WHERE id = ?",
        (long_ago, job_id),
    )
    conn.commit()

    job = retailer_search.get_job(conn, job_id)  # get_job calls reconcile_stale itself

    assert job["status"] == "FAILED"
    assert "stale" in job["error"]


def test_a_job_running_within_the_ceiling_is_left_alone(conn):
    """The same control must NOT fail a job that is still genuinely in progress."""
    job_id = retailer_search.create_job(conn, json.dumps({"product_name": "Dreame RoboMower"}))
    conn.commit()
    retailer_search.claim_next_queued(conn)
    conn.commit()

    job = retailer_search.get_job(conn, job_id)

    assert job["status"] == "RUNNING"
