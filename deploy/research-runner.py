#!/usr/bin/env python3
"""The wizard's "let's go" step, run from opti - never from inside the shopwatch container.

Mirrors app/mailwatch.py's existing wiring exactly: runs as a host-level script in its
own venv, sources the Claude Code OAuth token that already exists in
/srv/prod/career/runner.env (nothing new to store or rotate), and talks to the running
shopwatch container over plain HTTP on the docker network. The container never holds
this credential and never gains new outbound egress - only this script does.

    ssh root@YOUR-SERVER-IP
    set -a; . /srv/prod/career/runner.env; set +a
    cd /srv/prod/shopwatch/repo
    export SHOPWATCH_URL="http://$(docker inspect shopwatch --format \
        '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'):8477"
    /srv/prod/shopwatch/research-venv/bin/python deploy/research-runner.py --interval 10

NOT WIRED INTO opti YET. This file documents and implements the mechanism the plan
describes; it is reviewed here, deployed separately, deliberately.

Default-deny is enforced server-side (research.create_job only ever queues retailer ids
that already exist in shopwatch's own retailers table), so this script never has to
decide which domains are in scope - it only ever sees retailers the job itself named.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import time
from typing import Any

import requests

log = logging.getLogger("shopwatch.research_runner")

#: Per-retailer sub-timeout: one slow or hung retailer must not sink the whole job.
#: Matches the house convention already set by app/offers.py's own CLI timeouts.
RETAILER_TIMEOUT_SECONDS = 90

#: Hard ceiling for the whole job, independent of how many retailers it names. Backstops
#: app/research.py's own time-based staleness check (JOB_CEILING_SECONDS) from the other
#: side: if this script is still running past the point the server would have already
#: reconciled the job to FAILED, stop reporting into a job that no longer exists as RUNNING.
JOB_CEILING_SECONDS = 600

PROMPT = """You are researching the current price of one specific product at one
specific retailer, for a personal price-tracking tool. Use web search and read the
retailer's own site directly - do not guess or use general knowledge about typical
prices.

Product: {product_name}
Exact model: {model}
Retailer: {retailer_name}{homepage_hint}

Find this exact model's current price at this retailer only. If you cannot find this
exact model at this retailer (wrong model, no listing, the page blocks automated
access, or you are not confident it is the same product), say so - a wrong price is
worse than no price.

Return ONLY a JSON object, no prose, no code fence, matching this shape:
{{
  "found": true or false,
  "price": number or null (the advertised price, before freight),
  "stock": string or null (e.g. "In stock", "Out of stock"),
  "url": string or null (the product page you read),
  "reason": string (why not found, if found is false; brief confirmation if true)
}}
"""


class RunnerError(RuntimeError):
    """A retailer attempt failed in a way worth reporting as its own status."""

    def __init__(self, status: str, note: str) -> None:
        super().__init__(note)
        self.status = status
        self.note = note


def _last_json_object(raw: str, start: int) -> dict[str, Any]:
    """Scan for every complete JSON object at or after `start`, keeping the LAST one
    that parses. A reply with an earlier draft, worked example, or reference case
    followed by the real answer states the real one last in every case seen in
    practice; a stray brace in trailing prose (a parenthetical, a size list) is
    usually not valid JSON on its own and gets skipped. This does not guarantee
    semantic correctness when a reply genuinely contains two independently valid
    JSON objects, but matches every reproduced real-world pattern, where the later
    one was the intended answer. A code fence's backticks are not brace characters,
    so this also handles fenced replies (including two separately fenced blocks)
    without needing to strip fences first. RecursionError (pathological nesting) is
    treated the same as a parse failure: skip that candidate and keep looking.
    """
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None
    idx = start
    while True:
        brace = raw.find("{", idx)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(raw, brace)
        except (json.JSONDecodeError, RecursionError):
            idx = brace + 1
            continue
        best = obj
        idx = end
    if best is None:
        raise ValueError(f"reply was not valid JSON: no candidate object parsed ({raw[:150]!r})")
    return best


def parse_research_reply(raw: str) -> dict[str, Any]:
    """Pull the JSON object out of a CLI reply and validate it has a usable price.

    Kept separate from the subprocess call so it can be tested without running
    anything, same discipline as app/offers.py's parse_cli_output.
    """
    raw = (raw or "").strip()
    start = raw.find("{")
    if start == -1:
        raise RunnerError("NEEDS_MANUAL_CHECK", f"no JSON in reply: {raw[:150]!r}")
    try:
        data = _last_json_object(raw, start)
    except ValueError as exc:
        raise RunnerError("NEEDS_MANUAL_CHECK", str(exc)) from exc

    price = data.get("price")
    # bool is an int subclass in Python, and NaN is a float that survives an
    # `is None` check - both are real replies seen from a model that ignored the
    # requested shape, and both must not be treated as a usable price.
    price_is_usable = (
        isinstance(price, (int, float)) and not isinstance(price, bool)
        and math.isfinite(price)
    )
    if data.get("found") is not True or not price_is_usable:
        raise RunnerError("NEEDS_MANUAL_CHECK", str(data.get("reason") or "not found"))
    return data


def research_one_retailer(
    base_url: str,
    claude_bin: str,
    product_name: str,
    model: str,
    retailer_name: str,
    homepage: str | None,
) -> dict[str, Any]:
    """Ask the headless CLI about one retailer. Returns a parsed finding or raises RunnerError."""
    hint = f" ({homepage})" if homepage else ""
    prompt = PROMPT.format(
        product_name=product_name, model=model, retailer_name=retailer_name, homepage_hint=hint
    )
    try:
        proc = subprocess.run(
            [claude_bin, "-p"],
            input=prompt, capture_output=True, text=True, timeout=RETAILER_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RunnerError("NEEDS_MANUAL_CHECK", f"{claude_bin} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(
            "TIMED_OUT", f"no reply within {RETAILER_TIMEOUT_SECONDS}s"
        ) from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "non-zero exit")[:300]
        # A dead OAuth token (SECURITY.md's own documented failure mode) or a shared-quota
        # 429 both land here indistinguishably from stderr text - report the raw reason
        # rather than guessing, since guessing which one it was is exactly the "silence is
        # not a clean bill of health" trap.
        raise RunnerError("BLOCKED", f"claude exited {proc.returncode}: {stderr}")

    return parse_research_reply(proc.stdout)


def process_job(base_url: str, claude_bin: str, job: dict[str, Any]) -> None:
    product = requests.get(f"{base_url}/api/products/{job['product_id']}", timeout=30).json()
    deadline = time.monotonic() + JOB_CEILING_SECONDS

    for result in job["results"]:
        if time.monotonic() > deadline:
            log.warning("job %s hit its own ceiling; leaving the rest PENDING for the "
                        "server's own staleness check to resolve", job["id"])
            break
        retailer_name = result["retailer_name"]
        try:
            found = research_one_retailer(
                base_url, claude_bin, product["name"], product["model"],
                retailer_name, result.get("retailer_homepage"),
            )
        except RunnerError as exc:
            log.info("job %s / %s: %s (%s)", job["id"], retailer_name, exc.status, exc.note)
            requests.post(
                f"{base_url}/api/research-jobs/{job['id']}/results",
                json={"retailer_id": result["retailer_id"], "status": exc.status,
                      "note": exc.note[:300]},
                timeout=30,
            )
            continue

        imported = requests.post(
            f"{base_url}/api/import",
            json={"findings": [{
                "model": product["model"], "retailer": retailer_name,
                "price": found["price"], "stock": found.get("stock"),
                "url": found.get("url"), "source": "research-runner",
            }]},
            timeout=30,
        ).json()
        listing_id = None
        if imported.get("results"):
            listing_id = imported["results"][0]["listing_id"]
        log.info("job %s / %s: found $%s", job["id"], retailer_name, found["price"])
        requests.post(
            f"{base_url}/api/research-jobs/{job['id']}/results",
            json={"retailer_id": result["retailer_id"], "status": "FOUND",
                  "listing_id": listing_id, "note": found.get("reason", "")[:300]},
            timeout=30,
        )

    requests.post(f"{base_url}/api/research-jobs/{job['id']}/complete",
                   json={"status": "DONE"}, timeout=30)


def poll_once(base_url: str, claude_bin: str) -> bool:
    """Claim and fully process at most one job. Returns True if a job was found."""
    job = requests.post(f"{base_url}/api/research-jobs/claim", timeout=30).json()
    if job is None:
        return False
    log.info("claimed job %s for product %s", job["id"], job["product_id"])
    try:
        process_job(base_url, claude_bin, job)
    except Exception as exc:  # a crash here must not orphan the job silently
        log.exception("job %s crashed", job["id"])
        try:
            requests.post(
                f"{base_url}/api/research-jobs/{job['id']}/complete",
                json={"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"[:300]},
                timeout=30,
            )
        except Exception:
            # The server's own time-based staleness check (research.reconcile_stale) is
            # the backstop if even this report fails to land.
            log.exception("could not even report job %s as FAILED", job["id"])
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research-runner")
    parser.add_argument("--base-url", default=None,
                         help="defaults to $SHOPWATCH_URL")
    parser.add_argument("--claude-bin", default=None,
                         help="defaults to $CLAUDE_BIN or 'claude'")
    parser.add_argument("--interval", type=int, default=10,
                         help="seconds between polls when idle")
    parser.add_argument("--once", action="store_true",
                         help="process at most one job, then exit (for cron rather than a loop)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    import os
    base_url = args.base_url or os.environ.get("SHOPWATCH_URL")
    claude_bin = args.claude_bin or os.environ.get("CLAUDE_BIN", "claude")
    if not base_url:
        parser.error("--base-url or $SHOPWATCH_URL is required")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.once:
        poll_once(base_url, claude_bin)
        return 0

    log.info("polling %s every %ss", base_url, args.interval)
    while True:
        try:
            poll_once(base_url, claude_bin)
        except requests.RequestException as exc:
            log.warning("poll failed: %s", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
