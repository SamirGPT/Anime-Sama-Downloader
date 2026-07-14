"""MyAnimeList integration (optional, via Jikan public API).

Creates a `.match` file in the save directory to remember the MAL ID
for an anime. Skipped entirely when `--no-mal` is set.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Dict, Optional

from src import network
from src.ui import Colors, print_separator, print_status, prompt


_cache: Dict[str, Optional[dict]] = {}
_cache_lock = threading.Lock()


def _normalize(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"[^\w\s]", "", str(text).lower().strip())


def _is_movie_title(title: str) -> bool:
    if not title:
        return False
    t = title.lower()
    return any(k in t for k in ("movie", "film", "le film"))


def _clean_anime_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r'\s*\(.*?\)\s*', '', name)
    name = re.sub(r'\s*\[.*?\]\s*', '', name)
    name = re.sub(r'\s*-\s*saison\s*\d+.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*-\s*season\s*\d+.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*s\d+.*', '', name, flags=re.IGNORECASE)
    return name.strip()


def _best_title(anime: dict) -> str:
    titles = anime.get("titles", [])
    for t in titles:
        if t.get("type") == "English":
            return t.get("title") or ""
    for t in titles:
        if t.get("type") == "Default":
            return t.get("title") or ""
    if titles:
        return titles[0].get("title") or ""
    return anime.get("title") or "Unknown"


def _search_jikan(query: str) -> list:
    """Query Jikan v4 with simple 429 retry."""
    url = f"https://api.jikan.moe/v4/anime?q={query}&limit=20"
    for attempt in range(5):
        try:
            r = network.get(url, timeout=15)
            if r.status_code == 429:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception as e:
            print_status(f"Jikan error: {e}", "warning")
            return []
    return []


def _interactive_select(candidates: list, query: str) -> Optional[dict]:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    print(f"\n{Colors.BOLD}{Colors.HEADER}Plusieurs résultats MAL pour '{query}':{Colors.ENDC}")
    print_separator()
    display = candidates[:10]
    for i, a in enumerate(display, 1):
        t = _best_title(a)
        ty = a.get("type") or "?"
        mid = a.get("mal_id") or "?"
        print(f"{Colors.OKGREEN}[{i}]{Colors.ENDC} {Colors.BOLD}{t}{Colors.ENDC} ({ty}, MAL #{mid})")
    print(f"{Colors.OKGREEN}[0]{Colors.ENDC} Aucun (skip)")
    while True:
        raw = prompt(f"Choix [0-{len(display)}]: ")
        try:
            n = int(raw)
            if n == 0:
                return None
            if 1 <= n <= len(display):
                return display[n - 1]
        except ValueError:
            pass
        print_status("Invalide", "error")


def search_anime_on_mal(anime_name: str, interactive: bool = True) -> Optional[dict]:
    """Return {mal_id, title, type} or None."""
    cache_key = anime_name.lower().strip()
    with _cache_lock:
        if cache_key in _cache:
            return _cache[cache_key]

    cleaned = _clean_anime_name(anime_name)
    queries = [cleaned] + ([anime_name] if cleaned != anime_name else [])

    all_results = []
    seen_ids = set()
    for q in queries:
        for a in _search_jikan(q):
            if a.get("mal_id") in seen_ids:
                continue
            seen_ids.add(a.get("mal_id"))
            all_results.append(a)

    if not all_results:
        with _cache_lock:
            _cache[cache_key] = None
        return None

    # Try exact match first
    norm_target = _normalize(anime_name)
    for a in all_results:
        for t in a.get("titles", []):
            if _normalize(t.get("title")) == norm_target:
                result = {"mal_id": a.get("mal_id"),
                          "title": _best_title(a),
                          "type": a.get("type")}
                with _cache_lock:
                    _cache[cache_key] = result
                return result

    # Otherwise: prefer TV/ONA, then interactive or first
    tv = [a for a in all_results
          if (a.get("type") or "").lower() in ("tv", "ona")]
    candidates = tv if tv and not _is_movie_title(anime_name) else all_results

    if interactive:
        selected = _interactive_select(candidates, anime_name)
        if selected:
            result = {"mal_id": selected.get("mal_id"),
                      "title": _best_title(selected),
                      "type": selected.get("type")}
        else:
            result = None
    else:
        first = candidates[0] if candidates else all_results[0]
        result = {"mal_id": first.get("mal_id"),
                  "title": _best_title(first),
                  "type": first.get("type")}

    with _cache_lock:
        _cache[cache_key] = result
    return result


def create_match_file(save_dir: str, anime_name: str,
                      interactive: bool = True) -> None:
    """Create a .match file in save_dir with MAL metadata."""
    with _cache_lock:
        if anime_name.lower().strip() in _cache:
            return  # already processed

    match_path = os.path.join(save_dir, ".match")
    if os.path.exists(match_path):
        # Load existing
        try:
            with open(match_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('mal-id:'):
                        mid = line.split(':', 1)[1].strip()
                        if mid != 'unknown':
                            with _cache_lock:
                                _cache[anime_name.lower().strip()] = {"mal_id": int(mid)}
                            return
        except Exception:
            pass
        return

    print_separator()
    print(f"{Colors.BOLD}{Colors.HEADER}Recherche MAL...{Colors.ENDC}")
    data = search_anime_on_mal(anime_name, interactive=interactive)
    try:
        with open(match_path, 'w', encoding='utf-8') as f:
            if data:
                f.write(f"title: {data['title']}\n")
                f.write(f"mal-id: {data['mal_id']}\n")
                print_status(f"Match: {data['title']} (MAL #{data['mal_id']})", "success")
            else:
                f.write(f"title: {anime_name}\n")
                f.write("mal-id: unknown\n")
                print_status("Aucun match MAL trouvé", "warning")
    except OSError as e:
        print_status(f"Écriture .match échouée: {e}", "warning")
