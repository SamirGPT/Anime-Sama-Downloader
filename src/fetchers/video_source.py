"""Video source fetcher — thin wrapper around extractors package.

Re-exports the same `fetch_video_source` API for backwards compat.
"""
from __future__ import annotations

from src.extractors import fetch_video_source as _fetch

# Re-export
def fetch_video_source(url):
    return _fetch(url)
