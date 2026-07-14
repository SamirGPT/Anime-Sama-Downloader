"""Configuration management — JSON file + environment variables.

Replaces the old scattered `config.json`/`get_setting`/`set_setting`
trio with a single, well-typed Config object.

File location priority:
  1. `$ANIME_SAMA_CONFIG` env var (absolute path)
  2. `~/.config/anime-sama/config.json` (XDG-style)
  3. `./config.json` (legacy, project-local)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path

from src.ui import ConfigError


DEFAULT_CONFIG = {
    "cf_clearance": "",
    "user_agent": "",
    "save_template": "./videos/{anime}/{season}",
    "scan_dir": "./scans",
    "max_workers": 8,              # concurrent episode downloads (was 5)
    "max_segment_workers": 16,     # concurrent .ts segment downloads (was 8)
    "convert_tool": "auto",        # auto | av | ffmpeg
    "auto_mp4": True,
    "skip_existing": True,
    "rate_limit_seconds": 0.0,     # delay between episode fetches
    "default_site": "anime-sama",  # default site key
    "filename_template": "{anime}_{num}.mp4",
    "notify_on_complete": False,
    "groq_api_key": "",            # for chatbot (v4.1)
}


def _config_path() -> Path:
    env = os.environ.get("ANIME_SAMA_CONFIG")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        p = Path(xdg) / "anime-sama" / "config.json"
        if p.parent.exists() or True:
            return p
    home = Path.home()
    p = home / ".config" / "anime-sama" / "config.json"
    return p


@dataclass
class Config:
    cf_clearance: str = ""
    user_agent: str = ""
    save_template: str = DEFAULT_CONFIG["save_template"]
    scan_dir: str = DEFAULT_CONFIG["scan_dir"]
    max_workers: int = DEFAULT_CONFIG["max_workers"]
    max_segment_workers: int = DEFAULT_CONFIG["max_segment_workers"]
    convert_tool: str = DEFAULT_CONFIG["convert_tool"]
    auto_mp4: bool = DEFAULT_CONFIG["auto_mp4"]
    skip_existing: bool = DEFAULT_CONFIG["skip_existing"]
    rate_limit_seconds: float = DEFAULT_CONFIG["rate_limit_seconds"]
    default_site: str = DEFAULT_CONFIG["default_site"]
    filename_template: str = DEFAULT_CONFIG["filename_template"]
    notify_on_complete: bool = DEFAULT_CONFIG["notify_on_complete"]
    groq_api_key: str = DEFAULT_CONFIG["groq_api_key"]

    # In-memory only (not persisted)
    _path: Optional[str] = field(default=None, repr=False)

    # ----- persistence -----
    def save(self) -> None:
        if not self._path:
            return
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in asdict(self).items() if k != "_path"}
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        p = Path(path) if path else _config_path()
        cfg = cls()
        cfg._path = str(p)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    if hasattr(cfg, k):
                        setattr(cfg, k, v)
            except (json.JSONDecodeError, OSError) as e:
                raise ConfigError(f"Could not read config {p}: {e}")
        else:
            # First run — create with defaults
            try:
                cfg.save()
            except OSError:
                pass  # read-only filesystem; ignore
        return cfg

    # ----- helpers -----
    def set_cookies(self, cf_clearance: str, user_agent: str) -> None:
        self.cf_clearance = cf_clearance
        self.user_agent = user_agent
        self.save()

    def has_cookies(self) -> bool:
        return bool(self.cf_clearance and self.user_agent)

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)
        self.save()


# Module-level singleton
_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def set_config(cfg: Config) -> None:
    global _config
    _config = cfg


# ---------------------------------------------------------------------------
# Cloudflare cookie validation
# ---------------------------------------------------------------------------
def check_cloudflare_cookies(domain: str = "anime-sama.eu") -> bool:
    """Verify that the stored cf_clearance cookie still works."""
    cfg = get_config()
    if not cfg.has_cookies():
        return False
    try:
        from src.network import get
        r = get(
            f"https://{domain}/",
            headers={"Cookie": f"cf_clearance={cfg.cf_clearance}"},
            timeout=10,
            allow_redirects=True,
        )
        # Cloudflare returns 403 with cf-mitigated or 503 with challenge page
        if r.status_code == 403 or r.status_code == 503:
            return False
        return True
    except Exception:
        return False
