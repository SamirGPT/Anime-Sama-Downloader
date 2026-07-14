"""Fetch episodes.js from an anime-sama season page and parse player arrays."""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from src import network
from src.cloudflare import get_anime_sama_headers
from src.ui import print_status


def fetch_episodes(base_url: str, headers: Optional[Dict] = None
                   ) -> Optional[Dict[str, List[str]]]:
    """Return {player_name: [url1, url2, ...]} from episodes.js.

    Returns None on network failure. Empty dict if no episodes found.
    """
    js_url = base_url.rstrip('/') + '/episodes.js'
    headers = headers or get_anime_sama_headers()
    print_status(f"Récupération des épisodes...", "loading")
    try:
        text = network.get_text(js_url, headers=headers, timeout=15)
    except Exception as e:
        print_status(f"Échec episodes.js: {e}", "error")
        return None

    pattern = re.compile(r'var\s+(eps\d+)\s*=\s*\[([^\]]*)\];', re.MULTILINE)
    matches = pattern.findall(text)
    episodes: Dict[str, List[str]] = {}
    for name, content in matches:
        n = re.search(r'\d+', name).group()
        player = f"Player {n}"
        urls = re.findall(r"'(https?://[^']+)'", content)
        episodes[player] = urls

    if episodes:
        total_eps = max(len(v) for v in episodes.values())
        print_status(f"{len(episodes)} joueurs — {total_eps} épisodes max", "success")
    else:
        print_status("Aucun épisode trouvé dans episodes.js", "warning")
    return episodes
