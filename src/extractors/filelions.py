"""FileLions extractor — uses the generic MP4 pattern matcher.
FileLions may also serve HLS m3u8, which is handled by the downloader."""
from __future__ import annotations
from typing import Optional
from .generic import extract_generic_mp4


def extract_filelions(url: str) -> Optional[str]:
    """Extract direct video URL from a FileLions embed URL."""
    return extract_generic_mp4(url)
