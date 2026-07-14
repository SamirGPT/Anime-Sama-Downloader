"""Catalog expansion — find seasons/versions/languages for an anime."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src import network
from src.cloudflare import DOMAIN, get_anime_sama_headers
from src.ui import print_debug


URL_PATTERN = re.compile(
    r'^https?://(?:www\.)?anime-sama\.[^/]+/catalogue/[^/]+/.+/.+/?$',
    re.IGNORECASE,
)


def validate_anime_sama_url(url: str) -> Tuple[bool, str]:
    """Return (True, '') if the URL points to a valid season/scan page."""
    if URL_PATTERN.match(url):
        return True, ""
    return False, (
        f"URL invalide: {url}\n"
        f"  Format attendu:\n"
        f"    https://{DOMAIN}/catalogue/<anime>/<saison>/<langue>/\n"
        f"    https://{DOMAIN}/catalogue/<anime>/scan/<langue>/\n"
    )


def is_valid_season(url: str, headers: Optional[Dict] = None) -> bool:
    """Check whether a season URL has at least one real episode URL."""
    try:
        ep_url = url.rstrip("/") + "/episodes.js"
        r = network.get(ep_url, headers=headers, timeout=8)
        if r.status_code != 200:
            return False
        content = r.text
        if not content.strip():
            return False
        # Find all `var epsN = [...];` blocks
        arrays = re.findall(r'var\s+eps\d+\s*=\s*\[(.*?)\];', content, re.DOTALL)
        if not arrays:
            return False
        for arr in arrays:
            urls = re.findall(r"""['"](https?://[^'"]+)['"]""", arr)
            if any(_is_real_url(u) for u in urls):
                return True
        return False
    except Exception:
        return False


def _is_real_url(u: str) -> bool:
    u = u.strip()
    if len(u) < 20:
        return False
    if re.search(r'[?&][a-zA-Z0-9_]+=(?:$|&)', u):
        return False
    if re.search(r'/embed[-_.]?(?:\w{3,4})?$', u):
        return False
    return True


def _get_matches(url: str, headers: Optional[Dict]) -> List[Tuple[str, str]]:
    """Return list of (name, relative_url) from panneauAnime/panneauScan calls."""
    try:
        r = network.get(url, headers=headers, timeout=12)
        r.raise_for_status()
    except Exception:
        return []
    content = r.text
    # Strip comments first
    content = re.sub(r'<!--[\s\S]*?-->', '', content)
    content = re.sub(r'/\*[\s\S]*?\*/', '', content)
    anime = re.findall(
        r'panneauAnime\s*\(\s*(["\'])(.*?)\1\s*,\s*(["\'])(.*?)\3\s*\)',
        content,
    )
    scans = re.findall(
        r'panneauScan\s*\(\s*(["\'])(.*?)\1\s*,\s*(["\'])(.*?)\3\s*\)',
        content,
    )
    out: List[Tuple[str, str]] = []
    for _, name, _, rel in anime:
        out.append((name, rel))
    for _, name, _, rel in scans:
        out.append((name, rel))
    return out


def expand_catalogue_url(url: str, headers: Optional[Dict] = None
                         ) -> List[Dict[str, str]]:
    """Return list of {name, url} for all seasons/versions/scans found.

    Tries the given URL first; if no matches, falls back to the catalogue
    root URL for the anime slug.
    """
    headers = headers or get_anime_sama_headers()
    raw = _get_matches(url, headers)
    if not raw:
        m = re.search(
            r'https?://(?:www\.)?' + re.escape(DOMAIN) + r'/catalogue/([^/]+)/',
            url,
        )
        if m:
            slug = m.group(1)
            root = f"https://{DOMAIN}/catalogue/{slug}/"
            if root.rstrip('/') != url.rstrip('/'):
                raw = _get_matches(root, headers)

    results: List[Dict[str, str]] = []
    seen = set()
    base = url if url.endswith('/') else url + '/'

    for name, rel in raw:
        if name == "nom" or rel == "url":
            continue
        full = urljoin(base, rel)
        if not full.endswith('/'):
            full += '/'
        if full in seen:
            continue
        # For anime URLs (not scans), validate that the season actually has episodes
        if '/scan' not in full.lower():
            if not is_valid_season(full, headers):
                print_debug(f"Skipping (no episodes): {full}")
                continue
        seen.add(full)
        results.append({"name": name, "url": full})

        # If VOSTFR variant found, also try VF
        if 'vostfr' in rel.lower():
            vf_rel = rel.lower().replace('vostfr', 'vf')
            vf_full = full.lower().replace('vostfr', 'vf')
            if vf_full not in seen and '/scan' not in vf_full:
                if is_valid_season(vf_full, headers):
                    results.append({"name": f"{name} (VF)", "url": vf_full})
                    seen.add(vf_full)

    return results
