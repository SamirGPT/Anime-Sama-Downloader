"""Catalog of supported video sources and their metadata.

Centralizes the player/domain knowledge that was scattered across
`src/var.py`, `src/utils/print/print_episodes.py`, etc.
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

    def matches(self, url: str) -> bool:
        u = url.lower()
        return any(d in u for d in self.domains)


# Ordered list — the first matching source wins.
SOURCES: List[Source] = [
    Source("sendvid",   "SendVid",   ["sendvid.com"],            notes="Direct MP4, recommended"),
    Source("sibnet",    "Sibnet",    ["video.sibnet.ru"],        notes="Direct MP4"),
    Source("uqload",    "Uqload",    ["uqload.is", "uqload."],   notes="M3U8 HLS"),
    Source("vidmoly",   "Vidmoly",   ["vidmoly.net", "vidmoly.to", "vidmoly.biz"], notes="M3U8 HLS"),
    Source("oneupload", "OneUpload", ["oneupload.net", "oneupload.to"], notes="M3U8 HLS"),
    Source("embed4me",  "Embed4me",  ["embed4me.com", "lpayer.embed4me.com"], notes="AES-encrypted M3U8"),
    Source("movearnpre","Movearnpre",["movearnpre.com", "ovaltinecdn.com"], notes="Packed JS M3U8 (inconsistent)"),
    Source("smoothpre", "Smoothpre", ["smoothpre.com"],          notes="Packed JS M3U8 (inconsistent)"),
    Source("mivalyo",   "Mivalyo",   ["mivalyo.com"],            notes="Packed JS M3U8 (inconsistent)"),
    Source("dingtezuni","Dingtezuni",["dingtezuni.com"],         notes="Packed JS M3U8 (inconsistent)"),
    # Deprecated / unsupported (kept for display purposes)
    Source("vk",        "VK",        ["vk.com"], supported=False, notes="Unsupported"),
    Source("myvi",      "Myvi",      ["myvi.tv", "myvi.top"], supported=False, notes="Malicious — ads only"),
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


# Backwards-compatible flat list of valid player domains (used by listing).
ALL_DOMAINS: List[str] = [d for s in SOURCES for d in s.domains if s.supported]
