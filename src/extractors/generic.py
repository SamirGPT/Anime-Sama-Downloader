"""Generic MP4 extractor for hosts that expose the video URL in HTML/JS.

Used by: Mixdrop, Vidoza, Upstream, Streamlare, HubCloud, and other
"simple" hosts that embed the video URL in JavaScript.

Strategy:
1. Fetch the page HTML
2. Search for common patterns:
   - sources: ["https://...mp4"]
   - file: "https://...mp4"
   - src: "https://...mp4"
   - <source src="...">
   - <video src="...">
3. Return the first MP4 URL found
"""
from __future__ import annotations

import re
from typing import Optional, List

from src import network
from src.ui import print_status, print_debug


# Patterns to try, in order of preference (most reliable first)
_MP4_PATTERNS = [
    # JavaScript patterns
    r'sources\s*:\s*\["(https?://[^"]+\.mp4[^"]*)"\]',
    r'sources\s*:\s*\[\s*"(https?://[^"]+)"\s*\]',
    r'file\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
    r'file\s*:\s*"(https?://[^"]+)"',
    r'src\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
    r'"file"\s*:\s*"(https?://[^"]+)"',
    r'"src"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
    r'videoUrl\s*=\s*"(https?://[^"]+)"',
    r'url\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
    # HTML patterns
    r'<source[^>]+src="(https?://[^"]+\.mp4[^"]*)"',
    r'<source[^>]+src="(https?://[^"]+)"',
    r'<video[^>]+src="(https?://[^"]+\.mp4[^"]*)"',
    r'<video[^>]+src="(https?://[^"]+)"',
    # Generic catch-all (last resort)
    r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
]


def extract_generic_mp4(url: str, referer: Optional[str] = None,
                        patterns: Optional[List[str]] = None) -> Optional[str]:
    """Extract a direct MP4 URL from a generic video host page.

    Args:
        url: The embed/page URL to fetch.
        referer: Optional referer header.
        patterns: Custom regex patterns to try (defaults to _MP4_PATTERNS).

    Returns:
        The direct MP4 URL, or None if not found.
    """
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr-FR;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    else:
        # Use the embed site root as referer
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            headers["Referer"] = f"{p.scheme}://{p.netloc}/"
        except Exception:
            pass

    try:
        html = network.get_text(url, headers=headers, timeout=15)
    except Exception as e:
        print_status(f"Erreur fetch: {e}", "error")
        return None

    if not html:
        return None

    patterns = patterns or _MP4_PATTERNS
    for pattern in patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            mp4_url = m.group(1)
            print_debug(f"Matched pattern: {pattern[:50]}... → {mp4_url[:80]}")
            # Basic validation
            if mp4_url.startswith("http"):
                return mp4_url

    print_debug("No MP4 URL found in page")
    return None
