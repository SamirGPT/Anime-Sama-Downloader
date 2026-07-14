"""Vidmoly extractor.

Strategy:
1. Fetch the embed page.
2. Look for `file:"https://...m3u8"` directly.
3. If not found, look for a `g=<hash>` parameter, fetch the same URL with
   that hash appended, and search again.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from src import network
from src.extractors.common import select_best_variant
from src.ui import print_status


def _find_file_in_html(html: str) -> Optional[str]:
    if not html:
        return None
    m = re.search(r'file\s*:\s*["\'](https?://[^"\']+)["\']', html)
    return m.group(1) if m else None


def _find_hash(html: str) -> Optional[str]:
    m = re.search(r'g=([a-f0-9]{32})', html)
    return m.group(1) if m else None


def extract_vidmoly(url: str) -> Optional[str]:
    referer = "https://vidmoly.net/"
    headers = {"Referer": referer}

    # Vidmoly sometimes shows a 'Please wait' page; retry a few times
    html = None
    for attempt in range(3):
        try:
            html = network.get_text(url, headers=headers, timeout=15)
        except Exception as e:
            print_status(f"Vidmoly fetch error (attempt {attempt+1}): {e}", "warning")
            html = None
        if html and "<title>Please wait" in html and "url.indexOf('?'" not in html:
            print_status(f"Vidmoly rate-limit — retry {attempt+1}/3", "warning")
            import time
            time.sleep(3)
            continue
        break

    if not html:
        return None

    source = _find_file_in_html(html)
    if not source:
        h = _find_hash(html)
        if h:
            try:
                html2 = network.get_text(f"{url}?g={h}", headers=headers, timeout=15)
                source = _find_file_in_html(html2)
            except Exception:
                pass

    if not source:
        print_status("Vidmoly: source introuvable", "warning")
        return None

    # `source` is typically a master.m3u8; pick the best variant
    if source.endswith(".m3u8") or "m3u8" in source:
        best = select_best_variant(source)
        return best or source
    return source
