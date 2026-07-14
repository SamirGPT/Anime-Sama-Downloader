"""Extractors package — dispatches by URL domain.

Usage:
    from src.extractors import fetch_video_source
    source = fetch_video_source(url)
"""
from __future__ import annotations

from typing import List, Optional, Union

from src import network
from src.ui import ExtractorError, print_status, print_debug
from .sendvid import extract_sendvid
from .sibnet import extract_sibnet
from .uqload import extract_uqload
from .vidmoly import extract_vidmoly
from .oneupload import extract_oneupload
from .embed4me import extract_embed4me
from .movearnpre import extract_movearnpre_family


def _process_single(url: str) -> Optional[str]:
    """Return a direct video URL (mp4 or m3u8) from an embed page URL."""
    if not url:
        return None
    print_status(f"Extraction: {url[:70]}...", "loading")

    u = url.lower()

    # Vidmoly: prefer .biz domain (the original repo found this was more reliable)
    if "vidmoly.to" in u or "vidmoly.net" in u:
        url = url.replace("vidmoly.to", "vidmoly.biz").replace("vidmoly.net", "vidmoly.biz")
        u = url.lower()

    if "sendvid.com" in u:
        return extract_sendvid(url)
    if "video.sibnet.ru" in u:
        return extract_sibnet(url)
    if "uqload" in u:
        return extract_uqload(url)
    if "vidmoly.biz" in u:
        return extract_vidmoly(url)
    if "oneupload.net" in u or "oneupload.to" in u:
        # normalize
        url = url.replace("oneupload.to", "oneupload.net")
        return extract_oneupload(url)
    if "embed4me" in u or "lpayer.embed4me" in u:
        return extract_embed4me(url)
    if any(d in u for d in ("dingtezuni.com", "mivalyo.com",
                            "smoothpre.com", "movearnpre.com")):
        return extract_movearnpre_family(url)

    print_status(f"Source non supportée: {url}", "warning")
    return None


def fetch_video_source(url: Union[str, List[str]]) -> Optional[Union[str, List[Optional[str]]]]:
    """Extract direct video URL(s) from one or more embed URLs.

    Args:
        url: a single URL string or a list of URLs.

    Returns:
        - For a single URL: a string (the direct video URL) or None.
        - For a list: a list of the same length, with None where extraction failed.
    """
    if isinstance(url, str):
        return _process_single(url)
    if isinstance(url, list):
        return [_process_single(u) for u in url]
    raise ExtractorError(f"Invalid URL type: {type(url)}")
