"""Uqload extractor — FIXES the original bug.

The original code called `fetch_html_for_ts(embed_url, headers=headers)`
but `fetch_html_for_ts` only accepted one argument, so Uqload was
completely broken. We now use the shared `fetch_and_unpack` helper.
"""
from __future__ import annotations

from typing import Optional

from src.extractors.common import fetch_and_unpack, find_m3u8_in_code
from src.ui import print_status


def extract_uqload(url: str) -> Optional[str]:
    """Extract direct m3u8 URL from a Uqload embed page."""
    try:
        parsed_url = url
        # Use the embed root as referer
        referer = url.split("/embed/")[0] + "/" if "/embed/" in url else None
        unpacked = fetch_and_unpack(parsed_url, referer=referer)
    except Exception as e:
        print_status(f"Uqload fetch error: {e}", "error")
        return None

    if not unpacked:
        # Fallback: try direct regex on raw HTML
        try:
            from src import network
            html = network.get_text(url, timeout=15)
            m = find_m3u8_in_code(html)
            if m:
                return _absolutize(m, url)
        except Exception:
            pass
        print_status("Uqload: aucun m3u8 trouvé", "warning")
        return None

    m3u8 = find_m3u8_in_code(unpacked)
    if not m3u8:
        print_status("Uqload: m3u8 absent du code unpacked", "warning")
        return None
    return _absolutize(m3u8, url)


def _absolutize(m3u8: str, base_url: str) -> str:
    """Convert a relative m3u8 path to absolute."""
    if m3u8.startswith("http"):
        return m3u8
    if m3u8.startswith("//"):
        return "https:" + m3u8
    if m3u8.startswith("/"):
        from urllib.parse import urlparse
        p = urlparse(base_url)
        return f"{p.scheme}://{p.netloc}{m3u8}"
    # Relative path
    from urllib.parse import urljoin
    return urljoin(base_url, m3u8)
