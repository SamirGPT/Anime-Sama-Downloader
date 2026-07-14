"""Cloudflare detection and cookie setup.

Logic flow:
1. Probe the domain — if `/catalogue` is reachable, no cookies needed.
2. Otherwise, prompt the user for cf_clearance + User-Agent.
3. Validate the cookies with a follow-up request.
4. Loop until valid or user cancels.
"""
from __future__ import annotations

from typing import Tuple

from src import network
from src.config import get_config
from src.ui import Colors, print_separator, print_status, prompt


DOMAIN = "anime-sama.to"


def is_cloudflare_active() -> bool:
    """Probe the site — return True if Cloudflare blocks us."""
    try:
        r = network.get(f"https://{DOMAIN}/", timeout=10)
        # Cloudflare challenge pages contain these markers
        body = r.text.lower()
        if "cf-mitigated" in body or "cf_chl_opt" in body or "just a moment" in body:
            return True
        if r.status_code in (403, 503):
            return True
        # If /catalogue link is present, we're in
        if "/catalogue" in body:
            return False
        # Fallback heuristic
        return r.status_code >= 400
    except Exception as e:
        print_status(f"Could not probe {DOMAIN}: {e}", "warning")
        return False


def tutorial_input() -> Tuple[str, str]:
    print_status("Cloudflare bloque l'accès. Configurons les cookies.", "info")
    print_status(f"1. Ouvre https://{DOMAIN}/ dans ton navigateur.", "info")
    print_status("2. F12 → Application → Cookies → " + DOMAIN, "info")
    print_status("3. Copie la valeur du cookie 'cf_clearance'", "info")
    cf = prompt("Colle cf_clearance ici: ")
    print_status("4. Dans la console (F12 → Console), exécute: navigator.userAgent", "info")
    print_status("5. Copie la valeur (sans les quotes)", "info")
    ua = prompt("Colle le User-Agent ici: ")
    return cf, ua


def setup_cloudflare() -> bool:
    """Interactive Cloudflare cookie setup. Returns True on success."""
    if not is_cloudflare_active():
        print_status("Cloudflare ne bloque pas — accès direct.", "success")
        return True

    cfg = get_config()
    if cfg.has_cookies():
        if check_cookies():
            print_status("Cookies Cloudflare existants valides.", "success")
            return True
        print_status("Cookies Cloudflare expirés ou invalides.", "warning")

    while True:
        cf, ua = tutorial_input()
        if not cf or not ua:
            print_status("Valeurs vides — annulation.", "error")
            return False
        cfg.set_cookies(cf, ua)
        if check_cookies():
            print_status("Cookies valides !", "success")
            return True
        print_status("Cookies invalides. Réessaie.", "error")
        print_status("(Astuce: le User-Agent doit être identique à celui du navigateur)", "warning")


def check_cookies() -> bool:
    """Validate currently stored cookies against the domain."""
    cfg = get_config()
    if not cfg.has_cookies():
        return False
    try:
        r = network.get(
            f"https://{DOMAIN}/",
            headers={
                "Cookie": f"cf_clearance={cfg.cf_clearance}",
                "User-Agent": cfg.user_agent,
            },
            timeout=10,
        )
        return r.status_code not in (403, 503)
    except Exception:
        return False


def get_anime_sama_headers() -> dict:
    """Build the standard headers for anime-sama.eu requests."""
    cfg = get_config()
    h = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": f"https://{DOMAIN}/",
        "Origin": f"https://{DOMAIN}",
    }
    if cfg.has_cookies():
        h["Cookie"] = f"cf_clearance={cfg.cf_clearance}"
        h["User-Agent"] = cfg.user_agent
    return h
