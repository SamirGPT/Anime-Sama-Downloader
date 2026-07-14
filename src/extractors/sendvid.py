"""SendVid extractor — looks for `var video_source = "..."` in HTML."""
from __future__ import annotations

import re
from typing import Optional

from src import network
from src.ui import print_status


def extract_sendvid(url: str) -> Optional[str]:
    try:
        html = network.get_text(url, timeout=15)
    except Exception as e:
        print_status(f"SendVid fetch error: {e}", "error")
        return None
    m = re.search(r'var\s+video_source\s*=\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    # Fallback: look for source src=
    m = re.search(r'<source[^>]+src="([^"]+)"', html)
    if m:
        return m.group(1)
    print_status("SendVid: source vidéo introuvable", "warning")
    return None
