"""Embed4me extractor — AES-CBC encrypted API response.

v5.0 FIX: The API returns URLs with a raw IP address (e.g. https://203.188.166.47/...).
The server refuses these with HTTP 403 because:
  1. The Host header is the IP, not the expected domain
  2. No Referer header from the embed4me domain

Solution: Replace the IP with the embed4me CDN domain (lpayer.embed4me.com)
and send proper Host + Referer headers. This was causing the 403 error
reported by users.

The AES key/IV are hardcoded by the service (this is the service's own
obfuscation, not a vulnerability in our code). We decrypt the response
to get the M3U8 source URL.
"""
from __future__ import annotations

import re
import json
import binascii
from typing import Optional
from urllib.parse import urlparse

from src import network
from src.ui import print_status, print_debug


# Service-imposed static key/IV (shipped in their JS)
KEY = b"kiemtienmua911ca"
IV = b"1234567890oiuytr"

# The CDN domain that should be used instead of the raw IP
EMBED4ME_CDN_DOMAIN = "lpayer.embed4me.com"


def _decrypt(hex_str: str) -> Optional[str]:
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
    except ImportError:
        print_status("pycryptodome manquant — installe avec: pip install pycryptodome", "error")
        return None
    try:
        data = binascii.unhexlify(hex_str)
        cipher = AES.new(KEY, AES.MODE_CBC, IV)
        decrypted = unpad(cipher.decrypt(data), AES.block_size)
        return decrypted.decode("utf-8")
    except Exception as e:
        print_status(f"Embed4me decrypt error: {e}", "debug")
        return None


def _fix_embed4me_url(url: str) -> str:
    """Fix an embed4me CDN URL by replacing the raw IP with the proper domain.

    The API returns URLs like: https://203.188.166.47/v4/.../master.m3u8
    The server refuses these with 403 because the Host header is the IP.
    Replace with: https://lpayer.embed4me.com/v4/.../master.m3u8
    """
    if not url:
        return url
    try:
        parsed = urlparse(url)
        # If the hostname is an IP address, replace it
        host = parsed.hostname
        if host and re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host):
            new_url = url.replace(f"://{host}", f"://{EMBED4ME_CDN_DOMAIN}", 1)
            print_debug(f"Embed4me: IP {host} → {EMBED4ME_CDN_DOMAIN}")
            return new_url
    except Exception:
        pass
    return url


def extract_embed4me(url: str) -> Optional[str]:
    """Extract the M3U8 URL from an Embed4me embed page.

    Returns a URL that has been fixed (raw IPs replaced with the CDN domain)
    so that downstream requests don't get 403 errors.
    """
    # Extract video ID from URL fragment or query
    m = re.search(r'#([a-zA-Z0-9]+)', url)
    if not m:
        m = re.search(r'[?&]id=([a-zA-Z0-9]+)', url)
    if not m:
        print_status("Embed4me: ID vidéo introuvable", "warning")
        return None

    video_id = m.group(1)
    api_url = (
        f"https://{EMBED4ME_CDN_DOMAIN}/api/v1/video?id={video_id}"
        f"&w=1920&h=1080&r=https://{EMBED4ME_CDN_DOMAIN}/"
    )
    headers = {
        "Referer": f"https://{EMBED4ME_CDN_DOMAIN}/",
        "Origin": f"https://{EMBED4ME_CDN_DOMAIN}",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        r = network.get(api_url, headers=headers, timeout=15)
        if r.status_code != 200:
            print_status(f"Embed4me API HTTP {r.status_code}", "warning")
            return None
        text = r.text.strip()
        # Strip surrounding quotes if present
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
    except Exception as e:
        print_status(f"Embed4me API error: {e}", "error")
        return None

    decrypted = _decrypt(text)
    if not decrypted:
        return None
    try:
        data = json.loads(decrypted)
    except json.JSONDecodeError:
        print_status("Embed4me: réponse JSON invalide", "warning")
        return None

    source = data.get("source")
    if not source:
        return None

    # FIX: Replace raw IP in the URL with the CDN domain
    fixed_source = _fix_embed4me_url(source)
    if fixed_source != source:
        print_status(
            f"Embed4me: URL corrigée (IP → {EMBED4ME_CDN_DOMAIN})",
            "info",
        )
    return fixed_source
