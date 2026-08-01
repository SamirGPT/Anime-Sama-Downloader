"""Common helpers shared across extractors.

v4.2: Added fMP4 (CMAF) support — detects #EXT-X-MAP and returns the
init segment URL alongside the media segments. This is required for
hosts (Vidmoly, etc.) that switched from MPEG-TS segments to fMP4.

Public API:
  - extract_segments(playlist_url) -> PlaylistInfo | None
    Where PlaylistInfo = (init_segment_url | None, [segment_urls], is_fmp4)

  Old callers that did `segments = extract_segments(url)` and then
  `len(segments)` will still work because PlaylistInfo is a NamedTuple
  that supports __len__ and __iter__ on its segments field for backward
  compatibility — but you should destructure it for new code.
"""
from __future__ import annotations

import re
from typing import List, NamedTuple, Optional, Tuple
from urllib.parse import urljoin, urlparse

from src import network
from src.ui import print_debug, print_status


ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ---------------------------------------------------------------------------
# Playlist info — returned by extract_segments
# ---------------------------------------------------------------------------
class PlaylistInfo(NamedTuple):
    """Information about an HLS media playlist.

    Attributes:
        init_segment: URL of the initialization segment (fMP4 only).
                      None for plain MPEG-TS playlists.
        segments: List of media segment URLs (in order).
        is_fmp4: True if this is a fragmented MP4 (CMAF) playlist.
                 False for MPEG-TS.
    """
    init_segment: Optional[str]
    segments: List[str]
    is_fmp4: bool

    # Backward-compat: allow `len(playlist)` and `for url in playlist`
    # so old code that treated the return value as a list of URLs keeps
    # working (it iterates over segments, ignoring init).
    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self):
        return iter(self.segments)

    def __bool__(self) -> bool:
        return bool(self.segments)


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

    We iterate in REVERSED order so that longer tokens (higher indices)
    are replaced first, preventing partial collisions with shorter tokens
    that share a prefix.
    """
    out = packed
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
    for p in (
        r'https?://[^"\']+master\.m3u8[^"\']*',
        r'https?://[^"\']+\.m3u8[^"\']*',
    ):
        m = re.search(p, code)
        if m:
            return m.group(0)
    m = re.search(r'["\'](/stream/[^"\']*/master\.m3u8[^"\']*)["\']', code)
    if m:
        return m.group(1)
    m = re.search(r'["\'](/[^"\']*\.m3u8[^"\']*)["\']', code)
    if m:
        return m.group(1)
    return None


def select_best_variant(master_url: str, prefer_quality: Optional[str] = None) -> Optional[str]:
    """Fetch a master.m3u8 and return the variant URL.

    Args:
        master_url: URL of the master playlist.
        prefer_quality: 'fhd' (1080p), 'hd' (720p), 'sd' (480p), or None (auto-best).

    Returns:
        The absolute URL of the chosen variant, or None on failure.
    """
    try:
        text = network.get_text(master_url, timeout=15)
    except Exception as e:
        print_status(f"Could not fetch master playlist: {e}", "error")
        return None

    variants: List[Tuple[int, int, str]] = []  # (bandwidth, resolution, url)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            bw_m = re.search(r'BANDWIDTH=(\d+)', line)
            bw = int(bw_m.group(1)) if bw_m else 0
            res_m = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            height = int(res_m.group(2)) if res_m else 0
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                if next_line.startswith("#"):
                    continue
                candidate = next_line
                if not candidate.startswith("http"):
                    candidate = urljoin(master_url, candidate)
                variants.append((bw, height, candidate))
                break

    if not variants:
        return None

    # If user wants a specific quality, find the closest match
    if prefer_quality:
        target_map = {"fhd": 1080, "hd": 720, "sd": 480}
        target = target_map.get(prefer_quality.lower(), 1080)
        # Find variant closest to (but not above if possible) the target height
        # Prefer variants that match exactly, then closest below, then closest above
        exact = [v for v in variants if v[1] == target]
        if exact:
            chosen = max(exact, key=lambda x: x[0])
        else:
            below = [v for v in variants if v[1] <= target]
            if below:
                chosen = max(below, key=lambda x: x[1])
            else:
                chosen = min(variants, key=lambda x: x[1])
        print_debug(f"Selected variant: {chosen[2][:60]} ({chosen[1]}p, bw={chosen[0]})")
        return chosen[2]

    # Default: pick highest bandwidth
    best = max(variants, key=lambda x: x[0])
    print_debug(f"Selected variant: {best[2][:60]} ({best[1]}p, bw={best[0]})")
    return best[2]


def list_variants(master_url: str) -> List[Dict[str, Any]]:
    """List all available quality variants in a master playlist.

    Returns a list of dicts: [{"url":..., "bandwidth":..., "resolution":"WxH", "height":N}, ...]
    Sorted by height descending (best quality first).
    """
    from typing import Any
    try:
        text = network.get_text(master_url, timeout=15)
    except Exception:
        return []

    variants: List[Dict[str, Any]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            bw_m = re.search(r'BANDWIDTH=(\d+)', line)
            bw = int(bw_m.group(1)) if bw_m else 0
            res_m = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            width = int(res_m.group(1)) if res_m else 0
            height = int(res_m.group(2)) if res_m else 0
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                if next_line.startswith("#"):
                    continue
                candidate = next_line
                if not candidate.startswith("http"):
                    candidate = urljoin(master_url, candidate)
                variants.append({
                    "url": candidate,
                    "bandwidth": bw,
                    "resolution": f"{width}x{height}" if width and height else "?",
                    "height": height,
                })
                break
    variants.sort(key=lambda v: v["height"], reverse=True)
    return variants


# ---------------------------------------------------------------------------
# Regex for #EXT-X-MAP — the init segment declaration in fMP4 playlists
# ---------------------------------------------------------------------------
# Format example:
#   #EXT-X-MAP:URI="init.mp4"            (relative)
#   #EXT-X-MAP:URI="https://cdn/init.mp4"  (absolute)
#   #EXT-X-MAP:URI="init.mp4",BYTERANGE="1234@0"
_EXT_X_MAP_RE = re.compile(
    r'#EXT-X-MAP:.*?URI="([^"]+)"',
    re.IGNORECASE,
)


def _parse_ext_x_map(line: str, base_url: str) -> Optional[str]:
    """Parse an #EXT-X-MAP line and return the absolute init segment URL."""
    m = _EXT_X_MAP_RE.search(line)
    if not m:
        return None
    uri = m.group(1)
    if not uri:
        return None
    if not uri.startswith("http"):
        uri = urljoin(base_url, uri)
    return uri


def extract_segments(playlist_url: str,
                     prefer_quality: Optional[str] = None) -> Optional[PlaylistInfo]:
    """Fetch an m3u8 playlist and return PlaylistInfo.

    Args:
        playlist_url: URL of the playlist (master or media).
        prefer_quality: 'fhd' (1080p), 'hd' (720p), 'sd' (480p), or None (auto-best).

    Handles:
      - Master playlists (recurses into chosen variant, respecting prefer_quality)
      - MPEG-TS media playlists (returns segments only, is_fmp4=False)
      - fMP4 / CMAF playlists (returns init_segment + segments, is_fmp4=True)

    Returns None on fetch failure. Returns PlaylistInfo with empty segments
    list if no segments are found.
    """
    try:
        text = network.get_text(playlist_url, timeout=15)
    except Exception as e:
        print_status(f"Could not fetch playlist: {e}", "error")
        return None

    # If it's a master playlist, recurse into the chosen variant
    if "#EXT-X-STREAM-INF" in text:
        best = select_best_variant(playlist_url, prefer_quality=prefer_quality)
        if best and best != playlist_url:
            return extract_segments(best, prefer_quality=prefer_quality)
        return None

    base = playlist_url
    init_segment: Optional[str] = None
    is_fmp4 = False
    segments: List[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("#"):
            if line.upper().startswith("#EXT-X-MAP"):
                init_url = _parse_ext_x_map(line, base)
                if init_url:
                    init_segment = init_url
                    is_fmp4 = True
            continue

        if not line.startswith("http"):
            line = urljoin(base, line)
        segments.append(line)

    if not segments:
        print_status("Aucun segment trouvé dans la playlist", "warning")
        return None

    if is_fmp4:
        print_status(
            f"Playlist fMP4 détectée — init: {os.path.basename(init_segment or '?')}, "
            f"{len(segments)} segments",
            "info",
        )
    else:
        print_debug(f"MPEG-TS playlist — {len(segments)} segments")

    return PlaylistInfo(
        init_segment=init_segment,
        segments=segments,
        is_fmp4=is_fmp4,
    )


# Allow `import os` for the basename call in the fMP4 branch above without
# polluting the top of the file (kept at the bottom intentionally so the
# critical HLS code reads cleanly up top).
import os  # noqa: E402


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
