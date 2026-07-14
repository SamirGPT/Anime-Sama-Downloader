"""OneUpload extractor — looks for jwplayer `file:"..."` in HTML."""
from __future__ import annotations

import re
from typing import Optional

from src import network
from src.extractors.common import select_best_variant
from src.ui import print_status


def extract_oneupload(url: str) -> Optional[str]:
    referer = "https://oneupload.net/"
    headers = {"Referer": referer}
    try:
        html = network.get_text(url, headers=headers, timeout=15)
    except Exception as e:
        print_status(f"OneUpload fetch error: {e}", "error")
        return None

    m = re.search(r'file:"(https?://[^"]+)"', html)
    if not m:
        # Try single-quote variant
        m = re.search(r"file:'(https?://[^']+)'", html)
    if not m:
        print_status("OneUpload: source introuvable", "warning")
        return None

    source = m.group(1)
    if "m3u8" in source:
        best = select_best_variant(source)
        return best or source
    return source
