"""Self-update module — `anime-sama-downloader update` command.

Detects how the tool was installed and updates accordingly:
1. If installed via pip/pipx → `pip install --upgrade` from GitHub
2. If running from a git clone → `git pull`
3. Otherwise → fallback: download latest release zip
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.ui import Colors, print_status, print_separator


GITHUB_REPO = "SamirGPT/Anime-Sama-Downloader"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
GITHUB_ZIP = f"https://github.com/{GITHUB_URL}/archive/refs/heads/main.zip"


def _is_git_clone() -> bool:
    """Check if we're running from a git clone (has .git dir nearby)."""
    here = Path(__file__).resolve().parent
    # Walk up to find .git
    for p in [here] + list(here.parents):
        if (p / ".git").is_dir():
            return True
    return False


def _is_pip_installed() -> bool:
    """Check if installed via pip (in site-packages)."""
    here = Path(__file__).resolve().parent
    return "site-packages" in str(here)


def _git_pull() -> bool:
    """Run git pull in the clone directory."""
    here = Path(__file__).resolve().parent
    # Find the .git directory
    git_dir = None
    for p in [here] + list(here.parents):
        if (p / ".git").is_dir():
            git_dir = p
            break
    if not git_dir:
        return False

    print_status(f"Git pull dans {git_dir}...", "info")
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(git_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print_status("Git pull réussi!", "success")
            if result.stdout:
                print(result.stdout.strip())
            return True
        else:
            print_status(f"git pull échec (code {result.returncode})", "error")
            if result.stderr:
                print(result.stderr.strip())
            return False
    except FileNotFoundError:
        print_status("git n'est pas installé", "error")
        return False
    except subprocess.TimeoutExpired:
        print_status("git pull timeout", "error")
        return False


def _pip_upgrade() -> bool:
    """Upgrade via pip from GitHub."""
    print_status("Mise à jour via pip...", "info")
    try:
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--upgrade", f"git+{GITHUB_URL}.git",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print_status("Mise à jour pip réussie!", "success")
            return True
        else:
            # Try with --user or --break-system-packages
            print_status("Retry avec --break-system-packages...", "warning")
            cmd2 = cmd + ["--break-system-packages"]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
            if result2.returncode == 0:
                print_status("Mise à jour réussie!", "success")
                return True
            print_status(f"pip échec: {result2.stderr.strip()}", "error")
            return False
    except Exception as e:
        print_status(f"Erreur pip: {e}", "error")
        return False


def _download_zip() -> bool:
    """Fallback: download the latest zip from GitHub."""
    import tempfile, zipfile
    from src import network

    print_status("Téléchargement de la dernière version...", "info")
    try:
        r = network.get(GITHUB_ZIP, timeout=60, stream=True)
        if r.status_code != 200:
            print_status(f"HTTP {r.status_code}", "error")
            return False
        zip_path = tempfile.mktemp(suffix=".zip")
        with open(zip_path, 'wb') as f:
            for chunk in r.iter_content(1024 * 1024):
                f.write(chunk)
        # Extract
        target_dir = Path.cwd() / "Anime-Sama-Downloader-latest"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target_dir)
        os.remove(zip_path)
        print_status(f"Nouvelle version téléchargée dans: {target_dir}", "success")
        return True
    except Exception as e:
        print_status(f"Erreur téléchargement: {e}", "error")
        return False


def self_update() -> bool:
    """Update the tool to the latest version from GitHub.

    Returns True if an update was performed (or attempted), False on failure.
    """
    from src import __version__
    print_separator()
    print(f"{Colors.BOLD}{Colors.HEADER}🔄 MISE À JOUR — Anime-Sama Downloader v{__version__}{Colors.ENDC}")
    print_separator()

    # Get latest version from GitHub
    try:
        from src import network
        r = network.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            latest = data.get("tag_name", "").lstrip("v")
            print_status(f"Version actuelle: v{__version__}", "info")
            print_status(f"Dernière version: v{latest or 'inconnue'}", "info")
    except Exception:
        pass

    # Detect installation method
    if _is_git_clone():
        print_status("Mode: git clone détecté", "info")
        ok = _git_pull()
    elif _is_pip_installed():
        print_status("Mode: pip install détecté", "info")
        ok = _pip_upgrade()
    else:
        print_status("Mode: téléchargement zip (fallback)", "info")
        ok = _download_zip()

    if ok:
        print_separator()
        print_status("Mise à jour terminée! Relance le programme.", "success")
    else:
        print_separator()
        print_status("Mise à jour échouée — voir erreurs ci-dessus", "error")
    return ok
