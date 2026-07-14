"""Sibnet extractor.

Parses the embed page to find `player.src([{src:"..."}])`, then follows
the 302 redirect to get the direct .mp4 URL.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from src import network
from src.ui import print_status


SIBNET_HOME = "https://video.sibnet.ru/"


def extract_sibnet(url: str) -> Optional[str]:
    try:
        html = network.get_text(url, headers={"Referer": SIBNET_HOME}, timeout=15)
    except Exception as e:
        print_status(f"Sibnet fetch error: {e}", "error")
        return None

    # Find player.src( ... src: "..." ...)
    m = re.search(r'player\.src\(\[?\{.*?src:\s*"([^"]+)"', html, re.DOTALL)
    if not m:
        print_status("Sibnet: player.src introuvable", "warning")
        return None

    src = m.group(1)
    if src.startswith("//"):
        src = "https:" + src
    elif not src.startswith("https://"):
        src = f"https://video.sibnet.ru{src}"

    # Follow 302 redirect to get the actual .mp4
    try:
        r = network.get(
            src,
            headers={
                "Referer": SIBNET_HOME,
                "Accept": "video/webm,video/mp4,video/*;q=0.9,*/*;q=0.8",
            },
            allow_redirects=False,
            timeout=15,
        )
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location", "")
            if loc.startswith("//"):
                loc = "https:" + loc
            return loc
        # Some servers return 200 with the actual content (rare)
        if r.status_code == 200:
            return src
        print_status(f"Sibnet: statut inattendu {r.status_code}", "warning")
        return None
    except Exception as e:
        print_status(f"Sibnet redirect error: {e}", "error")
        return None
