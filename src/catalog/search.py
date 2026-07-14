"""Search anime-sama.eu catalog.

Posts to /template-php/defaut/fetch.php and parses the result HTML.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src import network
from src.cloudflare import DOMAIN, get_anime_sama_headers
from src.ui import print_status
from .expand import is_valid_season


def _check_link_support(res: Dict, headers: Optional[Dict]) -> Dict:
    """Probe an anime page to detect whether it has anime/scans."""
    try:
        r = network.get(res["url"], headers=headers, timeout=8)
        if r.status_code != 200:
            res["support"] = "Unknown"
            return res
        content = r.text
        base = res["url"]
        if not base.endswith("/"):
            base += "/"

        # Find panneauAnime(...) calls
        anime_matches = re.findall(
            r'panneauAnime\s*\(\s*(["\'])(.*?)\1\s*,\s*(["\'])(.*?)\3\s*\)',
            content,
        )
        has_valid_anime = False
        for _, name, _, rel in anime_matches:
            if name == "nom" or rel == "url":
                continue
            full = urljoin(base, rel)
            if not full.endswith("/"):
                full += "/"
            if is_valid_season(full, headers):
                has_valid_anime = True
                break

        scan_matches = re.findall(
            r'panneauScan\s*\(\s*(["\'])(.*?)\1\s*,\s*(["\'])(.*?)\3\s*\)',
            content,
        )
        valid_scan = [m for m in scan_matches if m[1] != "nom" and m[3] != "url"]

        if has_valid_anime and valid_scan:
            res["support"] = "Anime & Scans Supported"
        elif has_valid_anime:
            res["support"] = "Anime Supported"
        elif valid_scan:
            res["support"] = "Scans Supported"
        else:
            res["support"] = "Unsupported"
    except Exception:
        res["support"] = "Unknown"
    return res


def search_anime(query: str, headers: Optional[Dict] = None,
                 max_workers: int = 8) -> List[Dict[str, Optional[str]]]:
    """Search anime-sama.eu and return a list of {title, url, support}."""
    if not query.strip():
        return []
    headers = headers or get_anime_sama_headers()
    url = f"https://{DOMAIN}/template-php/defaut/fetch.php"
    try:
        r = network.post(url, headers=headers, data={"query": query}, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print_status(f"Erreur de recherche: {e}", "error")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results: List[Dict[str, Optional[str]]] = []
    for a in soup.find_all("a"):
        href = a.get("href")
        h3 = a.find("h3")
        title = h3.get_text(strip=True) if h3 else "Unknown"
        if href:
            full = urljoin(f"https://{DOMAIN}/", href)
            results.append({"title": title, "url": full, "support": None})

    if results and max_workers > 0:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(lambda r: _check_link_support(r, headers), results))
    return results
