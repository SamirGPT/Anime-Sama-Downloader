"""Embed4me extractor — AES-CBC encrypted API response.

The AES key/IV are hardcoded by the service (this is the service's own
obfuscation, not a vulnerability in our code). We decrypt the response
to get the M3U8 source URL.
"""
from __future__ import annotations

import re
import json
import binascii
from typing import Optional

from src import network
from src.ui import print_status


# Service-imposed static key/IV (NOT a security issue — this is the
# obfuscation the service itself uses; the key is shipped in their JS).
KEY = b"kiemtienmua911ca"
IV = b"1234567890oiuytr"


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


def extract_embed4me(url: str) -> Optional[str]:
    # Extract video ID from URL fragment or query
    m = re.search(r'#([a-zA-Z0-9]+)', url)
    if not m:
        m = re.search(r'[?&]id=([a-zA-Z0-9]+)', url)
    if not m:
        print_status("Embed4me: ID vidéo introuvable", "warning")
        return None

    video_id = m.group(1)
    api_url = (
        f"https://lpayer.embed4me.com/api/v1/video?id={video_id}"
        f"&w=1920&h=1080&r=https://lpayer.embed4me.com/"
    )
    headers = {
        "Referer": "https://lpayer.embed4me.com/",
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
    return data.get("source")
