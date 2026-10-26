#!/usr/bin/env python3
"""Add the Raspberry Pi 3 Model B+ (2018, 1GB) to the Pi watch through the running API.

Idempotent: reuses the product if one with this model already exists, and the API
reuses a listing it already has for the same URL. Sets no target price (the owner
decides). Each listing is read once, live, by the retailer's adapter; a listing the
adapter could not read is printed as UNREAD and stays on the board as unverified, never
as a quiet success.

    python tools/add_pi3_bplus.py [--base http://127.0.0.1:8477]

Run it on opti (or anywhere that can reach the API). Not the 2014 Model B+, and not the
plain 2016 Pi 3 Model B: the adapters refuse a page that names either.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

MODEL = "Raspberry Pi 3 Model B+"
NOTES = (
    "Pi 3 Model B+ (2018, BCM2837B0, 1GB, SC0073). Not the 2014 Model B+ and not the plain "
    "Pi 3 Model B. Checked 2026-10-27: no retailer page says discontinued, but PB Tech's "
    "page promises production only 'until at least January 2023' (past), PB Tech is out of "
    "stock and Pakronics is out of stock. Not confirmed discontinued by Raspberry Pi Ltd. "
    "Zaitronics and Small Devices list no Pi 3 B+ board (cases and accessories only). "
    "No target price set."
)
LISTINGS = [
    "https://core-electronics.com.au/raspberry-pi-3-model-b-plus.html",
    "https://littlebirdelectronics.com.au/products/raspberry-pi-3-model-b-plus",
    "https://piaustralia.com.au/products/raspberry-pi-3-model-b-plus",
    "https://www.pakronics.com.au/products/raspberry-pi3-model-b-rpi-sc0073",
    "https://www.pbtech.com/au/product/SEVRBP0126/Raspberry-Pi-3-Model-B-Quad-Core-14G-WIFI-Dual-ban",
]


def call(base: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path} -> HTTP {exc.code}: {exc.read().decode()[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8477")
    base = ap.parse_args().base.rstrip("/")

    products = call(base, "GET", "/api/products")
    products = products.get("products", products) if isinstance(products, dict) else products
    found = next(
        (p for p in products if (p.get("model") or "").strip().lower() == MODEL.lower()), None
    )
    if found:
        pid = found["id"]
        print(f"product exists: id {pid}")
    else:
        made = call(base, "POST", "/api/products", {
            "name": MODEL, "model": MODEL, "brand": "Raspberry Pi", "category": "Barkmarker",
            "verdict": "MAYBE", "status": "ACTIVE", "notes": NOTES,
        })
        pid = made["id"]
        print(f"product created: id {pid}")

    for url in LISTINGS:
        got = call(base, "POST", f"/api/products/{pid}/retailers/from-url", {"url": url})
        listing = got.get("listing", got)
        price = listing.get("advertised_price")
        if price:
            print(f"OK     {url}\n       price {price}, stock {listing.get('stock_status')!r}")
        else:
            print(f"UNREAD {url}\n       no reading; the watcher will retry and report it")


if __name__ == "__main__":
    main()
