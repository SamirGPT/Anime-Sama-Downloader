"""Command-line interface — argparse + interactive mode.

v4.0:
- Multi-sites (anime-sama.to + voiranime.rip)
- Subcommands: update, doctor, history
- --from-file for batch download
- --watch for new-episode monitoring
- Faster defaults (max_workers=8, max_segment_workers=16)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from src import network, __version__
from src.cloudflare import setup_cloudflare, get_anime_sama_headers
from src.config import get_config, set_config, Config
from src.sites import get_site_for_url, get_all_sites, get_site_by_key, SiteNotFound
from src.fetchers import fetch_video_source
from src.downloader import download_episode
from src.mal import create_match_file
from src.sources import source_label, is_supported, find_source
from src.ui import (
    Colors, print_header, print_separator, print_status, print_tutorial,
    prompt, confirm, set_verbosity, disable_colors,
)
from src.utils import (
    extract_anime_name, extract_season_slug, format_save_path,
    is_termux, ffmpeg_path, get_default_max_workers,
)


# ---------------------------------------------------------------------------
# Pre-argparse subcommand dispatch (so `update` and `doctor` work without
# Cloudflare setup etc.)
# ---------------------------------------------------------------------------
def _dispatch_subcommand(argv: List[str]) -> Optional[int]:
    """Handle subcommands that bypass the main flow.

    Returns an exit code if the subcommand was handled, None otherwise.
    """
    if not argv:
        return None
    cmd = argv[0].lower()

    if cmd in ("update", "upgrade", "self-update"):
        from src.updater import self_update
        return 0 if self_update() else 1

    if cmd in ("doctor", "health", "check"):
        from src.doctor import run_doctor
        return run_doctor()

    if cmd in ("history", "hist"):
        return _history_command(argv[1:])

    if cmd in ("sites", "list-sites"):
        print_header()
        print(f"{Colors.BOLD}{Colors.HEADER}🌐 SITES SUPPORTÉS{Colors.ENDC}")
        print_separator()
        for s in get_all_sites():
            print(f"{Colors.OKCYAN}{s.key:15}{Colors.ENDC} → {s.display} ({s.domain})")
        return 0

    if cmd in ("version", "--version", "-V"):
        print(f"Anime-Sama Downloader v{__version__}")
        return 0

    if cmd in ("chat", "bot", "assistant"):
        from src.chatbot import chat_loop, setup_api_key
        # Check for --setup
        rest = argv[1:]
        if rest and rest[0] in ("--setup", "setup"):
            return setup_api_key()
        # One-shot mode: chat "natural language request"
        if rest and not rest[0].startswith("-"):
            one_shot = " ".join(rest)
            return chat_loop(one_shot=one_shot)
        return chat_loop()

    return None


def _history_command(args: List[str]) -> int:
    from src.history import list_history, clear_history, stats
    if args and args[0] in ("clear", "wipe"):
        n = clear_history()
        print_status(f"Historique effacé ({n} entrées)", "success")
        return 0
    if args and args[0] in ("stats", "stat"):
        s = stats()
        print(f"\n{Colors.BOLD}{Colors.HEADER}📊 STATISTIQUES{Colors.ENDC}")
        print_separator()
        print(f"Total téléchargements: {s['total']}")
        if s.get("by_anime"):
            print(f"\n{Colors.OKCYAN}Par anime:{Colors.ENDC}")
            for anime, count in sorted(s["by_anime"].items(), key=lambda x: -x[1])[:10]:
                print(f"  {anime}: {count}")
        if s.get("by_site"):
            print(f"\n{Colors.OKCYAN}Par site:{Colors.ENDC}")
            for site, count in s["by_site"].items():
                print(f"  {site}: {count}")
        return 0

    # Default: list
    filter_arg = args[0] if args else None
    records = list_history(limit=50, anime_filter=filter_arg)
    if not records:
        print_status("Historique vide", "info")
        return 0
    print(f"\n{Colors.BOLD}{Colors.HEADER}📜 HISTORIQUE ({len(records)} derniers){Colors.ENDC}")
    print_separator()
    for r in records:
        ts = r.get("timestamp", "?")[:19]
        anime = r.get("anime", "?")
        ep = r.get("episode", "?")
        site = r.get("site", "?")
        print(f"{Colors.GREY}{ts}{Colors.ENDC}  {Colors.OKGREEN}{anime}{Colors.ENDC} EP{ep} ({site})")
    return 0


# ---------------------------------------------------------------------------
# Episode listing
# ---------------------------------------------------------------------------
def list_episodes(episodes: dict, player: Optional[str] = None) -> None:
    for cat, urls in episodes.items():
        if player and cat != player:
            continue
        print(f"\n{Colors.BOLD}{Colors.OKCYAN}🎮 {cat}:{Colors.ENDC} ({len(urls)} épisodes)")
        print_separator("─", 40)
        for i, url in enumerate(urls, 1):
            src = find_source(url)
            if src and src.supported:
                print(f"{Colors.OKGREEN}  {i:2d}. Épisode {i} — {src.display} ✅{Colors.ENDC}")
            elif src:
                print(f"{Colors.FAIL}  {i:2d}. Épisode {i} — {src.display} ❌{Colors.ENDC}")
            else:
                print(f"{Colors.WARNING}  {i:2d}. Épisode {i} — Inconnu ⚠️{Colors.ENDC}")


# ---------------------------------------------------------------------------
# Player selection
# ---------------------------------------------------------------------------
def get_player_choice(episodes: dict) -> Optional[str]:
    print(f"\n{Colors.BOLD}{Colors.HEADER}🎮 SÉLECTION PLAYER{Colors.ENDC}")
    print_separator()
    players = list(episodes.keys())
    for i, p in enumerate(players, 1):
        working = sum(1 for u in episodes[p] if is_supported(u))
        total = len(episodes[p])
        print(f"{Colors.OKCYAN}  {i}. {p} ({working}/{total} valides){Colors.ENDC}")
    while True:
        raw = prompt(f"Choix (1-{len(players)}) ou nom du player: ")
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(players):
                return players[idx]
            print_status("Invalide", "error")
        else:
            key = raw.lower()
            if key.isdigit():
                choice = f"Player {key}"
            elif key.startswith("player") and key[6:].isdigit():
                choice = f"Player {key[6:]}"
            else:
                choice = raw.title()
            if choice in episodes:
                return choice
            print_status("Invalide", "error")


# ---------------------------------------------------------------------------
# Episode selection (interactive)
# ---------------------------------------------------------------------------
def get_episode_choice(episodes: dict, player: str) -> Optional[List[int]]:
    print(f"\n{Colors.BOLD}{Colors.HEADER}📺 SÉLECTION ÉPISODE — {player}{Colors.ENDC}")
    print_separator()
    urls = episodes[player]
    n = len(urls)
    for i, u in enumerate(urls, 1):
        src = find_source(u)
        if src and src.supported:
            print(f"{Colors.OKGREEN}  {i:2d}. Épisode {i} — {src.display} ✅{Colors.ENDC}")
        elif src:
            print(f"{Colors.FAIL}  {i:2d}. Épisode {i} — {src.display} ❌{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}  {i:2d}. Épisode {i} — Inconnu ⚠️{Colors.ENDC}")

    while True:
        raw = prompt(f"Épisodes (1-{n}, ex: 1,3,5-10 ou 'all'): ").lower()
        if not raw:
            continue
        try:
            if raw == "all":
                valid = [i for i, u in enumerate(urls) if is_supported(u)]
                if not valid:
                    print_status("Aucun épisode valide", "error")
                    continue
                return valid
            selected = []
            seen = set()
            for part in raw.split(','):
                part = part.strip()
                if not part:
                    continue
                if '-' in part:
                    a, b = part.split('-', 1)
                    a, b = int(a), int(b)
                    for num in range(a, b + 1):
                        if num in seen or not (1 <= num <= n):
                            continue
                        seen.add(num)
                        if is_supported(urls[num - 1]):
                            selected.append(num - 1)
                        else:
                            print_status(f"Épisode {num} non supporté", "warning")
                else:
                    num = int(part)
                    if num in seen or not (1 <= num <= n):
                        continue
                    seen.add(num)
                    if is_supported(urls[num - 1]):
                        selected.append(num - 1)
                    else:
                        print_status(f"Épisode {num} non supporté", "warning")
            if selected:
                return selected
            print_status("Aucun épisode valide", "error")
        except ValueError:
            print_status("Format invalide", "error")


# ---------------------------------------------------------------------------
# Parse episode range from CLI
# ---------------------------------------------------------------------------
def parse_episodes_arg(arg: str, total: int, urls: list) -> Optional[List[int]]:
    arg = arg.lower().strip()
    if arg == "all":
        return [i for i, u in enumerate(urls) if is_supported(u)]
    if arg == "latest":
        for i in range(len(urls) - 1, -1, -1):
            if is_supported(urls[i]):
                return [i]
        return None
    selected = []
    seen = set()
    for part in arg.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            if '-' in part:
                a, b = part.split('-', 1)
                a, b = int(a), int(b)
                for num in range(a, b + 1):
                    if num in seen or not (1 <= num <= total):
                        continue
                    seen.add(num)
                    if is_supported(urls[num - 1]):
                        selected.append(num - 1)
            else:
                num = int(part)
                if num in seen or not (1 <= num <= total):
                    continue
                seen.add(num)
                if is_supported(urls[num - 1]):
                    selected.append(num - 1)
        except ValueError:
            print_status(f"Format invalide: {part}", "error")
            return None
    return selected


# ---------------------------------------------------------------------------
# Settings menu
# ---------------------------------------------------------------------------
def settings_menu() -> None:
    cfg = get_config()
    while True:
        print_header()
        print(f"\n{Colors.BOLD}{Colors.HEADER}⚙️  CONFIGURATION{Colors.ENDC}")
        print_separator()
        print(f"{Colors.OKCYAN} 1.{Colors.ENDC} Dossier de sauvegarde (template)        : {Colors.WARNING}{cfg.save_template}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 2.{Colors.ENDC} Dossier scans                            : {Colors.WARNING}{cfg.scan_dir}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 3.{Colors.ENDC} Outil de conversion                       : {Colors.WARNING}{cfg.convert_tool}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 4.{Colors.ENDC} Conversion auto .mp4                      : {Colors.WARNING}{'oui' if cfg.auto_mp4 else 'non'}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 5.{Colors.ENDC} Skip épisodes déjà téléchargés            : {Colors.WARNING}{'oui' if cfg.skip_existing else 'non'}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 6.{Colors.ENDC} Workers max (épisodes, 1-10)              : {Colors.WARNING}{cfg.max_workers}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 7.{Colors.ENDC} Workers max (segments .ts, 1-32)         : {Colors.WARNING}{cfg.max_segment_workers}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 8.{Colors.ENDC} Site par défaut                           : {Colors.WARNING}{cfg.default_site}{Colors.ENDC}")
        print(f"{Colors.OKCYAN} 9.{Colors.ENDC} Template nom de fichier                   : {Colors.WARNING}{cfg.filename_template}{Colors.ENDC}")
        print(f"{Colors.OKCYAN}10.{Colors.ENDC} Notifications de fin                      : {Colors.WARNING}{'oui' if cfg.notify_on_complete else 'non'}{Colors.ENDC}")
        print(f"{Colors.OKCYAN}11.{Colors.ENDC} Re-configurer Cloudflare (anime-sama.to)")
        print(f"{Colors.OKCYAN}12.{Colors.ENDC} Voir l'historique")
        print(f"{Colors.OKCYAN}13.{Colors.ENDC} Configurer la clé API Groq (chatbot)")
        print(f"{Colors.OKCYAN} 0.{Colors.ENDC} Retour")
        print_separator()
        choice = prompt("Choix: ")
        try:
            if choice == "1":
                tpl = prompt("Nouveau template (utilise {anime} et {season}): ")
                if tpl:
                    cfg.update(save_template=tpl)
                    print_status("Mis à jour!", "success")
            elif choice == "2":
                d = prompt("Nouveau dossier scans: ")
                if d:
                    cfg.update(scan_dir=d)
                    print_status("Mis à jour!", "success")
            elif choice == "3":
                t = prompt("Outil (auto/av/ffmpeg): ").lower()
                if t in ("auto", "av", "ffmpeg"):
                    cfg.update(convert_tool=t)
                    print_status("Mis à jour!", "success")
            elif choice == "4":
                cfg.update(auto_mp4=not cfg.auto_mp4)
                print_status(f"Conversion auto: {'oui' if cfg.auto_mp4 else 'non'}", "success")
            elif choice == "5":
                cfg.update(skip_existing=not cfg.skip_existing)
                print_status(f"Skip existing: {'oui' if cfg.skip_existing else 'non'}", "success")
            elif choice == "6":
                v = prompt(f"Workers épisodes (1-10) [{cfg.max_workers}]: ")
                n = int(v)
                if 1 <= n <= 10:
                    cfg.update(max_workers=n)
                    print_status("Mis à jour!", "success")
            elif choice == "7":
                v = prompt(f"Workers segments (1-32) [{cfg.max_segment_workers}]: ")
                n = int(v)
                if 1 <= n <= 32:
                    cfg.update(max_segment_workers=n)
                    print_status("Mis à jour!", "success")
            elif choice == "8":
                print("Sites disponibles:")
                for s in get_all_sites():
                    print(f"  {s.key:15} → {s.display}")
                k = prompt("Clé du site: ").lower()
                if get_site_by_key(k):
                    cfg.update(default_site=k)
                    print_status("Mis à jour!", "success")
            elif choice == "9":
                t = prompt("Template ({anime}, {num}, {season}): ")
                if t:
                    cfg.update(filename_template=t)
                    print_status("Mis à jour!", "success")
            elif choice == "10":
                cfg.update(notify_on_complete=not cfg.notify_on_complete)
                print_status(f"Notifications: {'oui' if cfg.notify_on_complete else 'non'}", "success")
            elif choice == "11":
                setup_cloudflare()
            elif choice == "12":
                _history_command([])
            elif choice == "13":
                from src.chatbot import setup_api_key
                setup_api_key()
            elif choice == "0":
                break
        except (ValueError, Exception) as e:
            print_status(f"Erreur: {e}", "error")
        if choice != "0":
            prompt("Entrée pour continuer...")


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=f"Anime-Sama Downloader v{__version__} — multi-sites + chatbot IA, Termux/Ubuntu",
        epilog="""\
Sous-commandes:
  chat         🤖 Discuter avec le chatbot IA (Groq + Qwen3)
  chat "..."   Exécuter une requête en langage naturel en one-shot
  chat --setup Configurer la clé API Groq
  update       Mettre à jour le programme depuis GitHub
  doctor       Diagnostiquer l'environnement (Python, ffmpeg, réseau, ...)
  history      Voir l'historique des téléchargements
  sites        Lister les sites supportés
  version      Afficher la version

Exemples:
  python3 main.py                                       # Mode interactif
  python3 main.py chat                                  # 🤖 Mode chatbot
  python3 main.py chat "télécharge naruto épisode 1"    # One-shot
  python3 main.py --search "naruto"
  python3 main.py --url "https://anime-sama.to/catalogue/naruto/saison1/vostfr/" --episodes "1-10" --mp4 --fast
  python3 main.py --url "https://voiranime.rip/naruto/" --episodes all
  python3 main.py --from-file animes.txt                # Batch download
  python3 main.py update                                # Auto-update
  python3 main.py doctor                                # Health check
""",
    )
    p.add_argument("--url", default=None, help="URL directe de la saison/scan")
    p.add_argument("--search", default=None, help="Rechercher un anime par nom")
    p.add_argument("--episodes", default=None,
                   help="Épisodes: '1,3,5-10' | 'all' | 'latest'")
    p.add_argument("--player", default=None, help="Player (ex: Sibnet, ou 1,2,3)")
    p.add_argument("--dest", default=None, help="Dossier de destination (override)")
    p.add_argument("--threads", action="store_true",
                   help="Télécharger plusieurs épisodes en parallèle")
    p.add_argument("--fast", action="store_true",
                   help="Segments .ts en parallèle (16 workers par défaut)")
    p.add_argument("--no-fast", action="store_true",
                   help="Désactiver le mode parallèle pour les segments")
    p.add_argument("--mp4", action="store_true",
                   help="Convertir automatiquement .ts → .mp4")
    p.add_argument("--ts", action="store_true",
                   help="Garder le format .ts (pas de conversion)")
    p.add_argument("--tool", default=None, choices=["auto", "av", "ffmpeg"],
                   help="Outil de conversion")
    p.add_argument("--no-mal", action="store_true",
                   help="Désactiver la recherche MyAnimeList")
    p.add_argument("--latest", action="store_true",
                   help="Télécharger uniquement le dernier épisode")
    p.add_argument("--list", action="store_true",
                   help="Lister les épisodes sans télécharger")
    p.add_argument("--dry-run", action="store_true",
                   help="Simuler sans rien télécharger")
    p.add_argument("--no-color", action="store_true", help="Désactiver les couleurs")
    p.add_argument("--proxy", default=None, help="Proxy HTTP(S) (ex: http://localhost:8080)")
    p.add_argument("--user-agent", default=None, help="User-Agent personnalisé")
    p.add_argument("--cf-clearance", default=None,
                   help="Cookie cf_clearance Cloudflare (non-interactif)")
    p.add_argument("--verbose", choices=["quiet", "error", "warning", "info", "debug"],
                   default="info", help="Niveau de verbosité")
    p.add_argument("--skip-cloudflare-check", action="store_true",
                   help="Passer la vérification Cloudflare au démarrage")
    p.add_argument("--settings", action="store_true",
                   help="Ouvrir le menu configuration")
    p.add_argument("--from-file", default=None,
                   help="Fichier texte contenant une URL par ligne (batch)")
    p.add_argument("--watch", action="store_true",
                   help="Surveiller et télécharger les nouveaux épisodes (mode daemon)")
    p.add_argument("--watch-interval", type=int, default=30,
                   help="Intervalle de surveillance en minutes (défaut: 30)")
    p.add_argument("--max-workers", type=int, default=None,
                   help="Override max_workers (épisodes parallèles)")
    p.add_argument("--max-segment-workers", type=int, default=None,
                   help="Override max_segment_workers (segments .ts parallèles)")
    p.add_argument("--quality", choices=["fhd", "hd", "sd", "auto"], default="auto",
                   help="Qualité préférée pour M3U8 (fhd=1080p, hd=720p, sd=480p, auto=meilleure)")
    p.add_argument("--site", default=None,
                   help="Forcer le site (anime-sama, voiranime)")
    return p


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------
def _resolve_url(args, headers) -> Optional[str]:
    cfg = get_config()
    base_url = args.url

    if args.settings:
        settings_menu()
        return None

    if args.search and not base_url:
        # Use the right site for search
        site = get_site_by_key(args.site or cfg.default_site) or get_all_sites()[0]
        print_status(f"Recherche sur {site.display}...", "info")
        results = site.search(args.search, headers=headers)
        if not results:
            print_status("Aucun résultat", "error")
            return None
        print(f"\n{Colors.BOLD}{Colors.HEADER}🔍 RÉSULTATS{Colors.ENDC}")
        print_separator()
        for i, r in enumerate(results, 1):
            sup = r.get('support') or ''
            color = Colors.OKGREEN if 'Supported' in sup else Colors.WARNING
            print(f"{Colors.OKCYAN}{i}. {r['title']} {color}({sup}){Colors.ENDC}")
        while True:
            raw = prompt(f"Choix (1-{len(results)}) ou 'c' annuler: ")
            if raw.lower() == 'c':
                return None
            if raw.isdigit() and 1 <= int(raw) <= len(results):
                base_url = results[int(raw) - 1]['url']
                break

    if not base_url:
        # Interactive menu
        if confirm("Afficher le tutoriel?", default=False):
            print_tutorial()
            prompt("Entrée pour continuer...")

        while True:
            print(f"\n{Colors.BOLD}{Colors.HEADER}🎬 MENU PRINCIPAL{Colors.ENDC}")
            print_separator()
            print(f"{Colors.OKCYAN}1.{Colors.ENDC} Coller une URL")
            print(f"{Colors.OKCYAN}2.{Colors.ENDC} Rechercher un anime")
            print(f"{Colors.OKCYAN}3.{Colors.ENDC} Configuration")
            print(f"{Colors.OKCYAN}4.{Colors.ENDC} Historique")
            print(f"{Colors.OKCYAN}5.{Colors.ENDC} Diagnostiquer (doctor)")
            print(f"{Colors.OKGREEN}6.{Colors.ENDC} 🤖 Chatbot IA (langage naturel)")
            print(f"{Colors.OKCYAN}0.{Colors.ENDC} Quitter")
            mode = prompt("Choix: ")
            if mode == "1":
                base_url = prompt("URL complète: ")
                if base_url:
                    break
            elif mode == "2":
                # Ask which site
                sites = get_all_sites()
                print(f"\n{Colors.BOLD}Sites:{Colors.ENDC}")
                for i, s in enumerate(sites, 1):
                    print(f"  {i}. {s.display} ({s.domain})")
                schoice = prompt(f"Site (1-{len(sites)}) [{cfg.default_site}]: ")
                if schoice.isdigit() and 1 <= int(schoice) <= len(sites):
                    site = sites[int(schoice) - 1]
                else:
                    site = get_site_by_key(cfg.default_site) or sites[0]
                q = prompt(f"Recherche sur {site.display}: ")
                results = site.search(q, headers=headers)
                if not results:
                    print_status("Aucun résultat", "error")
                    continue
                for i, r in enumerate(results, 1):
                    sup = r.get('support') or ''
                    print(f"{Colors.OKCYAN}{i}. {r['title']} ({sup}){Colors.ENDC}")
                raw = prompt(f"Choix (1-{len(results)}) ou 'c': ")
                if raw.lower() == 'c':
                    continue
                if raw.isdigit() and 1 <= int(raw) <= len(results):
                    base_url = results[int(raw) - 1]['url']
                    # Try expand
                    options = site.expand(base_url, headers=headers)
                    if options:
                        print(f"\n{Colors.BOLD}{Colors.HEADER}📅 SAISONS/VERSIONS{Colors.ENDC}")
                        print_separator()
                        for i, o in enumerate(options, 1):
                            print(f"{Colors.OKCYAN}{i}. {o['name']}{Colors.ENDC}")
                        raw2 = prompt(f"Choix (1-{len(options)}) ou Entrée pour URL directe: ")
                        if raw2.isdigit() and 1 <= int(raw2) <= len(options):
                            base_url = options[int(raw2) - 1]['url']
                    break
            elif mode == "3":
                settings_menu()
            elif mode == "4":
                _history_command([])
            elif mode == "5":
                from src.doctor import run_doctor
                run_doctor()
                prompt("Entrée pour continuer...")
            elif mode == "6":
                from src.chatbot import chat_loop
                chat_loop()
            elif mode == "0":
                return None

    return base_url


# ---------------------------------------------------------------------------
# Download flow for a single URL
# ---------------------------------------------------------------------------
def _process_url(base_url: str, args, headers, interactive: bool) -> int:
    """Process a single URL: detect site, fetch episodes, download."""
    try:
        site = get_site_for_url(base_url)
    except SiteNotFound as e:
        print_status(str(e), "error")
        return 1

    print_status(f"Site détecté: {site.display} ({site.domain})", "info")

    # Validate / expand
    if not site.validate(base_url):
        print_status("Recherche de saisons...", "info")
        options = site.expand(base_url, headers=headers)
        if options:
            print(f"\n{Colors.BOLD}{Colors.HEADER}📅 SAISONS/VERSIONS{Colors.ENDC}")
            print_separator()
            for i, o in enumerate(options, 1):
                print(f"{Colors.OKCYAN}{i}. {o['name']}{Colors.ENDC}")
            raw = prompt(f"Choix (1-{len(options)}): ") if interactive else "1"
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                base_url = options[int(raw) - 1]['url']
            else:
                print_status("Annulé", "warning")
                return 1
        else:
            print_status("URL invalide et aucune saison trouvée", "error")
            return 1

    # Scan download?
    if site.is_scan_url(base_url):
        ok = site.download_scan(base_url, headers=headers, dest=args.dest)
        return 0 if ok else 1

    # Anime download
    anime_name = extract_anime_name(base_url)
    season_slug = extract_season_slug(base_url)
    print_status(f"Anime: {anime_name} | Saison: {season_slug}", "info")

    episodes = site.fetch_episodes(base_url, headers=headers)
    if not episodes:
        print_status("Échec récupération épisodes", "error")
        return 1

    if args.list:
        list_episodes(episodes)
        return 0

    list_episodes(episodes)

    # Player selection
    player_choice = None
    if args.player:
        avail = list(episodes.keys())
        if args.player in avail:
            player_choice = args.player
        else:
            target = args.player.lower()
            for p in avail:
                if target in p.lower():
                    player_choice = p
                    break
            if not player_choice and target.isdigit():
                cand = f"Player {target}"
                if cand in avail:
                    player_choice = cand
            if not player_choice:
                from src.sources import SOURCES_BY_KEY
                if target in SOURCES_BY_KEY:
                    src = SOURCES_BY_KEY[target]
                    for p in avail:
                        if any(src.matches(u) for u in episodes[p][:5]):
                            player_choice = p
                            break
        if not player_choice:
            print_status(f"Player '{args.player}' introuvable", "error")
            return 1
    else:
        player_choice = get_player_choice(episodes) if interactive else list(episodes.keys())[0]
    if not player_choice:
        return 1

    urls = episodes[player_choice]
    total = len(urls)

    # Episode selection
    if args.latest:
        episode_indices = parse_episodes_arg("latest", total, urls)
        if not episode_indices:
            print_status("Aucun épisode valide", "error")
            return 1
        print_status(f"Dernier épisode: {episode_indices[0] + 1}", "info")
    elif args.episodes:
        episode_indices = parse_episodes_arg(args.episodes, total, urls)
    elif interactive:
        episode_indices = get_episode_choice(episodes, player_choice)
    else:
        print_status("Aucun épisode sélectionné (--episodes requis en CLI)", "error")
        return 1

    if not episode_indices:
        print_status("Aucun épisode à télécharger", "warning")
        return 1

    cfg = get_config()
    if args.dest:
        save_dir = format_save_path(cfg.save_template, anime_name, season_slug,
                                    base=args.dest)
    else:
        save_dir = format_save_path(cfg.save_template, anime_name, season_slug)
    os.makedirs(save_dir, exist_ok=True)

    ep_nums = [i + 1 for i in episode_indices]
    ep_urls = [urls[i] for i in episode_indices]
    print(f"\n{Colors.BOLD}{Colors.HEADER}🎬 TÉLÉCHARGEMENT{Colors.ENDC}")
    print_separator()
    print_status(f"Site: {site.display}", "info")
    print_status(f"Player: {player_choice}", "info")
    print_status(f"Épisodes: {', '.join(map(str, ep_nums))}", "info")
    print_status(f"Dossier: {os.path.abspath(save_dir)}", "info")

    if args.dry_run:
        print_status("DRY-RUN — aucun téléchargement effectué", "warning")
        return 0

    # Extract video sources
    print_status("Extraction des sources vidéo...", "loading")
    video_sources = fetch_video_source(ep_urls)
    if not video_sources or all(s is None for s in video_sources):
        print_status("Extraction échouée pour tous les épisodes", "error")
        return 1

    # Options
    use_threading = args.threads
    use_ts_threading = args.fast or (cfg.max_segment_workers > 1 and not args.no_fast)
    automatic_mp4 = args.mp4 or (cfg.auto_mp4 and not args.ts)
    tool = args.tool or cfg.convert_tool
    no_mal = args.no_mal
    max_w = cfg.max_workers
    if args.max_workers:
        max_w = args.max_workers
    if args.max_segment_workers:
        cfg.max_segment_workers = args.max_segment_workers

    if interactive:
        if len(ep_nums) > 1 and not args.threads:
            use_threading = confirm("Télécharger en parallèle?", default=True)
        if any('m3u8' in (s or '') for s in video_sources):
            if not args.fast and not args.no_fast:
                use_ts_threading = confirm(
                    "Segments .ts en parallèle (plus rapide)?", default=True
                )
            if not (args.mp4 or args.ts):
                automatic_mp4 = confirm("Convertir en .mp4 automatiquement?",
                                        default=cfg.auto_mp4)

    # MAL matching
    if not no_mal and anime_name and site.key == "anime-sama":
        try:
            create_match_file(save_dir, anime_name, interactive=interactive)
        except Exception as e:
            print_status(f"MAL skip: {e}", "debug")

    # Download
    failed = 0
    prefer_q = args.quality if args.quality and args.quality != "auto" else None
    try:
        if use_threading and len(ep_nums) > 1:
            print_status(f"Mode parallèle ({max_w} workers)", "info")
            with ThreadPoolExecutor(max_workers=min(max_w, len(ep_nums))) as ex:
                futures = {
                    ex.submit(download_episode, n, u, vs, anime_name, save_dir,
                              use_ts_threading, automatic_mp4, tool, no_mal,
                              interactive, prefer_q): n
                    for n, u, vs in zip(ep_nums, ep_urls, video_sources)
                }
                for future in as_completed(futures):
                    n = futures[future]
                    try:
                        ok, _ = future.result()
                        if not ok:
                            failed += 1
                    except Exception as e:
                        print_status(f"Erreur épisode {n}: {e}", "error")
                        failed += 1
        else:
            for n, u, vs in zip(ep_nums, ep_urls, video_sources):
                ok, _ = download_episode(
                    n, u, vs, anime_name, save_dir,
                    use_ts_threading=use_ts_threading,
                    automatic_mp4=automatic_mp4,
                    tool=tool,
                    no_mal=no_mal,
                    interactive=interactive,
                    prefer_quality=prefer_q,
                )
                if not ok:
                    failed += 1

        print_separator()
        if failed == 0:
            print_status("Tous les téléchargements sont terminés! 🎉", "success")
            _notify("Anime-Sama Downloader", f"✅ {len(ep_nums)} épisode(s) téléchargé(s) — {anime_name}")
            return 0
        else:
            print_status(f"Terminé avec {failed} échec(s)", "warning")
            _notify("Anime-Sama Downloader", f"⚠️ Terminé avec {failed} échec(s) — {anime_name}")
            return 1
    except KeyboardInterrupt:
        print_status("\nInterrompu par l'utilisateur", "warning")
        return 130
    except Exception as e:
        print_status(f"Erreur fatale: {e}", "error")
        return 1


# ---------------------------------------------------------------------------
# Watch mode (daemon)
# ---------------------------------------------------------------------------
def _watch_mode(args, headers) -> int:
    """Poll for new episodes and download them as they appear."""
    if not args.url:
        print_status("--watch nécessite --url", "error")
        return 1

    try:
        site = get_site_for_url(args.url)
    except SiteNotFound as e:
        print_status(str(e), "error")
        return 1

    interval = max(5, args.watch_interval) * 60  # convert minutes to seconds
    print_status(f"Mode surveillance: {site.display} — {args.url}", "info")
    print_status(f"Intervalle: {args.watch_interval} min", "info")
    print_status("Ctrl+C pour arrêter", "info")
    print_separator()

    seen_eps: set = set()
    iteration = 0
    try:
        while True:
            iteration += 1
            print_status(f"[{iteration}] Vérification des nouveaux épisodes...", "loading")
            try:
                episodes = site.fetch_episodes(args.url, headers=headers)
            except Exception as e:
                print_status(f"Erreur fetch: {e}", "warning")
                time.sleep(interval)
                continue

            if not episodes:
                time.sleep(interval)
                continue

            # Use first player
            player = list(episodes.keys())[0]
            urls = episodes[player]
            new_indices = []
            for i, u in enumerate(urls):
                if i not in seen_eps and is_supported(u):
                    new_indices.append(i)

            if not new_indices:
                print_status(f"[{iteration}] Aucun nouvel épisode", "info")
            else:
                print_status(f"[{iteration}] {len(new_indices)} nouveau(s) épisode(s)!", "success")
                # Download them
                anime_name = extract_anime_name(args.url)
                season_slug = extract_season_slug(args.url)
                cfg = get_config()
                save_dir = format_save_path(cfg.save_template, anime_name, season_slug)
                os.makedirs(save_dir, exist_ok=True)

                for idx in new_indices:
                    seen_eps.add(idx)
                    ep_num = idx + 1
                    ep_url = urls[idx]
                    print_status(f"Téléchargement épisode {ep_num}...", "info")
                    try:
                        vs = fetch_video_source(ep_url)
                        if vs:
                            download_episode(
                                ep_num, ep_url, vs, anime_name, save_dir,
                                use_ts_threading=True,
                                automatic_mp4=cfg.auto_mp4,
                                tool=cfg.convert_tool,
                                no_mal=True,
                                interactive=False,
                            )
                    except Exception as e:
                        print_status(f"Erreur épisode {ep_num}: {e}", "error")

            # Also mark already-seen episodes
            for i in range(len(urls)):
                seen_eps.add(i)

            print_status(f"Prochaine vérification dans {args.watch_interval} min", "info")
            time.sleep(interval)
    except KeyboardInterrupt:
        print_status("\nSurveillance arrêtée", "warning")
        return 0


# ---------------------------------------------------------------------------
# Batch from file
# ---------------------------------------------------------------------------
def _batch_from_file(filepath: str, args, headers) -> int:
    """Read URLs from a file (one per line) and process each."""
    if not os.path.exists(filepath):
        print_status(f"Fichier introuvable: {filepath}", "error")
        return 1
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        print_status(f"Erreur lecture fichier: {e}", "error")
        return 1

    if not urls:
        print_status("Fichier vide", "warning")
        return 1

    print_status(f"{len(urls)} URLs à traiter depuis {filepath}", "info")
    print_separator()

    failed_total = 0
    for i, url in enumerate(urls, 1):
        print(f"\n{Colors.BOLD}{Colors.HEADER}━━━ [{i}/{len(urls)}] {url} ━━━{Colors.ENDC}")
        try:
            rc = _process_url(url, args, headers, interactive=False)
            if rc != 0:
                failed_total += 1
                print_status(f"Échec pour {url}", "warning")
        except Exception as e:
            print_status(f"Exception pour {url}: {e}", "error")
            failed_total += 1

    print_separator()
    if failed_total == 0:
        print_status(f"Tous les {len(urls)} URLs traitées avec succès!", "success")
        return 0
    else:
        print_status(f"{failed_total}/{len(urls)} URL(s) en échec", "warning")
        return 1


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------
def _notify(title: str, message: str) -> None:
    """Send a desktop notification (if enabled and available)."""
    cfg = get_config()
    if not cfg.notify_on_complete:
        return
    import shutil
    if shutil.which("notify-send"):
        try:
            import subprocess
            subprocess.run(["notify-send", title, message], timeout=5)
        except Exception:
            pass
    elif is_termux():
        try:
            import subprocess
            subprocess.run(["termux-notification", "-t", title, "--content", message], timeout=5)
        except Exception:
            pass
    # Terminal bell fallback
    sys.stdout.write("\a")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Pre-dispatch subcommands (update, doctor, history, sites, version)
    rc = _dispatch_subcommand(argv)
    if rc is not None:
        return rc

    parser = build_parser()
    args = parser.parse_args(argv)
    interactive = len(argv) == 0

    # Verbosity / colors
    set_verbosity(args.verbose)
    if args.no_color:
        disable_colors()

    # Load config
    cfg = get_config()

    # Network setup
    user_agent = args.user_agent or cfg.user_agent or network.DEFAULT_USER_AGENT
    network.configure(user_agent=user_agent, proxy=args.proxy,
                      rate_limit=cfg.rate_limit_seconds)

    # Non-interactive Cloudflare cookie setup
    if args.cf_clearance:
        cfg.set_cookies(args.cf_clearance, user_agent)

    # Cloudflare check (only for anime-sama site)
    if not args.skip_cloudflare_check:
        try:
            setup_cloudflare()
        except KeyboardInterrupt:
            print_status("Annulé", "warning")
            return 1

    # Determine headers based on the site we'll use
    site_key = args.site or cfg.default_site
    site = get_site_by_key(site_key)
    if site and site.key == "anime-sama":
        headers = get_anime_sama_headers()
    else:
        headers = network.default_headers()
        if site:
            headers.update(site.get_headers())

    # Check ffmpeg
    if not ffmpeg_path():
        if is_termux():
            print_status("FFmpeg absent — installe avec: pkg install ffmpeg", "warning")
        else:
            print_status("FFmpeg absent — installe avec: sudo apt install ffmpeg", "warning")

    print_header()

    # Batch from file?
    if args.from_file:
        return _batch_from_file(args.from_file, args, headers)

    # Watch mode?
    if args.watch:
        return _watch_mode(args, headers)

    # Resolve URL
    base_url = _resolve_url(args, headers)
    if not base_url:
        return 0

    return _process_url(base_url, args, headers, interactive)
