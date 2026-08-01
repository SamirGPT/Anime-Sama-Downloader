"""Vidoza extractor — uses the generic MP4 pattern matcher."""
from __future__ import annotations
from typing import Optional
from .generic import extract_generic_mp4


def extract_vidoza(url: str) -> Optional[str]:
    """Extract direct MP4 URL from a Vidoza embed URL."""
    return extract_generic_mp4(url)
