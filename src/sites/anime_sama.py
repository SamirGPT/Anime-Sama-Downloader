"""anime-sama.to site implementation.

Refactored from the previous monolithic cloudflare.py + catalog/*.py
into a clean Site subclass.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, quote

from src import network
from src.ui import Colors, print_status, print_separator, prompt, confirm
from src.utils import sanitize_filename, extract_anime_name
from .base import Site


class AnimeSamaSite(Site):
    key = "anime-sama"
    display = "Anime-Sama"
    domain = "anime-sama.to"
    all_domains = ["anime-sama.to", "anime-sama.fr", "anime-sama.eu",
                   "anime-sama.si", "anime-sama.tv"]

    # ------------------------------------------------------------------
    # Cloudflare
    # ------------------------------------------------------------------
    def setup_cloudflare(self) -> bool:
        from src.cloudflare import setup_cloudflare
        return setup_cloudflare()

    def get_headers(self) -> Dict[str, str]:
        from src.cloudflare import get_anime_sama_headers
        return get_anime_sama_headers()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, headers: Optional[Dict] = None) -> List[Dict[str, str]]:
        from src.catalog.search import search_anime as _search
        return _search(query, headers=headers)

    # ------------------------------------------------------------------
    # Expand (seasons / versions)
    # ------------------------------------------------------------------
    def expand(self, url: str, headers: Optional[Dict] = None) -> List[Dict[str, str]]:
        from src.catalog.expand import expand_catalogue_url
        return expand_catalogue_url(url, headers=headers)

    def validate(self, url: str) -> bool:
        from src.catalog.expand import validate_anime_sama_url
        ok, _ = validate_anime_sama_url(url)
        return ok

    # ------------------------------------------------------------------
    # Episodes
    # ------------------------------------------------------------------
    def fetch_episodes(self, url: str,
                       headers: Optional[Dict] = None) -> Optional[Dict[str, List[str]]]:
        from src.fetchers.episodes import fetch_episodes as _fetch
        return _fetch(url, headers=headers)

    # ------------------------------------------------------------------
    # Scans
    # ------------------------------------------------------------------
    def is_scan_url(self, url: str) -> bool:
        return "/scan" in url.lower()

    def download_scan(self, url: str,
                      headers: Optional[Dict] = None,
                      dest: Optional[str] = None) -> bool:
        from src.scan_downloader import download_scan as _dl
        return _dl(url, headers=headers, dest=dest)


# Singleton instance
SITE = AnimeSamaSite()
