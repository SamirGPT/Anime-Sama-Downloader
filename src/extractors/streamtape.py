"""Streamtape extractor.

Streamtape exposes the video URL via a pattern in the HTML:
- Look for `get_video_url` or `video_url` JavaScript variable
- Pattern: id=...&stream=... concatenated with a robotproof suffix

Simplified approach: parse the HTML for the URL pattern.
"""
from __future__ import annotations

import re
from typing import Optional

from src import network
from src.ui import print_status, print_debug
from .generic import extract_generic_mp4


def extract_streamtape(url: str) -> Optional[str]:
    """Extract direct MP4 URL from a Streamtape embed URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or "streamtape.com"

    headers = {
        "Referer": f"https://{domain}/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        r = network.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            # Try with the generic extractor as fallback
            return extract_generic_mp4(url, referer=f"https://{domain}/")
        html = r.text
    except Exception:
        return extract_generic_mp4(url, referer=f"https://{domain}/")

    # Streamtape pattern: var video_url = "..." + robotproof substring
    # Or: get_video_url("id=xxx&stream=xxx&...")
    # Try the regex approach first
    m = re.search(
        r'get_video_url\s*\(\s*["\']([^"\']+)["\']\s*\)',
        html,
    )
    if m:
        url_fragment = m.group(1)
        # The full URL is built as: https://{domain}/e/...?{fragment}
        # Actually the fragment IS the relative URL
        if url_fragment.startswith("/"):
            return f"https://{domain}{url_fragment}"
        if not url_fragment.startswith("http"):
            return f"https://{domain}/{url_fragment}"
        return url_fragment

    # Alternative pattern: <script>document.getElementById('ideoo').innerHTML = '<a href="URL">'
    m = re.search(
        r"innerHTML\s*=\s*['\"]<a[^>]+href=['\"]([^'\"]+)['\"]",
        html,
    )
    if m:
        u = m.group(1)
        if u.startswith("http"):
            return u
        return f"https://{domain}{u}"

    # Fallback: try generic MP4 patterns
    return extract_generic_mp4(url, referer=f"https://{domain}/")
