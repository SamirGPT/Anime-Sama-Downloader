"""Catalog of supported video sources and their metadata.

v5.0: Added 8 new players (Doodstream, Streamtape, Mixdrop, Vidoza,
Streamlare, Upstream, FileLions, HubCloud). Total: 18 supported sources.

Each Source entry maps a domain pattern to:
  - key: internal identifier
  - display: user-facing name
  - domains: list of substrings to match in URLs (lowercase)
  - supported: whether we have an extractor for it
  - notes: short description
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Source:
    key: str               # internal key (e.g. "sibnet")
    display: str           # user-facing name
    domains: List[str]     # list of matching domains (lowercase)
    supported: bool = True
    notes: str = ""
    quality: str = ""      # typical quality (e.g. "up to 1080p")

    def matches(self, url: str) -> bool:
        u = url.lower()
        return any(d in u for d in self.domains)


# Ordered list — the first matching source wins.
# Quality info helps users choose (FHD > HD > 720p)
SOURCES: List[Source] = [
    # --- Tier 1: Direct MP4, fastest ---
    Source("sendvid",   "SendVid",   ["sendvid.com"],
           notes="Direct MP4", quality="up to 1080p FHD"),
    Source("sibnet",    "Sibnet",    ["video.sibnet.ru", "sibnet.ru"],
           notes="Direct MP4", quality="720p HD"),

    # --- Tier 2: HLS M3U8 (need segment download) ---
    Source("uqload",    "Uqload",    ["uqload.is", "uqload."],
           notes="M3U8 HLS", quality="up to 1080p"),
    Source("vidmoly",   "Vidmoly",   ["vidmoly.net", "vidmoly.to", "vidmoly.biz"],
           notes="M3U8 HLS (fMP4)", quality="up to 1080p FHD"),
    Source("oneupload", "OneUpload", ["oneupload.net", "oneupload.to"],
           notes="M3U8 HLS", quality="up to 1080p"),
    Source("embed4me",  "Embed4me",  ["embed4me.com", "lpayer.embed4me.com"],
           notes="AES-encrypted M3U8", quality="up to 1080p"),

    # --- Tier 3: Packed-JS M3U8 (inconsistent) ---
    Source("movearnpre","Movearnpre",["movearnpre.com", "ovaltinecdn.com"],
           notes="Packed JS", quality="variable"),
    Source("smoothpre", "Smoothpre", ["smoothpre.com"],
           notes="Packed JS", quality="variable"),
    Source("mivalyo",   "Mivalyo",   ["mivalyo.com"],
           notes="Packed JS", quality="variable"),
    Source("dingtezuni","Dingtezuni",["dingtezuni.com"],
           notes="Packed JS", quality="variable"),

    # --- Tier 4: NEW v5.0 — popular streaming hosts ---
    Source("doodstream","Doodstream",["doodstream", "dood.so", "doodstream.com"],
           notes="Direct MP4 via API", quality="up to 1080p"),
    Source("streamtape","Streamtape",["streamtape", "streamtape.com"],
           notes="Direct MP4 via API", quality="up to 1080p"),
    Source("mixdrop",   "Mixdrop",   ["mixdrop", "mixdrop.co", "mixdrop.to"],
           notes="Direct MP4", quality="up to 1080p"),
    Source("vidoza",    "Vidoza",    ["vidoza.net"],
           notes="Direct MP4", quality="up to 1080p"),
    Source("streamlare", "Streamlare", ["streamlare.com"],
           notes="Direct MP4", quality="up to 1080p"),
    Source("upstream",  "Upstream",  ["upstream.to", "upstream"],
           notes="Direct MP4", quality="up to 1080p"),
    Source("filelions", "FileLions", ["filelions", "filelions.to"],
           notes="M3U8 HLS", quality="up to 1080p"),
    Source("hubcloud",  "HubCloud",  ["hubcloud", "hubcloud.cc"],
           notes="Direct MP4", quality="up to 1080p"),

    # --- Deprecated / unsupported ---
    Source("vk",        "VK",        ["vk.com"],
           supported=False, notes="Unsupported"),
    Source("myvi",      "Myvi",      ["myvi.tv", "myvi.top"],
           supported=False, notes="Malicious — ads only"),
]

SOURCES_BY_KEY: Dict[str, Source] = {s.key: s for s in SOURCES}


def find_source(url: str) -> Optional[Source]:
    """Return the Source matching the given URL, or None."""
    if not url:
        return None
    for src in SOURCES:
        if src.matches(url):
            return src
    return None


def is_supported(url: str) -> bool:
    s = find_source(url)
    return s is not None and s.supported


def source_label(url: str) -> str:
    s = find_source(url)
    if not s:
        return "Unknown"
    return s.display


# Backwards-compatible flat list of valid player domains
ALL_DOMAINS: List[str] = [d for s in SOURCES for d in s.domains if s.supported]
