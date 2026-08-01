"""Extractors package — dispatches by URL domain.

v5.0: Added 8 new extractors (Doodstream, Streamtape, Mixdrop, Vidoza,
Streamlare, Upstream, FileLions, HubCloud) via the generic MP4 pattern
matcher and dedicated extractors for Doodstream/Streamtape.

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
from .doodstream import extract_doodstream
from .streamtape import extract_streamtape
from .mixdrop import extract_mixdrop
from .vidoza import extract_vidoza
from .streamlare import extract_streamlare
from .upstream import extract_upstream
from .filelions import extract_filelions
from .hubcloud import extract_hubcloud


def _process_single(url: str) -> Optional[str]:
    """Return a direct video URL (mp4 or m3u8) from an embed page URL."""
    if not url:
        return None
    print_status(f"Extraction: {url[:70]}...", "loading")

    u = url.lower()

    # VoirAnime: episode page → extract the embed URL first, then recurse
    if "voiranime.rip" in u or "voiranime.com" in u or "voiranime.fr" in u:
        from src.sites.voiranime import SITE as VA_SITE
        embed_url = VA_SITE.extract_episode_video(url)
        if not embed_url:
            print_status("VoirAnime: aucune source vidéo trouvée sur la page", "warning")
            return None
        print_status(f"VoirAnime → embed: {embed_url[:70]}...", "info")
        return _process_single(embed_url)

    # Vidmoly: prefer .biz domain (more reliable)
    if "vidmoly.to" in u or "vidmoly.net" in u:
        url = url.replace("vidmoly.to", "vidmoly.biz").replace("vidmoly.net", "vidmoly.biz")
        u = url.lower()

    # OneUpload: normalize .to → .net
    if "oneupload.to" in u:
        url = url.replace("oneupload.to", "oneupload.net")
        u = url.lower()

    # --- Tier 1: Direct MP4 ---
    if "sendvid.com" in u:
        return extract_sendvid(url)
    if "sibnet.ru" in u:
        return extract_sibnet(url)

    # --- Tier 2: HLS M3U8 ---
    if "uqload" in u:
        return extract_uqload(url)
    if "vidmoly.biz" in u:
        return extract_vidmoly(url)
    if "oneupload.net" in u:
        return extract_oneupload(url)
    if "embed4me" in u or "lpayer.embed4me" in u:
        return extract_embed4me(url)

    # --- Tier 3: Packed-JS M3U8 ---
    if any(d in u for d in ("dingtezuni.com", "mivalyo.com",
                            "smoothpre.com", "movearnpre.com")):
        return extract_movearnpre_family(url)

    # --- Tier 4: NEW v5.0 — Popular streaming hosts ---
    if any(d in u for d in ("doodstream", "dood.so")):
        return extract_doodstream(url)
    if "streamtape" in u:
        return extract_streamtape(url)
    if any(d in u for d in ("mixdrop", "mixdrop.co", "mixdrop.to")):
        return extract_mixdrop(url)
    if "vidoza" in u:
        return extract_vidoza(url)
    if "streamlare" in u:
        return extract_streamlare(url)
    if any(d in u for d in ("upstream.to", "upstream")):
        return extract_upstream(url)
    if "filelions" in u:
        return extract_filelions(url)
    if "hubcloud" in u:
        return extract_hubcloud(url)

    # --- Last resort: try generic MP4 extraction ---
    # This catches any host that embeds an MP4 URL in HTML/JS
    print_debug(f"Source non reconnue, essai générique: {url[:80]}")
    from .generic import extract_generic_mp4
    result = extract_generic_mp4(url)
    if result:
        return result

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
