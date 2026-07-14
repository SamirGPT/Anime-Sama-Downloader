#!/usr/bin/env python3
"""Anime-Sama Downloader — entry point.

Usage:
    python3 main.py                                  # interactive mode
    python3 main.py --search "naruto"
    python3 main.py --url "https://anime-sama.eu/catalogue/naruto/saison1/vostfr/" --episodes "1-10" --mp4 --fast
    python3 main.py --url "..." --latest
    python3 main.py --url "..." --list
    python3 main.py --settings

Run `python3 main.py --help` for the full reference.
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from src.cli import main as cli_main
        return cli_main()
    except KeyboardInterrupt:
        print("\n[!] Interrompu")
        return 130
    except Exception as e:
        print(f"[!] Erreur fatale: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
