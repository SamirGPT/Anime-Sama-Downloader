"""Small shared utilities (path sanitization, slug, etc.)."""
from __future__ import annotations

import os
import re
import platform
import sys
from pathlib import Path
from typing import Optional


def sanitize_filename(name: str) -> str:
    """Remove characters not safe for filenames on Linux/Termux."""
    if not name:
        return "unknown"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = name.strip().rstrip('.')
    name = re.sub(r'\s+', ' ', name)
    return name or "unknown"


def get_default_max_workers() -> int:
    """Heuristic for max_workers based on environment.
    
    Termux (Android) → 3 (limited resources)
    Low-core Linux   → 4
    Otherwise        → 5
    """
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix:
        return 3
    try:
        import os as _os
        n = _os.cpu_count() or 4
        return min(5, max(2, n - 1))
    except Exception:
        return 4


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


def is_ubuntu() -> bool:
    try:
        with open("/etc/os-release") as f:
            return "ubuntu" in f.read().lower()
    except Exception:
        return False


def ffmpeg_path() -> Optional[str]:
    """Locate ffmpeg binary."""
    import shutil
    return shutil.which("ffmpeg")


def avconv_path() -> Optional[str]:
    """Locate avconv (rare, but exists)."""
    import shutil
    return shutil.which("avconv")


def expand_path(path: str) -> str:
    """Expand ~ and env vars in a path."""
    return os.path.expandvars(os.path.expanduser(path))


def extract_anime_name(url: str) -> str:
    """Extract the anime slug from an anime-sama URL."""
    m = re.search(r'catalogue/([^/]+)/', url)
    return m.group(1) if m else "unknown"


def extract_season_slug(url: str) -> str:
    """Extract the season slug (e.g. 'saison1') from URL."""
    parts = [p for p in url.rstrip('/').split('/') if p]
    if len(parts) >= 2:
        return parts[-2] if parts[-1] in ("vostfr", "vf") else parts[-1]
    return "season1"


def format_save_path(template: str, anime: str, season: str, base: Optional[str] = None) -> str:
    """Format a save path from a template."""
    try:
        formatted = template.format(anime=anime, season=season)
    except (KeyError, IndexError):
        formatted = f"./videos/{anime}/{season}"
    if base:
        return os.path.join(base, anime, season)
    return os.path.normpath(formatted)
