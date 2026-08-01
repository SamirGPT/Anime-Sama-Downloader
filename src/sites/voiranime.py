"""voiranime.rip site implementation.

Reverse-engineered from the actual site (v4.2 — previously the
implementation was based on guesses and did not work).

Actual site structure (verified by scraping the live site):
  - Home:        https://voiranime.rip/
  - Search:      https://voiranime.rip/search?q={query}    (NOT ?s=)
  - Anime page:  https://voiranime.rip/{slug}/             (e.g. /naruto-shippuden/)
  - Season page: https://voiranime.rip/{slug}/saison-{n}/  (e.g. /naruto-shippuden/saison-1/)
  - Episode:     https://voiranime.rip/{slug}/saison-{n}/episode-{m}/

Episode pages contain an <iframe id="videoPlayer" src="..."> and a
JS dict `videoUrls = {"vf": "...", "vostfr": "..."}` listing the
available language versions of the embed URL. The embed URL itself
points to a player (Sibnet, Vidmoly, Uqload, etc.) which we then
pass to the standard extractors.

URL validation:
  - https://voiranime.rip/{slug}/saison-{n}/              ← season page (valid)
  - https://voiranime.rip/{slug}/saison-{n}/episode-{m}/  ← episode page (valid)
  - https://voiranime.rip/{slug}/                         ← anime page (needs expand)
"""
from __future__ import annotations

import json
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

# Episode URL pattern: /{slug}/saison-N/episode-M/
_EP_URL_RE = re.compile(
    rf'^https?://(?:www\.)?{re.escape(DOMAIN)}/[^/]+/saison-\d+/episode-\d+/?$',
    re.IGNORECASE,
)
# Season URL pattern: /{slug}/saison-N/
_SEASON_URL_RE = re.compile(
    rf'^https?://(?:www\.)?{re.escape(DOMAIN)}/[^/]+/saison-\d+/?$',
    re.IGNORECASE,
)
# Anime URL pattern: /{slug}/
_ANIME_URL_RE = re.compile(
    rf'^https?://(?:www\.)?{re.escape(DOMAIN)}/[^/]+/?$',
    re.IGNORECASE,
)


class VoirAnimeSite:
    """voiranime.rip site — custom (non-WordPress) structure."""

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
        """Voiranime is reachable without Cloudflare cookies in most cases."""
        try:
            r = network.get(f"{BASE_URL}/", timeout=10)
            if r.status_code == 200:
                print_status("VoirAnime accessible.", "success")
                return True
            if r.status_code in (403, 503):
                print_status(
                    "VoirAnime bloqué (Cloudflare?). Réessaie plus tard ou utilise un VPN.",
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
        """Search via /search?q=... and parse the results."""
        if not query.strip():
            return []
        headers = headers or self.get_headers()
        search_url = f"{BASE_URL}/search?q={quote(query)}"
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

        # Result cards link to anime pages like /{slug}/
        # We look for <a href="/slug/"> where slug is not a known section
        known_sections = {
            "", "anime", "film", "catalogue", "search", "tags",
            "aide", "dmca", "img", "js", "css", "api",
            "planning", "profil", "login", "register", "user",
            "search.php", "compte", "connexion", "inscription",
        }

        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            if not title or href in seen:
                continue
            # Normalize to absolute
            full = urljoin(f"{BASE_URL}/", href)
            # Must be on voiranime.rip
            if not self.matches(full):
                continue
            # Extract the path
            try:
                from urllib.parse import urlparse
                path = urlparse(full).path.strip("/")
            except Exception:
                continue
            if not path:
                continue
            # First segment must not be a known section
            first_seg = path.split("/")[0].lower()
            # Also skip if it ends with .php (search.php, etc.)
            if first_seg.endswith(".php"):
                continue
            if first_seg in known_sections:
                continue
            # Must be an anime page (single segment, no season/episode)
            if "/" in path:
                continue
            # Skip very short titles (likely nav buttons)
            if len(title) < 2:
                continue
            seen.add(full)
            results.append({
                "title": title,
                "url": full,
                "support": "Anime Supported",
            })
            if len(results) >= 30:
                break

        return results

    # ------------------------------------------------------------------
    # Expand (find seasons from anime page)
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

        # Look for /{slug}/saison-N/ links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href in seen:
                continue
            full = urljoin(url, href)
            # Must be a season URL (not just any link on the page)
            if "/saison-" not in full.lower():
                continue
            if not _SEASON_URL_RE.match(full):
                continue
            seen.add(full)
            # Clean up the name: remove "Anime" prefix if present, trim
            raw_text = a.get_text(strip=True)
            name = self._clean_season_name(raw_text, full)
            results.append({"name": name, "url": full})

        # Dedupe by URL (keep order)
        unique: List[Dict[str, str]] = []
        seen_urls = set()
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                unique.append(r)
        return unique

    @staticmethod
    def _clean_season_name(raw: str, url: str) -> str:
        """Clean up a season name extracted from the page.

        Voiranime often concatenates the anime title + 'Saison N' + time
        (e.g. 'AnimeFarming Life in Another WorldSaison 216:30').
        We extract a clean 'Saison N' name from the URL as fallback.
        """
        if not raw:
            return VoirAnimeSite._extract_season_name(url)
        # Try to extract season number from URL for a clean name
        m = re.search(r'/saison-(\d+)/?', url, re.IGNORECASE)
        if m:
            return f"Saison {m.group(1)}"
        return raw[:80]  # truncate if too long

    @staticmethod
    def _extract_season_name(url: str) -> str:
        m = re.search(r'/saison-(\d+)/?', url, re.IGNORECASE)
        if m:
            return f"Saison {m.group(1)}"
        return "Saison"

    # ------------------------------------------------------------------
    # Validate URL
    # ------------------------------------------------------------------
    def validate(self, url: str) -> bool:
        """A valid URL is a season page or an episode page."""
        if not self.matches(url):
            return False
        return bool(_SEASON_URL_RE.match(url) or _EP_URL_RE.match(url))

    # ------------------------------------------------------------------
    # Episodes — scrape episode URLs from a season page
    # ------------------------------------------------------------------
    def fetch_episodes(self, url: str,
                       headers: Optional[Dict] = None) -> Optional[Dict[str, List[str]]]:
        """Scrape episode URLs from a season page.

        Returns {"Player 1": [url1, url2, ...]}.
        The actual embed URLs are resolved per-episode at download time
        by fetch_video_source (which calls the right extractor based on
        the iframe src found on the episode page).
        """
        headers = headers or self.get_headers()
        try:
            r = network.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                print_status(f"VoirAnime page HTTP {r.status_code}", "error")
                return None
            html = r.text
        except Exception as e:
            print_status(f"Erreur fetch page saison: {e}", "error")
            return None

        soup = BeautifulSoup(html, "html.parser")
        episode_urls: List[str] = []
        seen = set()

        # Find all /{slug}/saison-N/episode-M/ links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href in seen:
                continue
            full = urljoin(url, href)
            if _EP_URL_RE.match(full):
                seen.add(full)
                episode_urls.append(full)

        if not episode_urls:
            print_status("Aucun épisode trouvé sur VoirAnime", "warning")
            return {}

        # Sort by episode number (the URLs contain "episode-N")
        def _ep_num(u: str) -> int:
            m = re.search(r'/episode-(\d+)/?', u, re.IGNORECASE)
            return int(m.group(1)) if m else 0
        episode_urls.sort(key=_ep_num)

        print_status(f"VoirAnime: {len(episode_urls)} épisodes trouvés", "success")
        return {"Player 1": episode_urls}

    # ------------------------------------------------------------------
    # Custom: extract the video embed URL from an episode page.
    # This is called by fetch_video_source via the dispatch in
    # src/extractors/__init__.py (see the voiranime case added there).
    # ------------------------------------------------------------------
    def extract_episode_video(self, episode_url: str,
                              headers: Optional[Dict] = None) -> Optional[str]:
        """Extract the embed URL (Sibnet/Vidmoly/etc.) from a VoirAnime episode page.

        The page contains:
          <iframe id="videoPlayer" src="https://video.sibnet.ru/shell.php?videoid=XXX">
        and a JS dict:
          const videoUrls = {"vf":"...", "vostfr":"..."};

        We try the iframe src first (most reliable), then fall back to
        parsing videoUrls.
        """
        headers = headers or self.get_headers()
        try:
            r = network.get(episode_url, headers=headers, timeout=15)
            if r.status_code != 200:
                return None
            html = r.text
        except Exception:
            return None

        # 1. Try iframe with id=videoPlayer
        soup = BeautifulSoup(html, "html.parser")
        iframe = soup.find("iframe", id="videoPlayer") or soup.find("iframe", src=True)
        if iframe and iframe.get("src"):
            return iframe["src"]

        # 2. Fallback: parse the videoUrls JS dict
        # Pattern: videoUrls = {"vf":"URL","vostfr":"URL"};
        m = re.search(
            r'videoUrls\s*=\s*(\{[^}]+\})',
            html,
        )
        if m:
            try:
                # JS dict → JSON (replace single quotes, etc.)
                dict_str = m.group(1)
                # Remove trailing semicolons/commas
                dict_str = dict_str.strip().rstrip(';').rstrip(',')
                # Try to parse as JSON (it usually is valid JSON)
                try:
                    data = json.loads(dict_str)
                except json.JSONDecodeError:
                    # Fall back to regex extraction of URLs
                    urls = re.findall(r':\s*"(https?://[^"]+)"', dict_str)
                    if urls:
                        return urls[0]
                else:
                    # Prefer vostfr, then vf, then first available
                    for key in ("vostfr", "vf", "vo"):
                        if key in data and data[key]:
                            return data[key]
                    if data:
                        first_val = next(iter(data.values()))
                        if first_val:
                            return first_val
            except Exception:
                pass

        # 3. Last resort: any iframe src in the page
        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"]
            if src.startswith("http"):
                return src

        return None

    # ------------------------------------------------------------------
    # Scans — VoirAnime doesn't host scans
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
