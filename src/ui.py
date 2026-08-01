"""UI helpers — colors, headers, status messages.

Detected environment:
- Termux (Android): no emoji width issues, but limited terminal width.
- Ubuntu/Linux: full ANSI support.
- Windows: colors disabled unless ANSI enabled.

Robust: never crashes if stdout is not a TTY (e.g. piped to a file).
"""
from __future__ import annotations

import os
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------
IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "")
IS_WINDOWS = os.name == "nt"
IS_TTY = sys.stdout.isatty()


def _supports_color() -> bool:
    if IS_WINDOWS:
        return False
    if not IS_TTY:
        return False
    term = os.environ.get("TERM", "").lower()
    if term in ("dumb", ""):
        return False
    return True


_USE_COLOR = _supports_color()


def disable_colors() -> None:
    """Disable color output (used by --no-color)."""
    global _USE_COLOR
    _USE_COLOR = False


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
class Colors:
    HEADER = "\033[95m" if _USE_COLOR else ""
    OKBLUE = "\033[94m" if _USE_COLOR else ""
    OKCYAN = "\033[96m" if _USE_COLOR else ""
    OKGREEN = "\033[92m" if _USE_COLOR else ""
    WARNING = "\033[93m" if _USE_COLOR else ""
    FAIL = "\033[91m" if _USE_COLOR else ""
    ENDC = "\033[0m" if _USE_COLOR else ""
    BOLD = "\033[1m" if _USE_COLOR else ""
    UNDERLINE = "\033[4m" if _USE_COLOR else ""
    GREY = "\033[90m" if _USE_COLOR else ""


# ---------------------------------------------------------------------------
# Status / logging
# ---------------------------------------------------------------------------
_VERBOSITY = "info"  # one of: quiet, error, warning, info, debug


def set_verbosity(level: str) -> None:
    global _VERBOSITY
    _VERBOSITY = level.lower()


_ORDER = {"quiet": 0, "error": 1, "warning": 2, "info": 3, "debug": 4}


def _should_print(level: str) -> bool:
    return _ORDER.get(level, 3) <= _ORDER.get(_VERBOSITY, 3)


_ICONS = {
    "info": "[*]",
    "success": "[+]",
    "error": "[!]",
    "warning": "[!]",
    "loading": "[~]",
    "debug": "[D]",
}

_COLORS = {
    "info": Colors.OKBLUE,
    "success": Colors.OKGREEN,
    "error": Colors.FAIL,
    "warning": Colors.WARNING,
    "loading": Colors.OKCYAN,
    "debug": Colors.GREY,
}


def print_status(message: str, status_type: str = "info") -> None:
    """Print a status message with consistent prefix and color.

    Respects verbosity: 'quiet' prints nothing except fatal errors.
    """
    if not _should_print(status_type):
        return
    icon = _ICONS.get(status_type, "[*]")
    color = _COLORS.get(status_type, "")
    end = Colors.ENDC if color else ""
    print(f"{color}{icon} {message}{end}")


def print_debug(message: str) -> None:
    """Alias for print_status(message, 'debug')."""
    print_status(message, "debug")


def print_separator(char: str = "─", length: int = 65) -> None:
    if not _should_print("info"):
        return
    print(f"{Colors.OKBLUE}{char * length}{Colors.ENDC}")


def print_header() -> None:
    if not _should_print("info"):
        return
    print(f"""
{Colors.HEADER}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║              ANIME-SAMA DOWNLOADER  v5.0                     ║
║       Multi-sites • 18 players • Termux/Ubuntu edition       ║
╚══════════════════════════════════════════════════════════════╝
{Colors.ENDC}
{Colors.OKCYAN}Télécharge animes & scans depuis anime-sama.to + voiranime.rip{Colors.ENDC}
""")


def print_tutorial() -> None:
    tutorial = f"""
{Colors.BOLD}{Colors.HEADER}TUTORIEL RAPIDE{Colors.ENDC}
{Colors.BOLD}{'=' * 65}{Colors.ENDC}

{Colors.OKGREEN}{Colors.BOLD}1. Trouver l'anime{Colors.ENDC}
  - Visite https://anime-sama.eu/catalogue/
  - Clique sur l'anime, choisis la saison et la langue
  - Copie l'URL complète depuis la barre d'adresse

{Colors.OKGREEN}{Colors.BOLD}2. Lancer le downloader{Colors.ENDC}
  $ python3 main.py
  Puis colle l'URL quand demandé.

{Colors.OKGREEN}{Colors.BOLD}3. Exemples CLI{Colors.ENDC}
  $ python3 main.py --search "naruto"
  $ python3 main.py --url "https://anime-sama.eu/catalogue/naruto/saison1/vostfr/" --episodes "1-10" --mp4
  $ python3 main.py --url "..." --latest                # Dernier épisode
  $ python3 main.py --url "..." --list                  # Lister sans télécharger

{Colors.WARNING}{Colors.BOLD}Notes{Colors.ENDC}
  - Sur Termux : installe ffmpeg avec `pkg install ffmpeg`
  - Sur Ubuntu : `sudo apt install ffmpeg`
  - Si Cloudflare bloque : utilise --cf-clearance et --user-agent
"""
    print(tutorial)


def prompt(message: str) -> str:
    """Read input with a styled prompt."""
    try:
        return input(f"{Colors.BOLD}{message}{Colors.ENDC}").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def confirm(message: str, default: bool = False) -> bool:
    """Yes/no confirmation."""
    suffix = " [Y/n]" if default else " [y/N]"
    raw = prompt(message + suffix).lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class DownloaderError(Exception):
    """Base class for downloader errors."""


class NetworkError(DownloaderError):
    """Network-related error."""


class ExtractorError(DownloaderError):
    """Source extraction error."""


class ConfigError(DownloaderError):
    """Configuration error."""
