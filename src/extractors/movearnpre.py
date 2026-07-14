"""Movearnpre / Smoothpre / Mivalyo / Dingtezuni family extractor.

All these players serve a packed-JS page that resolves to a /stream/...
master.m3u8 URL. We share one implementation.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse

from src.extractors.common import fetch_and_unpack, find_m3u8_in_code, select_best_variant
from src.ui import print_status


def extract_movearnpre_family(url: str) -> Optional[str]:
    """Extract the best-variant m3u8 from a packed-JS embed page."""
    # Derive embed root for referer
    referer = None
    if "/embed/" in url:
        referer = url.split("/embed/")[0] + "/"

    unpacked = fetch_and_unpack(url, referer=referer)
    if not unpacked:
        print_status("Movearnpre-family: unpack échoué", "warning")
        return None

    m3u8 = find_m3u8_in_code(unpacked)
    if not m3u8:
        print_status("Movearnpre-family: m3u8 introuvable", "warning")
        return None

    # Absolutize
    if m3u8.startswith("http"):
        master_url = m3u8
    elif m3u8.startswith("/"):
        p = urlparse(url)
        master_url = f"{p.scheme}://{p.netloc}{m3u8}"
    else:
        master_url = urljoin(url, m3u8)

    # Pick best variant
    best = select_best_variant(master_url)
    return best or master_url
