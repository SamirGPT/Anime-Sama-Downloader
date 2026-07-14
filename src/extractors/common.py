"""Common helpers shared across extractors:
- packed-JS unpacker (single implementation, replaces the two divergent ones)
- master.m3u8 URL extraction
- best-variant m3u8 selection
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from src import network
from src.ui import print_debug, print_status


ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ---------------------------------------------------------------------------
# Packed-JS unpacker — single, correct implementation
# ---------------------------------------------------------------------------
def encode_base(num: int, base: int) -> str:
    """Encode `num` in the given `base` using ALPHABET."""
    if base > len(ALPHABET):
        raise ValueError(f"Base {base} exceeds alphabet size {len(ALPHABET)}")
    if num == 0:
        return ALPHABET[0]
    out = ""
    while num > 0:
        out = ALPHABET[num % base] + out
        num //= base
    return out


def extract_packed_code(html: str) -> Optional[Tuple[str, int, int, List[str]]]:
    """Extract (packed_code, base, count, words) from a packed eval() block.

    Returns None if no packed code is found.
    """
    pattern = (
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\("
        r"'(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)"
        r"\)\)"
    )
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        print_debug("No packed JS found in HTML")
        return None
    packed = m.group(1)
    base = int(m.group(2))
    count = int(m.group(3))
    words = m.group(4).split('|')
    return packed, base, count, words


def unpack_js(packed: str, base: int, count: int, words: List[str]) -> str:
    """Unpack a packed-JS payload.

    Correctness note: we iterate in REVERSED order so that longer tokens
    (higher indices) are replaced first, preventing partial collisions
    with shorter tokens that share a prefix. The two original
    implementations disagreed on this; reversed is correct because
    tokens are word-boundary anchored but `re.sub` does left-to-right
    replacement which is order-sensitive when one token is a prefix of
    another in the alphabet (e.g. base 36: 'a' is 10, 'aa' is 370).
    """
    out = packed
    # Replace longest tokens first to avoid prefix collisions
    for i in sorted(range(min(count, len(words))), reverse=True):
        word = words[i]
        if not word:
            continue
        token = encode_base(i, base)
        if not token:
            continue
        out = re.sub(rf'\b{re.escape(token)}\b', word, out)
    return out


# ---------------------------------------------------------------------------
# M3U8 helpers
# ---------------------------------------------------------------------------
def find_m3u8_in_code(code: str) -> Optional[str]:
    """Find an m3u8 URL (absolute or /stream/...) inside unpacked JS."""
    # Try absolute URLs first
    for p in (
        r'https?://[^"\']+master\.m3u8[^"\']*',
        r'https?://[^"\']+\.m3u8[^"\']*',
    ):
        m = re.search(p, code)
        if m:
            return m.group(0)
    # Try relative /stream/.../master.m3u8
    m = re.search(r'["\'](/stream/[^"\']*/master\.m3u8[^"\']*)["\']', code)
    if m:
        return m.group(1)
    m = re.search(r'["\'](/[^"\']*\.m3u8[^"\']*)["\']', code)
    if m:
        return m.group(1)
    return None


def select_best_variant(master_url: str) -> Optional[str]:
    """Fetch a master.m3u8 and return the variant with the highest bandwidth.

    Returns the absolute URL of the best variant playlist, or None on failure.
    """
    try:
        text = network.get_text(master_url, timeout=15)
    except Exception as e:
        print_status(f"Could not fetch master playlist: {e}", "error")
        return None

    best_bw = -1
    best_url: Optional[str] = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            bw_m = re.search(r'BANDWIDTH=(\d+)', line)
            bw = int(bw_m.group(1)) if bw_m else 0
            # The next non-comment line is the variant URL
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                if next_line.startswith("#"):
                    continue
                candidate = next_line
                if not candidate.startswith("http"):
                    candidate = urljoin(master_url, candidate)
                if bw > best_bw:
                    best_bw = bw
                    best_url = candidate
                break
    if best_url:
        print_debug(f"Selected variant: {best_url} (bw={best_bw})")
    return best_url


def extract_segments(playlist_url: str) -> Optional[List[str]]:
    """Fetch an m3u8 playlist and return the list of segment URLs.

    Handles master playlists (picks best variant) and media playlists
    (returns segment URLs directly).
    """
    try:
        text = network.get_text(playlist_url, timeout=15)
    except Exception as e:
        print_status(f"Could not fetch playlist: {e}", "error")
        return None

    # If it's a master playlist, recurse into the best variant
    if "#EXT-X-STREAM-INF" in text:
        best = select_best_variant(playlist_url)
        if best and best != playlist_url:
            return extract_segments(best)
        return None

    segments: List[str] = []
    base = playlist_url
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("http"):
            line = urljoin(base, line)
        segments.append(line)

    if not segments:
        print_status("Aucun segment .ts trouvé dans la playlist", "warning")
        return None
    return segments


# ---------------------------------------------------------------------------
# Packed-JS page fetcher (used by uqload, movearnpre, ...)
# ---------------------------------------------------------------------------
def fetch_and_unpack(embed_url: str, referer: Optional[str] = None) -> Optional[str]:
    """Fetch an embed page, extract+unpack the packed JS, return unpacked code."""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    else:
        # Use the embed site root as referer
        try:
            parsed = urlparse(embed_url)
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        except Exception:
            pass

    try:
        html = network.get_text(embed_url, headers=headers, timeout=15)
    except Exception as e:
        print_status(f"Erreur fetch embed: {e}", "error")
        return None

    packed = extract_packed_code(html)
    if not packed:
        # Some pages have the m3u8 directly without packing
        direct = find_m3u8_in_code(html)
        return direct

    code, base, count, words = packed
    return unpack_js(code, base, count, words)
