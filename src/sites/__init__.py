"""Multi-site support package.

Each site is a module that exports a `Site` instance.
The registry auto-detects which site to use based on the URL.
"""
from .base import Site, SiteNotFound
from .registry import get_site_for_url, get_all_sites, get_site_by_key

__all__ = [
    "Site", "SiteNotFound",
    "get_site_for_url", "get_all_sites", "get_site_by_key",
]
