"""Tools that the chatbot can call — each maps to a real downloader action.

Every function returns a string that the LLM can read and relay to the user
(or use to formulate a follow-up response). Functions never raise — they
catch errors and return error messages instead, so the LLM always gets
clean feedback.
"""
from __future__ import annotations

import json
import os
from typing import Optional, List, Dict, Any

from src.config import get_config
from src.ui import Colors, print_status, print_separator


# We import heavy modules lazily inside the functions to keep startup fast
# and to avoid import errors when optional dependencies are missing.


def search_anime(query: str, site: str = "anime-sama") -> str:
    """Search for an anime by name. Returns a formatted list of results."""
    try:
        from src.sites import get_site_by_key, get_all_sites
        from src.cloudflare import get_anime_sama_headers
        s = get_site_by_key(site)
        if not s:
            available = ", ".join(s.key for s in get_all_sites())
            return f"Site inconnu: {site}. Sites disponibles: {available}"
        headers = get_anime_sama_headers() if s.key == "anime-sama" else s.get_headers()
        results = s.search(query, headers=headers)
        if not results:
            return f"Aucun résultat pour '{query}' sur {s.display}."
        lines = [f"{len(results)} résultat(s) sur {s.display}:"]
        for i, r in enumerate(results, 1):
            sup = r.get("support") or ""
            lines.append(f"  {i}. {r['title']} ({sup}) — {r['url']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur de recherche: {e}"


def download(url: str, episodes: str = "latest", site: str = "auto",
             mp4: bool = True, fast: bool = True, threads: bool = False,
             player: Optional[str] = None,
             quality: Optional[str] = None) -> str:
    """Download episodes from a URL.
    episodes: 'latest', 'all', '1', '1-10', '1,3,5'
    site: 'auto' (detect from URL), 'anime-sama', 'voiranime'
    quality: 'fhd' (1080p), 'hd' (720p), 'sd' (480p), or None (auto-best)
    """
    try:
        from src.sites import get_site_for_url, get_site_by_key, SiteNotFound
        from src.cloudflare import get_anime_sama_headers
        from src.fetchers import fetch_video_source
        from src.downloader import download_episode
        from src.utils import extract_anime_name, extract_season_slug, format_save_path
        from src.sources import is_supported

        # Determine site
        if site == "auto":
            try:
                s = get_site_for_url(url)
            except SiteNotFound as e:
                return str(e)
        else:
            s = get_site_by_key(site)
            if not s:
                return f"Site inconnu: {site}"

        # Validate / expand
        if not s.validate(url):
            options = s.expand(url, headers=s.get_headers())
            if options:
                # Take the first option (anime preferring)
                url = options[0]["url"]
            else:
                return f"URL invalide et aucune saison trouvée pour {url}"

        # Scan?
        if s.is_scan_url(url):
            ok = s.download_scan(url, headers=s.get_headers())
            return "✅ Scan téléchargé!" if ok else "❌ Échec du téléchargement du scan."

        # Fetch episodes
        headers = get_anime_sama_headers() if s.key == "anime-sama" else s.get_headers()
        episodes_dict = s.fetch_episodes(url, headers=headers)
        if not episodes_dict:
            return "❌ Impossible de récupérer les épisodes."

        # Pick player
        player_name = list(episodes_dict.keys())[0]
        if player and player in episodes_dict:
            player_name = player
        elif player:
            # Fuzzy match
            for p in episodes_dict:
                if player.lower() in p.lower():
                    player_name = p
                    break
        urls_list = episodes_dict[player_name]
        total = len(urls_list)

        # Parse episode selection
        from src.cli import parse_episodes_arg
        ep_indices = parse_episodes_arg(episodes, total, urls_list)
        if not ep_indices:
            return f"Aucun épisode valide (total: {total})."

        # Save dir
        cfg = get_config()
        anime_name = extract_anime_name(url)
        season_slug = extract_season_slug(url)
        save_dir = format_save_path(cfg.save_template, anime_name, season_slug)
        os.makedirs(save_dir, exist_ok=True)

        # Extract video sources
        ep_urls = [urls_list[i] for i in ep_indices]
        ep_nums = [i + 1 for i in ep_indices]
        video_sources = fetch_video_source(ep_urls)
        if not video_sources or all(v is None for v in video_sources):
            return "❌ Extraction des sources vidéo échouée."

        # Download
        failed = 0
        if threads and len(ep_nums) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            max_w = min(cfg.max_workers, len(ep_nums))
            with ThreadPoolExecutor(max_workers=max_w) as ex:
                futures = {
                    ex.submit(download_episode, n, u, vs, anime_name, save_dir,
                              fast, mp4, cfg.convert_tool, True, False, quality): n
                    for n, u, vs in zip(ep_nums, ep_urls, video_sources)
                }
                for future in as_completed(futures):
                    try:
                        ok, _ = future.result()
                        if not ok:
                            failed += 1
                    except Exception:
                        failed += 1
        else:
            for n, u, vs in zip(ep_nums, ep_urls, video_sources):
                ok, _ = download_episode(
                    n, u, vs, anime_name, save_dir,
                    use_ts_threading=fast,
                    automatic_mp4=mp4,
                    tool=cfg.convert_tool,
                    no_mal=True,
                    interactive=False,
                    prefer_quality=quality,
                )
                if not ok:
                    failed += 1

        if failed == 0:
            return f"✅ {len(ep_nums)} épisode(s) téléchargé(s) avec succès dans {save_dir}!"
        else:
            return f"⚠️ Terminé avec {failed} échec(s) sur {len(ep_nums)} épisode(s)."
    except Exception as e:
        return f"❌ Erreur de téléchargement: {e}"


def list_episodes(url: str, site: str = "auto") -> str:
    """List episodes for a given URL without downloading."""
    try:
        from src.sites import get_site_for_url, get_site_by_key, SiteNotFound
        from src.cloudflare import get_anime_sama_headers
        from src.sources import find_source

        if site == "auto":
            try:
                s = get_site_for_url(url)
            except SiteNotFound as e:
                return str(e)
        else:
            s = get_site_by_key(site)
            if not s:
                return f"Site inconnu: {site}"

        headers = get_anime_sama_headers() if s.key == "anime-sama" else s.get_headers()
        episodes = s.fetch_episodes(url, headers=headers)
        if not episodes:
            return "Aucun épisode trouvé."

        lines = []
        for player, urls in episodes.items():
            from src.sources import is_supported as _is
            valid = sum(1 for u in urls if _is(u))
            lines.append(f"\n{player}: {len(urls)} épisodes ({valid} valides)")
            for i, u in enumerate(urls, 1):
                src = find_source(u)
                icon = "✅" if src and src.supported else "❌"
                name = src.display if src else "Inconnu"
                lines.append(f"  {i:2d}. {name} {icon}")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur: {e}"


def show_history(limit: int = 20) -> str:
    """Show recent download history."""
    try:
        from src.history import list_history
        records = list_history(limit=limit)
        if not records:
            return "Historique vide."
        lines = [f"{len(records)} derniers téléchargements:"]
        for r in records:
            ts = r.get("timestamp", "?")[:19]
            anime = r.get("anime", "?")
            ep = r.get("episode", "?")
            site = r.get("site", "?")
            lines.append(f"  {ts} — {anime} EP{ep} ({site})")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur: {e}"


def show_stats() -> str:
    """Show download statistics."""
    try:
        from src.history import stats
        s = stats()
        if s["total"] == 0:
            return "Aucun téléchargement enregistré."
        lines = [f"Total: {s['total']} téléchargements"]
        if s.get("by_anime"):
            lines.append("\nPar anime:")
            for anime, count in sorted(s["by_anime"].items(), key=lambda x: -x[1])[:10]:
                lines.append(f"  {anime}: {count}")
        if s.get("by_site"):
            lines.append("\nPar site:")
            for site, count in s["by_site"].items():
                lines.append(f"  {site}: {count}")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur: {e}"


def show_config() -> str:
    """Show the current configuration."""
    try:
        cfg = get_config()
        lines = ["Configuration actuelle:"]
        for k, v in cfg.__dict__.items():
            if k.startswith("_"):
                continue
            if k in ("cf_clearance", "user_agent") and v:
                v = "***"  # don't leak cookies
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur: {e}"


def update_config(key: str, value: str) -> str:
    """Update a config key. Value is a string, will be coerced to the right type."""
    try:
        cfg = get_config()
        if not hasattr(cfg, key) or key.startswith("_"):
            return f"Clé inconnue: {key}"
        # Coerce type
        current = getattr(cfg, key)
        if isinstance(current, bool):
            v = value.lower() in ("true", "1", "yes", "oui", "on")
        elif isinstance(current, int):
            v = int(value)
        elif isinstance(current, float):
            v = float(value)
        else:
            v = value
        cfg.update(**{key: v})
        return f"✅ {key} mis à jour: {v}"
    except Exception as e:
        return f"Erreur: {e}"


def show_doctor() -> str:
    """Run a quick diagnostic."""
    try:
        import shutil, sys
        from src.utils import ffmpeg_path, is_termux
        lines = ["Diagnostic:"]
        lines.append(f"  Python: {sys.version.split()[0]}")
        lines.append(f"  FFmpeg: {'✅' if ffmpeg_path() else '❌'}")
        lines.append(f"  Platform: {'Termux' if is_termux() else 'Linux'}")
        # Check packages
        missing = []
        for pkg, name in [("requests", "requests"), ("bs4", "beautifulsoup4"),
                          ("tqdm", "tqdm"), ("av", "av"),
                          ("Crypto", "pycryptodome")]:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(name)
        if missing:
            lines.append(f"  Packages manquants: {', '.join(missing)}")
        else:
            lines.append("  Packages: ✅ tous installés")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur: {e}"


def list_sites() -> str:
    """List supported sites."""
    try:
        from src.sites import get_all_sites
        sites = get_all_sites()
        lines = [f"{len(sites)} sites supportés:"]
        for s in sites:
            lines.append(f"  - {s.display} ({s.domain}) [clé: {s.key}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur: {e}"


def self_update() -> str:
    """Update the program to the latest version."""
    try:
        from src.updater import self_update as _update
        ok = _update()
        return "✅ Mise à jour réussie! Relance le programme." if ok else "❌ Échec de la mise à jour."
    except Exception as e:
        return f"Erreur: {e}"


def get_version() -> str:
    """Return the current version."""
    from src import __version__
    return f"Anime-Sama Downloader v{__version__}"


def get_help(topic: Optional[str] = None) -> str:
    """Return help text. topic can be None (general), 'download', 'chat', 'config'."""
    general = """Anime-Sama Downloader — Aide

Tu peux me demander en lang naturel:
  • "Télécharge l'épisode 5 de naruto sur anime-sama"
  • "Cherche one piece"
  • "Liste les épisodes de https://anime-sama.to/catalogue/naruto/saison1/vostfr/"
  • "Télécharge tout les épisodes de naruto saison 1 en mp4"
  • "Montre mon historique"
  • "Quelles sont mes stats?"
  • "Affiche la config"
  • "Change max_workers à 10"
  • "Fais un diagnostic"
  • "Liste les sites supportés"
  • "Mets à jour le programme"
  • "Quelle version?"

Pour le téléchargement, donne-moi soit:
  - Une URL complète (https://anime-sama.to/catalogue/...)
  - Le nom de l'anime à rechercher d'abord
"""
    if topic is None:
        return general
    topic = topic.lower()
    if "download" in topic or "téléchar" in topic:
        return ("Download: indique l'anime ou l'URL, les épisodes (1, 1-10, all, latest), "
                "le format (mp4/ts), et optionnellement le site et le player.")
    if "chat" in topic:
        return ("Chat: tu parlotes avec moi! Pose des questions en lang naturel, "
                "je comprends et j'exécute.")
    if "config" in topic:
        return ("Config: affiche avec 'montre la config', modifie avec 'change X à Y'. "
                "Clés: max_workers, max_segment_workers, auto_mp4, skip_existing, etc.")
    return general


# ---------------------------------------------------------------------------
# Tool registry — used by the chatbot to declare tools to the LLM
# ---------------------------------------------------------------------------
TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_anime",
            "description": "Rechercher un anime par son nom sur un site supporté.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Nom de l'anime à rechercher"},
                    "site": {"type": "string", "description": "Site: 'anime-sama' ou 'voiranime'",
                             "enum": ["anime-sama", "voiranime"], "default": "anime-sama"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download",
            "description": "Télécharger des épisodes d'anime. 'episodes' peut être 'latest', 'all', '1', '1-10', '1,3,5'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL de la saison ou de l'anime"},
                    "episodes": {"type": "string",
                                 "description": "Sélection: 'latest', 'all', '1', '1-10', '1,3,5'",
                                 "default": "latest"},
                    "site": {"type": "string", "default": "auto",
                             "description": "'auto' (détecte depuis URL), 'anime-sama', 'voiranime'"},
                    "mp4": {"type": "boolean", "default": True, "description": "Convertir en mp4"},
                    "fast": {"type": "boolean", "default": True, "description": "Segments parallèles"},
                    "threads": {"type": "boolean", "default": False,
                                "description": "Épisodes parallèles"},
                    "player": {"type": "string", "description": "Player spécifique (Sibnet, etc.)"},
                    "quality": {"type": "string",
                                "description": "Qualité: 'fhd' (1080p), 'hd' (720p), 'sd' (480p), ou null (auto)",
                                "enum": ["fhd", "hd", "sd"]},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_episodes",
            "description": "Lister les épisodes d'un anime sans télécharger.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL de la saison"},
                    "site": {"type": "string", "default": "auto"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_history",
            "description": "Afficher l'historique des téléchargements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_stats",
            "description": "Afficher les statistiques de téléchargement.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_config",
            "description": "Afficher la configuration actuelle.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_config",
            "description": "Modifier une clé de configuration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Nom de la clé (ex: max_workers)"},
                    "value": {"type": "string", "description": "Nouvelle valeur"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_doctor",
            "description": "Lancer un diagnostic rapide de l'environnement.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sites",
            "description": "Lister les sites supportés.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "self_update",
            "description": "Mettre à jour le programme depuis GitHub.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_version",
            "description": "Obtenir la version actuelle du programme.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_help",
            "description": "Obtenir de l'aide sur l'utilisation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Sujet: download, chat, config"},
                },
            },
        },
    },
]


# Dispatch table
TOOL_FUNCTIONS = {
    "search_anime": search_anime,
    "download": download,
    "list_episodes": list_episodes,
    "show_history": show_history,
    "show_stats": show_stats,
    "show_config": show_config,
    "update_config": update_config,
    "show_doctor": show_doctor,
    "list_sites": list_sites,
    "self_update": self_update,
    "get_version": get_version,
    "get_help": get_help,
}


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool by name with the given arguments. Returns the result string."""
    fn = TOOL_FUNCTIONS.get(name)
    if not fn:
        return f"Outil inconnu: {name}"
    try:
        return fn(**arguments) if arguments else fn()
    except TypeError as e:
        return f"Arguments invalides pour {name}: {e}"
    except Exception as e:
        return f"Erreur dans {name}: {e}"
