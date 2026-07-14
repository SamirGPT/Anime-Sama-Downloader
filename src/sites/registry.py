"""Site registry — auto-detect which site to use based on URL."""
from __future__ import annotations

from typing import List, Optional

from .base import Site, SiteNotFound
from .anime_sama import AnimeSamaSite
from .voiranime import VoirAnimeSite


# Singleton instances
_SITES = {
    "anime-sama": AnimeSamaSite(),
    "voiranime": VoirAnimeSite(),
}


def get_all_sites() -> List[Site]:
    """Return all registered site instances."""
    return list(_SITES.values())


def get_site_by_key(key: str) -> Optional[Site]:
    """Return the site with the given key, or None."""
    return _SITES.get(key)


def get_site_for_url(url: str) -> Site:
    """Auto-detect the site for a given URL.

    Raises SiteNotFound if no site matches.
    """
    if not url:
        raise SiteNotFound("URL vide")
    for site in _SITES.values():
        if site.matches(url):
            return site
    raise SiteNotFound(
        f"Aucun site ne gère l'URL: {url}\n"
        f"Sites supportés: {', '.join(s.display for s in _SITES.values())}"
    )
