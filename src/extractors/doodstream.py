"""Doodstream extractor.

Doodstream uses a two-step process:
1. Extract video ID from URL (e.g. /e/abc123 or /d/abc123)
2. Call the API: https://doodstream.com/api/pass_md5/REFERRER/VIDEO_ID
3. Get the pass_md5 token, then construct the final URL with a random
   user-agent string suffix.

Returns a direct MP4 URL.
"""
from __future__ import annotations

import re
import random
import string
from typing import Optional

from src import network
from src.ui import print_status, print_debug


def extract_doodstream(url: str) -> Optional[str]:
    """Extract direct MP4 URL from a Doodstream embed URL."""
    # Extract video ID from various URL formats:
    # - https://doodstream.com/e/abc123
    # - https://dood.so/d/abc123
    # - https://doodstream.com/d/abc123
    m = re.search(r'/(?:e|d)/([a-zA-Z0-9]+)', url)
    if not m:
        # Try /watch/ pattern
        m = re.search(r'/watch/([a-zA-Z0-9]+)', url)
    if not m:
        print_status("Doodstream: ID vidéo introuvable", "warning")
        return None

    video_id = m.group(1)

    # Determine the domain (doodstream.com, dood.so, etc.)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or "doodstream.com"
    if not domain:
        domain = "doodstream.com"

    # Step 1: Get the page to find the API token
    headers = {
        "Referer": f"https://{domain}/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = network.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print_status(f"Doodstream HTTP {r.status_code}", "warning")
            return None
        html = r.text
    except Exception as e:
        print_status(f"Doodstream fetch error: {e}", "error")
        return None

    # Look for the pass_md5 API call in the HTML
    # Pattern: $.get('https://doodstream.com/api/pass_md5/REF/VIDEO_ID', ...)
    # or: pass_md5('/api/pass_md5/REF/VIDEO_ID')
    api_m = re.search(
        r'(?:https?:)?//[^"\']+/(?:api/)?pass_md5/([a-zA-Z0-9]+)/' + re.escape(video_id),
        html,
    )
    if not api_m:
        # Try alternative pattern: data-token="..."
        api_m = re.search(r'data-token\s*=\s*"([a-zA-Z0-9]+)"', html)
        if api_m:
            ref = api_m.group(1)
        else:
            print_debug("Doodstream: pass_md5 reference not found")
            return None
    else:
        ref = api_m.group(1)

    # Step 2: Call the API to get the pass_md5 token
    api_url = f"https://{domain}/api/pass_md5/{ref}/{video_id}"
    try:
        api_r = network.get(api_url, headers=headers, timeout=10)
        if api_r.status_code != 200:
            print_status(f"Doodstream API HTTP {api_r.status_code}", "warning")
            return None
        pass_md5 = api_r.text.strip()
        if not pass_md5 or len(pass_md5) < 10:
            print_status("Doodstream: token invalide", "warning")
            return None
    except Exception as e:
        print_status(f"Doodstream API error: {e}", "error")
        return None

    # Step 3: Construct the final URL
    # Format: https://{domain}/pass_md5/{pass_md5}?token={ref}&expiry=...
    # Need a random 10-char string for the URL suffix
    random_suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    # Look for expiry in the HTML
    expiry_m = re.search(r'expiry\s*[:=]\s*"?(\d+)"?', html)
    expiry = expiry_m.group(1) if expiry_m else ""

    final_url = (
        f"https://{domain}/pass_md5/{pass_md5}/{random_suffix}"
        f"?token={ref}&expiry={expiry}"
    )
    print_debug(f"Doodstream final URL: {final_url[:80]}")
    return final_url
