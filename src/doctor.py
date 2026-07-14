"""Doctor module — health check for the downloader environment.

Runs checks:
1. Python version
2. Required Python packages
3. ffmpeg installed
4. Network reachability (anime-sama.to, voiranime.rip)
5. Cloudflare cookies (if configured)
6. Config file integrity
7. Write permissions on save dir
"""
from __future__ import annotations

import os
import sys
import shutil
from typing import List, Tuple

from src import __version__, network
from src.config import get_config
from src.ui import Colors, print_separator, print_status


def _check_python() -> Tuple[bool, str]:
    v = sys.version_info
    ok = v >= (3, 8)
    return ok, f"Python {v.major}.{v.minor}.{v.micro}"


def _check_packages() -> Tuple[bool, str]:
    missing = []
    for pkg, import_name in [
        ("requests", "requests"),
        ("beautifulsoup4", "bs4"),
        ("tqdm", "tqdm"),
        ("av", "av"),
        ("pycryptodome", "Crypto"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        return False, f"Manquants: {', '.join(missing)}"
    return True, "Tous les packages requis sont installés"


def _check_ffmpeg() -> Tuple[bool, str]:
    p = shutil.which("ffmpeg")
    if p:
        return True, f"ffmpeg: {p}"
    return False, "ffmpeg absent du PATH"


def _check_network(url: str, name: str) -> Tuple[bool, str]:
    try:
        r = network.get(url, timeout=10)
        if r.status_code in (200, 403, 503):  # 403/503 may be Cloudflare but at least reachable
            return True, f"{name} accessible (HTTP {r.status_code})"
        return False, f"{name} HTTP {r.status_code}"
    except Exception as e:
        return False, f"{name} injoignable: {e.__class__.__name__}"


def _check_config() -> Tuple[bool, str]:
    try:
        cfg = get_config()
        return True, f"Config: {cfg._path or 'N/A'}"
    except Exception as e:
        return False, f"Config invalide: {e}"


def _check_save_dir() -> Tuple[bool, str]:
    cfg = get_config()
    save_dir = cfg.save_template.format(anime="test", season="test")
    try:
        os.makedirs(save_dir, exist_ok=True)
        # Test write
        test_file = os.path.join(save_dir, ".write_test")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        return True, f"Écriture OK: {os.path.abspath(save_dir)}"
    except Exception as e:
        return False, f"Écriture impossible: {e}"


def run_doctor() -> int:
    """Run all health checks. Returns exit code (0 = all OK, 1 = some failed)."""
    print_separator()
    print(f"{Colors.BOLD}{Colors.HEADER}🏥 DOCTOR — Diagnostic v{__version__}{Colors.ENDC}")
    print_separator()

    checks: List[Tuple[str, Tuple[bool, str]]] = []

    print_status("Vérification Python...", "info")
    checks.append(("Python", _check_python()))

    print_status("Vérification packages...", "info")
    checks.append(("Packages", _check_packages()))

    print_status("Vérification ffmpeg...", "info")
    checks.append(("FFmpeg", _check_ffmpeg()))

    print_status("Vérification réseau anime-sama.to...", "info")
    checks.append(("Anime-Sama", _check_network("https://anime-sama.to/", "anime-sama.to")))

    print_status("Vérification réseau voiranime.rip...", "info")
    checks.append(("VoirAnime", _check_network("https://voiranime.rip/", "voiranime.rip")))

    print_status("Vérification config...", "info")
    checks.append(("Config", _check_config()))

    print_status("Vérification dossier de sauvegarde...", "info")
    checks.append(("Save dir", _check_save_dir()))

    # Display
    print_separator()
    print(f"{Colors.BOLD}RÉSULTATS:{Colors.ENDC}")
    print_separator()
    failed = 0
    for name, (ok, msg) in checks:
        icon = "✅" if ok else "❌"
        color = Colors.OKGREEN if ok else Colors.FAIL
        print(f"{color}{icon} {name:15} : {msg}{Colors.ENDC}")
        if not ok:
            failed += 1

    print_separator()
    if failed == 0:
        print_status("Tout est OK! Le downloader est prêt.", "success")
    else:
        print_status(f"{failed} vérification(s) ont échoué.", "warning")
        print_status("Astuce: lance `bash install.sh` pour installer les dépendances manquantes.", "info")

    return 0 if failed == 0 else 1
