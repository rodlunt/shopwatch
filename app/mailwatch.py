"""Read retailer marketing email and turn offers into leads on the board.

Runs on the machine where Thunderbird already lives, reading its local mail store
directly. There are no mail credentials anywhere in this: Thunderbird has already
fetched and stored the messages, and this only reads the files.

    python -m app.mailwatch --dry-run        # see what it would do, spend nothing
    python -m app.mailwatch                  # extract and post
    python -m app.mailwatch --since 2026-08-01 --limit 20

The watcher does not need to be more available than you are. If the lid is shut you are
not shopping that week either, which is why this is a laptop job and not a server one.
"""

from __future__ import annotations

import argparse
import email.header
import email.utils
import html
import json
import logging
import mailbox
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import offers
from .db import migrate, session, utcnow

log = logging.getLogger("shopwatch.mailwatch")

#: Senders worth reading. Anything else in the mailbox is ignored outright, which is
#: also the privacy boundary: personal mail is never opened or sent anywhere.
RETAILERS = {
    "jbhifi.com.au": "JB Hi-Fi",
    "email.jbhifi.com.au": "JB Hi-Fi",
    "thegoodguys.com.au": "The Good Guys",
    "email.thegoodguys.com.au": "The Good Guys",
    "harveynorman.com.au": "Harvey Norman",
    "appliancecentral.com.au": "Appliance Central",
    "binglee.com.au": "Bing Lee",
    "crowdshop.com.au": "Crowdshop",
}

#: Order-confirmation and account senders carry no offers and often carry personal
#: details, so they are skipped even though the domain matches.
SKIP_SUBDOMAINS = ("order.", "orders.", "receipt.", "noreply-account.")


def default_mailbox_paths() -> list[Path]:
    """Every Thunderbird mail file on this machine, newest profile first.

    Deliberately returns candidates rather than one path: Thunderbird keeps more than
    one profile and the live one is not always the one named 'default'.
    """
    root = Path(os.environ.get("SHOPWATCH_THUNDERBIRD", Path.home() / ".thunderbird"))
    if not root.exists():
        return []
    found = []
    for profile in root.iterdir():
        if not profile.is_dir():
            continue
        for store_dir in ("ImapMail", "Mail"):
            base = profile / store_dir
            if not base.exists():
                continue
            for account in base.iterdir():
                if not account.is_dir():
                    continue
                inbox = account / "INBOX"
                if inbox.is_file() and inbox.stat().st_size > 0:
                    found.append(inbox)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def body_text(message) -> str:
    """Readable text from a message, HTML flattened. Never raises on a bad part."""
    chunks: list[str] = []
    for part in message.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            raw = part.get_payload(decode=True) or b""
            text = raw.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if part.get_content_type() == "text/html":
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
        chunks.append(text)
    return re.sub(r"[ \t ]+", " ", "\n".join(chunks)).strip()


def retailer_for(sender: str) -> str | None:
    addr = email.utils.parseaddr(sender)[1].lower()
    if not addr or "@" not in addr:
        return None
    domain = addr.split("@", 1)[1]
    if any(domain.startswith(s) for s in SKIP_SUBDOMAINS):
        return None
    for suffix, name in RETAILERS.items():
        if domain == suffix or domain.endswith("." + suffix):
            return name
    return None


def received_at(message) -> str:
    raw = message.get("Date")
    if raw:
        try:
            return email.utils.parsedate_to_datetime(raw).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    return utcnow()


class ImapSource:
    """Read the account directly instead of Thunderbird's copy.

    Reuses the credential the /check-seek runner already has on opti, so nothing new
    is stored anywhere. Two things learned from that pipeline and repeated here:
    Trash is read alongside INBOX because Rodney swipe-deletes mail he has skimmed,
    and a malformed IMAP search returns an empty result set rather than an error, so
    a None result is treated as a failure and not as "no messages".
    """

    HOST = "imap.mail.me.com"

    def __init__(self, email_addr: str, password: str, folders: list[str] | None = None):
        self.email_addr = email_addr
        self.password = password
        self.folders = folders or [
            f.strip() for f in os.environ.get("ICLOUD_FOLDERS", "INBOX,Trash").split(",")
            if f.strip()
        ]

    def messages(self, since: str | None = None) -> Iterator[Any]:
        import email as email_mod
        import imaplib

        conn = imaplib.IMAP4_SSL(self.HOST, 993)
        try:
            conn.login(self.email_addr, self.password)
            for folder in self.folders:
                status, _ = conn.select(folder, readonly=True)
                if status != "OK":
                    log.warning("cannot open folder %s", folder)
                    continue
                # IMAP dates are unquoted; a malformed search yields None, not an error.
                criteria = "ALL"
                if since:
                    from datetime import datetime
                    when = datetime.strptime(since, "%Y-%m-%d").strftime("%d-%b-%Y")
                    criteria = f"(SINCE {when})"
                status, data = conn.search(None, criteria)
                if status != "OK" or not data or data[0] is None:
                    log.warning("search failed in %s (criteria %s)", folder, criteria)
                    continue
                for uid in data[0].split():
                    status, fetched = conn.fetch(uid, "(RFC822)")
                    if status != "OK" or not fetched or not fetched[0]:
                        continue
                    yield email_mod.message_from_bytes(fetched[0][1])
        finally:
            try:
                conn.logout()
            except Exception:
                pass


def imap_from_environment() -> ImapSource | None:
    """An ImapSource when the credential is present, else None. Never prompts."""
    addr = os.environ.get("ICLOUD_EMAIL", "").strip()
    password = os.environ.get("ICLOUD_APP_PASSWORD", "").strip()
    if addr and password:
        return ImapSource(addr, password)
    return None


@dataclass
class Candidate:
    message_id: str
    retailer: str
    sender: str
    subject: str
    received: str
    body: str


def mbox_messages(paths: list[Path]) -> Iterator[Any]:
    for path in paths:
        try:
            box = mailbox.mbox(str(path))
        except Exception as exc:
            log.warning("could not open %s: %s", path, exc)
            continue
        yield from box


def candidates(messages: Iterator[Any], since: str | None = None,
               limit: int | None = None) -> list[Candidate]:
    """Retailer messages worth a model call, newest first, de-duplicated by Message-ID."""
    seen: set[str] = set()
    found: list[Candidate] = []
    for message in messages:
        sender = str(message.get("From", ""))
        retailer = retailer_for(sender)
        if not retailer:
            continue
        mid = str(message.get("Message-ID") or "").strip()
        if not mid or mid in seen:
            continue
        when = received_at(message)
        if since and when[:10] < since:
            continue
        subject = str(message.get("Subject", ""))
        try:
            subject = str(email.header.make_header(email.header.decode_header(subject)))
        except Exception:
            pass
        body = body_text(message)
        if not offers.worth_extracting(subject, body):
            continue
        seen.add(mid)
        found.append(Candidate(mid, retailer, sender, subject, when, body))
    found.sort(key=lambda c: c.received, reverse=True)
    return found[:limit] if limit else found


@dataclass
class RunSummary:
    scanned: int = 0
    already_seen: int = 0
    extracted: int = 0
    not_offers: int = 0
    errors: list[str] = field(default_factory=list)
    recorded: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned, "already_seen": self.already_seen,
            "extracted": self.extracted, "not_offers": self.not_offers,
            "recorded": len(self.recorded), "errors": self.errors,
            "leads": [
                {"retailer": o["retailer_name"], "summary": o["summary"],
                 "confidence": o["confidence"],
                 "matches": [m["rationale"] for m in o["matches"]]}
                for o in self.recorded if o["matches"]
            ],
        }


class Sink:
    """Where offers go. Local for tests and single-machine use, remote for the real one.

    This matters: the mail lives on the laptop and the board lives on opti, so the
    default path has to be an HTTP post. Writing to a local SQLite file would file
    everything into a database nobody looks at, and nothing would ever say so.
    """

    def known_message_ids(self) -> set[str]:
        raise NotImplementedError

    def record(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError


class LocalSink(Sink):
    def __init__(self, conn) -> None:
        self.conn = conn

    def known_message_ids(self) -> set[str]:
        return {r["message_id"] for r in self.conn.execute("SELECT message_id FROM offers")}

    def record(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return offers.record_offer(self.conn, payload)


class ApiSink(Sink):
    """Posts to a running shopwatch. Credentials come from the environment only."""

    def __init__(self, base_url: str, user: str | None, password: str | None) -> None:
        import requests

        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        if user and password:
            self.session.auth = (user, password)

    def known_message_ids(self) -> set[str]:
        response = self.session.get(f"{self.base}/api/offers?live=false", timeout=30)
        response.raise_for_status()
        return {o["message_id"] for o in response.json()}

    def record(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        response = self.session.post(f"{self.base}/api/offers", json=payload, timeout=60)
        response.raise_for_status()
        body = response.json()
        return body.get("offer") if body.get("status") == "recorded" else None


def default_sink_config() -> tuple[str | None, str | None, str | None]:
    return (
        os.environ.get("SHOPWATCH_URL"),
        os.environ.get("SHOPWATCH_USER"),
        os.environ.get("SHOPWATCH_PASSWORD"),
    )


def run(paths: list[Path] | None = None, since: str | None = None,
        limit: int | None = None, dry_run: bool = False,
        model: str = offers.MODEL, client: Any = None,
        sink: Sink | None = None, source: Any = None,
        use_cli: bool = False, claude_bin: str = "claude") -> RunSummary:
    """One pass. `source` is anything yielding email.Message; defaults to the local mbox."""
    summary = RunSummary()
    if source is None:
        paths = paths or default_mailbox_paths()
        if not paths:
            summary.errors.append("no Thunderbird mail store found and no IMAP credential")
            return summary
        messages = mbox_messages(paths)
    else:
        messages = source.messages(since=since)

    with session() as conn:
        active = sink or LocalSink(conn)
        try:
            known = active.known_message_ids()
        except Exception as exc:
            summary.errors.append(f"could not reach the board: {type(exc).__name__}: {exc}")
            return summary
        for cand in candidates(messages, since=since, limit=limit):
            summary.scanned += 1
            if cand.message_id in known:
                summary.already_seen += 1
                continue
            if dry_run:
                continue

            if use_cli:
                result = offers.extract_via_cli(
                    cand.subject, cand.sender, cand.received, cand.body,
                    claude_bin=claude_bin,
                )
            else:
                result = offers.extract(
                    cand.subject, cand.sender, cand.received, cand.body,
                    client=client, model=model,
                )
            if result.error:
                summary.errors.append(f"{cand.subject[:50]}: {result.error}")
                continue
            summary.extracted += 1
            parsed = result.offer
            if parsed is None or not parsed.is_offer:
                summary.not_offers += 1
                continue

            recorded = active.record({
                "message_id": cand.message_id,
                "retailer_name": cand.retailer,
                "sender": cand.sender,
                "subject": cand.subject,
                "received_at": cand.received,
                "raw_excerpt": cand.body[:600],
                "extracted_by": result.model,
                **parsed.model_dump(),
            })
            if recorded:
                summary.recorded.append(recorded)

        conn.execute(
            "INSERT INTO mail_cursor (source, last_run_at, messages_seen)"
            " VALUES ('thunderbird', ?, ?)"
            " ON CONFLICT(source) DO UPDATE SET last_run_at = excluded.last_run_at,"
            " messages_seen = mail_cursor.messages_seen + excluded.messages_seen",
            (utcnow(), summary.scanned),
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.mailwatch")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be read; makes no API calls")
    parser.add_argument("--since", help="only messages on or after YYYY-MM-DD")
    parser.add_argument("--limit", type=int, help="stop after N candidates")
    parser.add_argument("--model", default=offers.MODEL)
    parser.add_argument("--mailbox", action="append", type=Path,
                        help="explicit mail file; repeatable")
    parser.add_argument("--imap", action="store_true",
                        help="read the account directly (ICLOUD_EMAIL / ICLOUD_APP_PASSWORD)")
    parser.add_argument("--cli", action="store_true",
                        help="extract with headless Claude Code instead of the API; needs no key")
    parser.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"))
    parser.add_argument("--local", action="store_true",
                        help="write to the local database instead of posting to the board")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    migrate()

    sink = None
    url, user, password = default_sink_config()
    if not args.local and url:
        sink = ApiSink(url, user, password)
        log.info("posting offers to %s", url)
    elif not args.local and not args.dry_run:
        print("SHOPWATCH_URL is not set, so there is nowhere to send what this finds.\n"
              "Set it (plus SHOPWATCH_USER and SHOPWATCH_PASSWORD), or pass --local to\n"
              "write into the database this machine can see.", file=sys.stderr)
        return 2

    source = None
    if args.imap:
        source = imap_from_environment()
        if source is None:
            print("--imap needs ICLOUD_EMAIL and ICLOUD_APP_PASSWORD in the environment.",
                  file=sys.stderr)
            return 2
        log.info("reading %s over IMAP", source.email_addr)

    summary = run(paths=args.mailbox, since=args.since, limit=args.limit,
                  dry_run=args.dry_run, model=args.model, sink=sink, source=source,
                  use_cli=args.cli, claude_bin=args.claude_bin)

    if args.json:
        print(json.dumps(summary.as_dict(), indent=2))
    else:
        d = summary.as_dict()
        print(f"scanned {d['scanned']} (seen before {d['already_seen']}), "
              f"extracted {d['extracted']}, not offers {d['not_offers']}, "
              f"recorded {d['recorded']}, errors {len(d['errors'])}")
        for lead in d["leads"]:
            print(f"\n  {lead['retailer']} [{lead['confidence']}] {lead['summary']}")
            for rationale in lead["matches"]:
                print(f"    -> {rationale}")
        for err in d["errors"][:5]:
            print(f"  ERROR {err}", file=sys.stderr)

    return 1 if summary.errors and not summary.recorded else 0


if __name__ == "__main__":
    raise SystemExit(main())
