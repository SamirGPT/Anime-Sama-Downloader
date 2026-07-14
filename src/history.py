"""Download history — track what was downloaded for resume & stats.

Stores a simple JSON Lines file at ~/.local/share/anime-sama/history.jsonl
(or $XDG_DATA_HOME/anime-sama/history.jsonl).

Each line: {"anime": "...", "episode": N, "path": "...", "timestamp": ...,
             "site": "...", "url": "..."}
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def _history_path() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "anime-sama" / "history.jsonl"
    return Path.home() / ".local" / "share" / "anime-sama" / "history.jsonl"


def record_download(anime: str, episode, path: str,
                    site: str = "anime-sama", url: str = "") -> None:
    """Append a download record to history."""
    p = _history_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "anime": anime,
            "episode": episode,
            "path": path,
            "site": site,
            "url": url,
            "timestamp": datetime.now().isoformat(),
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # never fail a download because of history


def list_history(limit: int = 50,
                 anime_filter: Optional[str] = None) -> List[dict]:
    """Read history, return most-recent first."""
    p = _history_path()
    if not p.exists():
        return []
    records = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if anime_filter and anime_filter.lower() not in r.get("anime", "").lower():
                        continue
                    records.append(r)
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    # Most recent first
    records.reverse()
    return records[:limit]


def clear_history() -> int:
    """Clear history. Returns the number of records removed."""
    p = _history_path()
    if not p.exists():
        return 0
    try:
        count = sum(1 for _ in open(p, "r", encoding="utf-8"))
        p.unlink()
        return count
    except Exception:
        return 0


def stats() -> dict:
    """Return download stats: total, by_anime, by_site."""
    p = _history_path()
    if not p.exists():
        return {"total": 0, "by_anime": {}, "by_site": {}}
    total = 0
    by_anime = {}
    by_site = {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line.strip())
                    total += 1
                    a = r.get("anime", "unknown")
                    by_anime[a] = by_anime.get(a, 0) + 1
                    s = r.get("site", "unknown")
                    by_site[s] = by_site.get(s, 0) + 1
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return {"total": total, "by_anime": by_anime, "by_site": by_site}
