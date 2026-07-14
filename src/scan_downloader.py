"""Scan (manga chapter) downloader — with retry, skip-existing, save_dir."""
from __future__ import annotations

import os
import re
from typing import Optional, List, Dict
from urllib.parse import quote

from tqdm import tqdm

from src import network
from src.cloudflare import DOMAIN, get_anime_sama_headers
from src.config import get_config
from src.ui import Colors, print_status, print_separator, prompt, confirm
from src.utils import sanitize_filename, extract_anime_name


def download_scan(url: str, headers: Optional[Dict] = None,
                  dest: Optional[str] = None) -> bool:
    """Download scan chapters for the given URL."""
    headers = headers or get_anime_sama_headers()
    cfg = get_config()
    save_base = dest or cfg.scan_dir

    try:
        print_status("Récupération de la page scan...", "info")
        page = network.get_text(url, headers=headers, timeout=15)
    except Exception as e:
        print_status(f"Erreur fetch page scan: {e}", "error")
        return False

    # Extract anime slug from scan path
    m = re.search(r'src=["\'](?:[^"\']*/)?s2/scans/([^/]+)/', page)
    if m:
        anime_slug = m.group(1)
    else:
        m2 = re.search(r'id=["\']titreOeuvre["\'][^>]*>(.*?)<', page, re.DOTALL)
        if m2:
            anime_slug = m2.group(1).strip()
        else:
            anime_slug = extract_anime_name(url)
            if anime_slug and anime_slug[0].islower():
                anime_slug = anime_slug.capitalize()

    encoded = quote(anime_slug)
    api_url = f"https://{DOMAIN}/s2/scans/get_nb_chap_et_img.php?oeuvre={encoded}"

    print_status(f"Chapitres de: {anime_slug}", "info")
    try:
        r = network.get(api_url, headers=headers, timeout=15)
        r.raise_for_status()
        chapters_data = r.json()
    except Exception as e:
        print_status(f"Erreur API chapitres: {e}", "error")
        return False

    if not chapters_data or "error" in chapters_data:
        msg = chapters_data.get("error") if isinstance(chapters_data, dict) else "vide"
        print_status(f"Pas de chapitres ({msg})", "warning")
        return False

    try:
        sorted_chapters = sorted(chapters_data.keys(), key=lambda x: float(x))
    except ValueError:
        sorted_chapters = sorted(chapters_data.keys())

    # Display
    print(f"\n{Colors.BOLD}{Colors.HEADER}📖 CHAPITRES — {anime_slug.upper()}{Colors.ENDC}")
    print_separator()
    cols = 4
    for i in range(0, len(sorted_chapters), cols):
        row = sorted_chapters[i:i + cols]
        parts = []
        for c in row:
            parts.append(f"{Colors.OKCYAN}{c:>8}{Colors.ENDC} ({chapters_data[c]}p)")
        print("  ".join(parts))
    print_separator()
    print(f"{Colors.OKGREEN}Total: {len(sorted_chapters)} chapitres{Colors.ENDC}")

    # User selection
    selected: List[str] = []
    while True:
        raw = prompt("Chapitres (ex: 1, 10-20, all): ").lower()
        if not raw:
            continue
        if raw in ("q", "exit"):
            return False
        try:
            if raw == "all":
                selected = sorted_chapters
            else:
                for part in raw.split(','):
                    part = part.strip()
                    if '-' in part:
                        a, b = part.split('-', 1)
                        a, b = float(a), float(b)
                        for c in sorted_chapters:
                            try:
                                v = float(c)
                                if a <= v <= b and c not in selected:
                                    selected.append(c)
                            except ValueError:
                                pass
                    else:
                        if part in chapters_data:
                            if part not in selected:
                                selected.append(part)
                        else:
                            try:
                                tv = float(part)
                                for c in sorted_chapters:
                                    if float(c) == tv and c not in selected:
                                        selected.append(c)
                                        break
                            except ValueError:
                                print_status(f"Chapitre {part} introuvable", "warning")
            if not selected:
                print_status("Aucun chapitre valide", "error")
                continue
            break
        except Exception as e:
            print_status(f"Erreur parsing: {e}", "error")

    # Sort numerically
    try:
        selected.sort(key=lambda x: float(x))
    except ValueError:
        selected.sort()

    print_status(f"{len(selected)} chapitres sélectionnés", "success")

    # Save dir
    safe_name = sanitize_filename(anime_slug)
    save_dir = os.path.join(save_base, safe_name)
    os.makedirs(save_dir, exist_ok=True)
    print_status(f"Dossier: {os.path.abspath(save_dir)}", "info")

    # Download
    scan_base_url = f"https://{DOMAIN}/s2/scans/{encoded}"
    total = len(selected)

    for idx, chap in enumerate(selected, 1):
        pages = int(chapters_data[chap])
        safe_chap = sanitize_filename(str(chap))
        chap_dir = os.path.join(save_dir, f"Chapter_{safe_chap}")
        os.makedirs(chap_dir, exist_ok=True)

        print(f"\n{Colors.BOLD}Chapitre {chap} ({idx}/{total}) — {pages} pages{Colors.ENDC}")
        success = 0
        with tqdm(range(1, pages + 1), unit="img", leave=False,
                  desc=f"Ch.{chap}") as pbar:
            for p in pbar:
                if _page_already_downloaded(chap_dir, p):
                    success += 1
                    continue
                if _download_page(scan_base_url, chap, p, chap_dir, headers):
                    success += 1

        if success == pages:
            print_status(f"Chapitre {chap}: {success}/{pages}", "success")
        else:
            print_status(f"Chapitre {chap}: {success}/{pages} (partiel)", "warning")

    print_separator()
    print_status("Téléchargement scans terminé!", "success")
    return True


def _page_already_downloaded(chap_dir: str, page: int) -> bool:
    for ext in ('.jpg', '.jpeg', '.png', '.webp'):
        if os.path.exists(os.path.join(chap_dir, f"{page}{ext}")):
            return True
    return False


def _download_page(scan_base_url: str, chap: str, page: int,
                   chap_dir: str, headers: dict) -> bool:
    """Try each extension until one works. Returns True on success."""
    extensions = ('.jpg', '.jpeg', '.png', '.webp')
    for ext in extensions:
        img_url = f"{scan_base_url}/{chap}/{page}{ext}"
        save_path = os.path.join(chap_dir, f"{page}{ext}")
        try:
            r = network.get(img_url, headers=headers, timeout=15, stream=True)
            if r.status_code == 200:
                with open(save_path, 'wb') as f:
                    # 256KB chunks (was 1KB — huge speedup)
                    for chunk in r.iter_content(256 * 1024):
                        f.write(chunk)
                return True
        except Exception:
            continue
    return False
