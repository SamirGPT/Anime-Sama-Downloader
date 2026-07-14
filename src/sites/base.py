"""Abstract Site class — defines the interface every site must implement.

A "site" is a streaming website (anime-sama.to, voiranime.rip, ...).
Each site knows how to:
  - search its catalog
  - expand an anime URL to seasons/versions
  - validate a URL
  - fetch the list of episodes for a season
  - detect whether a URL points to scans
  - download scans
  - build the right headers (Cloudflare, referer, ...)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class SiteNotFound(Exception):
    """Raised when no site matches a given URL."""


class Site(ABC):
    """Base abstract class for all streaming sites."""

    #: Short internal key (e.g. "anime-sama")
    key: str = ""
    #: Display name (e.g. "Anime-Sama")
    display: str = ""
    #: Main domain without scheme (e.g. "anime-sama.to")
    domain: str = ""
    #: All domains the site uses (for matching)
    all_domains: List[str] = []

    # ------------------------------------------------------------------
    # URL detection
    # ------------------------------------------------------------------
    def matches(self, url: str) -> bool:
        """Return True if this site handles the given URL."""
        if not url:
            return False
        u = url.lower()
        return any(d in u for d in self.all_domains)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    @abstractmethod
    def search(self, query: str, headers: Optional[Dict] = None) -> List[Dict[str, str]]:
        """Search the catalog. Return list of {title, url, support}."""

    # ------------------------------------------------------------------
    # Catalog expansion
    # ------------------------------------------------------------------
    @abstractmethod
    def expand(self, url: str, headers: Optional[Dict] = None) -> List[Dict[str, str]]:
        """Expand an anime page to its seasons/versions/scans.
        Returns list of {name, url}."""

    @abstractmethod
    def validate(self, url: str) -> bool:
        """Return True if the URL is a valid season/scan page."""

    # ------------------------------------------------------------------
    # Episodes
    # ------------------------------------------------------------------
    @abstractmethod
    def fetch_episodes(self, url: str,
                       headers: Optional[Dict] = None) -> Optional[Dict[str, List[str]]]:
        """Return {player_name: [url1, ...]} or None on failure."""

    # ------------------------------------------------------------------
    # Scans
    # ------------------------------------------------------------------
    @abstractmethod
    def is_scan_url(self, url: str) -> bool:
        """Return True if the URL points to a scan (manga) page."""

    @abstractmethod
    def download_scan(self, url: str,
                      headers: Optional[Dict] = None,
                      dest: Optional[str] = None) -> bool:
        """Download scan chapters from this URL."""

    # ------------------------------------------------------------------
    # Headers / Cloudflare
    # ------------------------------------------------------------------
    def get_headers(self) -> Dict[str, str]:
        """Default headers for this site."""
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": f"https://{self.domain}/",
        }

    def setup_cloudflare(self) -> bool:
        """Hook for sites that need Cloudflare cookies. Default: no-op."""
        return True
