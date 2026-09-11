"""Render an email's HTML to a screenshot, so the offer inside the artwork can be read.

Retailer marketing email puts the numbers in pictures. On a live Good Guys email the
extracted text contains "20%" but not "Ends", not "13/09/2026" and not "11.59" - those
are pixels. No amount of parsing gets them; a render does.

Two things this cannot do, both learned by trying:

* **It only works while the offer is live.** The hero images are served from a live URL
  and swapped when the offer ends, so rendering an old email shows "This offer has
  ended" rather than what it once said. Useless for a backfill, fine for a daily job.
* **It cannot avoid the tracking pixel.** The images carry the offer, so they must load,
  and loading them tells the retailer the mail was opened.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("shopwatch.render")

#: Headless Chrome in a container: nothing to install on the host, and it cannot see
#: anything outside the directory handed to it.
CHROME_IMAGE = os.environ.get("SHOPWATCH_CHROME_IMAGE", "zenika/alpine-chrome:latest")

#: Tall enough for the hero artwork and the first screen of fine print, which is where
#: the amount and the expiry live. Rendering 6,000px of product grid buys nothing and
#: costs tokens.
WIDTH = int(os.environ.get("SHOPWATCH_RENDER_WIDTH", "900"))
HEIGHT = int(os.environ.get("SHOPWATCH_RENDER_HEIGHT", "3200"))


class RenderError(RuntimeError):
    """Rendering failed. The caller keeps whatever the text pass produced."""


def available() -> bool:
    """Is there a docker to render with? Checked so the caller can skip quietly."""
    return shutil.which("docker") is not None


def render_html(html: str, timeout: int = 120) -> Path:
    """Render HTML to a PNG and return its path. The caller owns the file.

    The work directory is world-writable on purpose: the container runs as its own
    user and has to write the screenshot back out. It holds one email for a few
    seconds and is removed by the caller.
    """
    if not available():
        raise RenderError("docker is not available on this machine")

    workdir = Path(tempfile.mkdtemp(prefix="shopwatch-render-"))
    try:
        os.chmod(workdir, 0o777)
        (workdir / "email.html").write_text(html, encoding="utf-8", errors="replace")
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{workdir}:/data",
                CHROME_IMAGE,
                "--no-sandbox", "--headless", "--disable-gpu", "--hide-scrollbars",
                f"--window-size={WIDTH},{HEIGHT}",
                "--screenshot=/data/shot.png",
                "file:///data/email.html",
            ],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise RenderError(f"chrome timed out after {timeout}s") from exc
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise RenderError(f"{type(exc).__name__}: {exc}") from exc

    shot = workdir / "shot.png"
    if not shot.exists() or shot.stat().st_size == 0:
        shutil.rmtree(workdir, ignore_errors=True)
        # Chrome writes its real complaint to stderr amid a wall of GPU warnings.
        tail = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise RenderError(f"no screenshot produced: {tail[0][:160]}")
    log.debug("rendered %d bytes to %s", shot.stat().st_size, shot)
    return shot


def cleanup(shot: Path) -> None:
    """Remove the screenshot and its directory. One-use artefact, gone when read."""
    try:
        shutil.rmtree(shot.parent, ignore_errors=True)
    except Exception:
        pass
