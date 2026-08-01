"""Upstream extractor — uses the generic MP4 pattern matcher."""
from __future__ import annotations
from typing import Optional
from .generic import extract_generic_mp4


def extract_upstream(url: str) -> Optional[str]:
    """Extract direct MP4 URL from an Upstream embed URL."""
    return extract_generic_mp4(url)
