"""voiranime.rip site implementation.

Voiranime is a WordPress-based anime streaming site. Its structure:
- Home: https://voiranime.rip/
- Search: https://voiranime.rip/?s={query}
- Anime page: https://voiranime.rip/anime/{slug}/
- Episode: https://voiranime.rip/{slug}-saison-{n}-episode-{n}/
           or https://voiranime.rip/episode/{slug}/

The site typically embeds the same video players as anime-sama
(Sibnet, Vidmoly, SendVid, etc.), so we can reuse the extractors.

Note: web structures change. If voiranime.rip updates its layout,
the regexes here may need adjustment. The framework makes it easy
to refine without touching the rest of the code.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from src import network
from src.config import get_config
from src.ui import Colors, print_status, print_separator, prompt, confirm
from src.utils import sanitize_filename


DOMAIN = "voiranime.rip"
BASE_URL = f"https://{DOMAIN}"


class VoirAnimeSite:
    """voiranime.rip site — uses WordPress patterns."""

    key = "voiranime"
    display = "VoirAnime"
    domain = DOMAIN
    all_domains = [DOMAIN, "voiranime.com", "voiranime.fr"]

    # ------------------------------------------------------------------
    # URL detection
    # ------------------------------------------------------------------
    def matches(self, url: str) -> bool:
        if not url:
            return False
        u = url.lower()
        return any(d in u for d in self.all_domains)

    # ------------------------------------------------------------------
    # Cloudflare / headers
    # ------------------------------------------------------------------
    def setup_cloudflare(self) -> bool:
        # Voiranime typically doesn't use Cloudflare protection as aggressively
        # as anime-sama. Just probe to confirm reachability.
        try:
            r = network.get(f"{BASE_URL}/", timeout=10)
            if r.status_code == 200:
                print_status("VoirAnime accessible.", "success")
                return True
            if r.status_code in (403, 503):
                print_status(
                    "VoirAnime bloqué (peut-être Cloudflare). "
                    "Réessaie plus tard ou utilise un VPN.",
                    "warning",
                )
                return False
            print_status(f"VoirAnime: HTTP {r.status_code}", "warning")
            return False
        except Exception as e:
            print_status(f"VoirAnime inaccessible: {e}", "warning")
            return False

    def get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": f"{BASE_URL}/",
            "User-Agent": network.DEFAULT_USER_AGENT,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, headers: Optional[Dict] = None) -> List[Dict[str, str]]:
        """Search voiranime.rip via the WordPress ?s= parameter."""
        if not query.strip():
            return []
        headers = headers or self.get_headers()
        search_url = f"{BASE_URL}/?s={quote(query)}"
        try:
            r = network.get(search_url, headers=headers, timeout=15)
            if r.status_code != 200:
                print_status(f"Recherche VoirAnime HTTP {r.status_code}", "warning")
                return []
            html = r.text
        except Exception as e:
            print_status(f"Erreur recherche VoirAnime: {e}", "error")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, str]] = []
        seen = set()

        # WordPress search results typically use <article> or <div class="post">
        # Try multiple selectors
        for selector in [
            ("article", {}),
            ("div", {"class": re.compile(r"post|item|result|article", re.I)}),
            ("li", {"class": re.compile(r"post|item|result", re.I)}),
            ("h2", {"class": re.compile(r"entry-title|title", re.I)}),
            ("h3", {"class": re.compile(r"entry-title|title", re.I)}),
        ]:
            tag, attrs = selector
            for el in soup.find_all(tag, attrs):
                a = el.find("a", href=True) if el.name != "a" else el
                if not a or not a.get("href"):
                    continue
                href = a["href"]
                title = a.get_text(strip=True)
                if not title or href in seen:
                    continue
                # Filter out non-anime links
                if "/anime/" in href or "/episode/" in href or "/category/" in href:
                    seen.add(href)
                    results.append({
                        "title": title,
                        "url": href,
                        "support": "Anime Supported",
                    })
            if results:
                break

        return results

    # ------------------------------------------------------------------
    # Expand (find seasons/episodes from anime page)
    # ------------------------------------------------------------------
    def expand(self, url: str, headers: Optional[Dict] = None) -> List[Dict[str, str]]:
        """From an anime page, list its seasons."""
        headers = headers or self.get_headers()
        try:
            r = network.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                return []
            html = r.text
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, str]] = []
        seen = set()

        # Look for season links — common patterns
        # 1. <a href=".../saison-1/"> or <a href=".../season-1/">
        # 2. <a href=".../category/.../saison-...">
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if not text or href in seen:
                continue
            # Match season-like URLs
            if re.search(r'/saison[-_]?\d|/season[-_]?\d', href, re.I):
                seen.add(href)
                results.append({"name": text, "url": href})
            elif "/category/" in href and href != url:
                seen.add(href)
                results.append({"name": text, "url": href})

        # Dedupe and keep order
        return results

    def validate(self, url: str) -> bool:
        """A valid VoirAnime URL is one that contains /episode/ or /saison/ or /season/."""
        if not self.matches(url):
            return False
        u = url.lower()
        return any(k in u for k in ("/episode", "/saison", "/season", "/category/"))

    # ------------------------------------------------------------------
    # Episodes — find all episode URLs on a season page
    # ------------------------------------------------------------------
    def fetch_episodes(self, url: str,
                       headers: Optional[Dict] = None) -> Optional[Dict[str, List[str]]]:
        """Scrape episode URLs from a season/category page.

        Returns {"Player 1": [url1, url2, ...]} — single player since
        VoirAnime usually has one embed per episode.
        """
        headers = headers or self.get_headers()
        try:
            r = network.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                print_status(f"VoirAnime page HTTP {r.status_code}", "error")
                return None
            html = r.text
        except Exception as e:
            print_status(f"Erreur fetch page: {e}", "error")
            return None

        soup = BeautifulSoup(html, "html.parser")
        episode_urls: List[str] = []
        seen = set()

        # Find episode links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href in seen:
                continue
            # Match episode URL patterns
            if re.search(r'/episode/|[-_]episode[-_]?\d', href, re.I):
                # Make absolute
                if not href.startswith("http"):
                    href = urljoin(url, href)
                seen.add(href)
                episode_urls.append(href)

        if not episode_urls:
            # Fallback: try pagination — get all episodes by following page links
            print_status("Aucun épisode direct — essai pagination...", "info")
            # Try /page/2/, /page/3/, etc.
            for page in range(2, 10):
                page_url = url.rstrip("/") + f"/page/{page}/"
                try:
                    pr = network.get(page_url, headers=headers, timeout=10)
                    if pr.status_code != 200:
                        break
                    psoup = BeautifulSoup(pr.text, "html.parser")
                    found_any = False
                    for a in psoup.find_all("a", href=True):
                        href = a["href"]
                        if re.search(r'/episode/|[-_]episode[-_]?\d', href, re.I):
                            if href not in seen:
                                if not href.startswith("http"):
                                    href = urljoin(page_url, href)
                                seen.add(href)
                                episode_urls.append(href)
                                found_any = True
                    if not found_any:
                        break
                except Exception:
                    break

        if not episode_urls:
            print_status("Aucun épisode trouvé sur VoirAnime", "warning")
            return {}

        # Reverse to get episode 1 first (WordPress lists newest first)
        episode_urls.reverse()
        print_status(f"VoirAnime: {len(episode_urls)} épisodes trouvés", "success")
        return {"Player 1": episode_urls}

    # ------------------------------------------------------------------
    # Scans — VoirAnime doesn't typically host scans
    # ------------------------------------------------------------------
    def is_scan_url(self, url: str) -> bool:
        return False

    def download_scan(self, url: str,
                      headers: Optional[Dict] = None,
                      dest: Optional[str] = None) -> bool:
        print_status("VoirAnime ne supporte pas les scans.", "warning")
        return False


# Singleton instance
SITE = VoirAnimeSite()
