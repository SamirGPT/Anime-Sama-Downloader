# Anime-Sama Downloader v4.1

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue.svg?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Platform-Termux%20%7C%20Ubuntu%20%7C%20Linux-success.svg?style=for-the-badge" alt="Platform">
  <img src="https://img.shields.io/badge/Multi--sites-anime-- sama.to%20%2B%20voiranime.rip-blueviolet.svg?style=for-the-badge" alt="Multi-sites">
  <img src="https://img.shields.io/badge/Chatbot-Groq%20%2B%20Qwen3-ff69b4.svg?style=for-the-badge" alt="Chatbot">
  <img src="https://img.shields.io/badge/License-GPL_3-green.svg?style=for-the-badge" alt="License">
</p>

Version robuste, **multi-sites**, **rapide** et **chatbot IA** du téléchargeur anime, conçue pour **Termux (Android)** et **Ubuntu/Debian**.

## 🆕 Quoi de neuf dans v4.1 ?

### 🤖 Chatbot IA (Groq + Qwen3)
Tu n'as plus besoin de taper des commandes — **parle au bot en langage naturel** :

```bash
python3 main.py chat
# Puis:
# > "Télécharge l'épisode 5 de naruto sur anime-sama"
# > "Cherche one piece"
# > "Télécharge tout les épisodes de naruto saison 1 en mp4"
# > "Montre mon historique"
# > "Change max_workers à 10"
```

Ou en one-shot :
```bash
python3 main.py chat "télécharge le dernier épisode de demon slayer"
```

**Setup** (une seule fois) :
```bash
python3 main.py chat --setup
# Ou export GROQ_API_KEY='gsk_...'
```
Clé gratuite sur https://console.groq.com/keys — le plan gratuit amplement suffisant.

### 📚 Architecture du chatbot
- **LLM** : Qwen3-32B (via Groq LPU, ultra-rapide)
- **Function-calling** : 12 outils (search, download, list, history, stats, config, doctor, sites, update, version, help)
- **Mémoire** : conversation multi-tour (20 derniers messages)
- **Fallback** : si Qwen3 indispo, fallback automatique sur Llama-3.3-70B et Llama-3.1-8B
- **Sécurité** : la clé API est stockée dans la config, jamais logguée

### 🔄 Mise à jour v4 → v4.1 sans reclone
Le `update` fait un `git pull` qui applique les diffs — **aucun reste de v4** :
- Fichiers modifiés → mis à jour
- Fichiers supprimés → retirés
- Fichiers nouveaux → ajoutés

```bash
cd Anime-Sama-Downloader
python3 main.py update
# ou: git pull
```

---

## 🚀 Vitesse (le gros point fort v4.0)
- **Workers segments : 8 → 16** (parallélisation des .ts)
- **Workers épisodes : 5 → 8** (parallélisation des épisodes)
- **Pool de connexions : 20 → 50** par host (connexion reuse)
- **Chunk download direct : 1 MB → 4 MB** (4× plus gros)
- **Chunk images scans : 1 KB → 256 KB** (256× plus gros — énorme gain sur les scans !)
- **Session HTTP partagée** entre tous les threads
- **Backoff plus court** (0.5s au lieu de 0.8s)

### 🌐 Multi-sites
- **anime-sama.to** (domaine corrigé : c'est `.to` pas `.eu` !)
- **voiranime.rip** (nouveau, complètement séparé)
- Architecture extensible : ajouter un site = créer un fichier dans `src/sites/`

### 🔄 Auto-update
```bash
anime-sama-downloader update
```
Détecte automatiquement l'installation (git clone / pip / zip) et met à jour depuis GitHub.

### 📚 Historique & stats
- Tous les téléchargements sont enregistrés dans `~/.local/share/anime-sama/history.jsonl`
- `anime-sama-downloader history` — voir l'historique
- `anime-sama-downloader history stats` — statistiques
- `anime-sama-downloader history clear` — effacer

### 🏥 Doctor (health check)
```bash
anime-sama-downloader doctor
```
Vérifie : Python, packages, ffmpeg, réseau (anime-sama + voiranime), config, permissions.

### 📦 Batch download
```bash
echo "https://anime-sama.to/catalogue/naruto/saison1/vostfr/" > animes.txt
echo "https://anime-sama.to/catalogue/one-piece/saison1/vostfr/" >> animes.txt
anime-sama-downloader --from-file animes.txt --episodes all --mp4
```

### 👀 Watch mode (daemon)
Surveille un anime et télécharge automatiquement les nouveaux épisodes :
```bash
anime-sama-downloader --url "https://anime-sama.to/catalogue/..." --watch --watch-interval 30
```

### 🔔 Notifications
Active-les dans `--settings` (option 10) :
- Linux : `notify-send`
- Termux : `termux-notification`
- Fallback : terminal bell

### 🛠️ Nouveaux flags
- `--max-workers N` — override max_workers
- `--max-segment-workers N` — override max_segment_workers
- `--no-fast` — désactiver le mode parallèle segments
- `--site anime-sama|voiranime` — forcer le site
- `--watch`, `--watch-interval N` — mode surveillance
- `--from-file FILE` — batch download

---

## 📦 Installation

### Termux (Android)
```bash
pkg install python git ffmpeg
git clone https://github.com/SamirGPT/Anime-Sama-Downloader.git
cd Anime-Sama-Downloader
bash install.sh
```

### Ubuntu / Debian
```bash
sudo apt install python3 python3-pip ffmpeg git
git clone https://github.com/SamirGPT/Anime-Sama-Downloader.git
cd Anime-Sama-Downloader
bash install.sh
```

### Installation globale (pip)
```bash
pip install git+https://github.com/SamirGPT/Anime-Sama-Downloader.git
# Ensuite, depuis n'importe où :
anime-sama-downloader --help
# ou l'alias court :
asd --help
```

---

## 🎬 Utilisation

### Mode interactif
```bash
python3 main.py
```

### Exemples par site

**Anime-Sama :**
```bash
python3 main.py --search "naruto" --site anime-sama
python3 main.py --url "https://anime-sama.to/catalogue/naruto/saison1/vostfr/" --episodes "1-10" --mp4 --fast
```

**VoirAnime :**
```bash
python3 main.py --search "naruto" --site voiranime
python3 main.py --url "https://voiranime.rip/naruto/" --episodes all
```

### Exemples avancés

```bash
# Dernier épisode
python3 main.py --url "..." --latest

# Lister sans télécharger
python3 main.py --url "..." --list

# Batch depuis un fichier
python3 main.py --from-file animes.txt --episodes all --mp4

# Mode surveillance (daemon)
python3 main.py --url "..." --watch --watch-interval 60

# Diagnostiquer l'installation
python3 main.py doctor

# Mettre à jour
python3 main.py update

# Voir l'historique
python3 main.py history
python3 main.py history stats

# Avec proxy
python3 main.py --url "..." --proxy http://localhost:8080

# Mode silencieux (pour scripts)
python3 main.py --url "..." --episodes all --mp4 --verbose quiet --skip-cloudflare-check

# 32 segments parallèles (connexion très stable)
python3 main.py --url "..." --fast --max-segment-workers 32
```

### Sous-commandes
| Commande | Description |
|----------|-------------|
| `update` | Mettre à jour depuis GitHub |
| `doctor` | Diagnostiquer l'environnement |
| `history` | Voir l'historique des téléchargements |
| `history stats` | Statistiques de téléchargement |
| `history clear` | Effacer l'historique |
| `sites` | Lister les sites supportés |
| `version` | Afficher la version |

### Arguments
| Argument | Description |
|----------|-------------|
| `--url URL` | URL directe de la saison/scan |
| `--search Q` | Rechercher un anime |
| `--site S` | Forcer le site (`anime-sama` ou `voiranime`) |
| `--episodes X` | `1,3,5-10` \| `all` \| `latest` |
| `--player P` | Player (Sibnet, SendVid, 1,2,3) |
| `--dest DIR` | Dossier de destination |
| `--threads` | Épisodes en parallèle |
| `--fast` | Segments .ts en parallèle (16 workers) |
| `--no-fast` | Désactiver parallèle segments |
| `--mp4` | Convertir en .mp4 |
| `--ts` | Garder .ts |
| `--tool T` | `auto` \| `av` \| `ffmpeg` |
| `--no-mal` | Désactiver MyAnimeList |
| `--latest` | Dernier épisode |
| `--list` | Lister seulement |
| `--dry-run` | Simuler |
| `--no-color` | Sans couleurs |
| `--proxy URL` | Proxy HTTP(S) |
| `--user-agent UA` | User-Agent personnalisé |
| `--cf-clearance V` | Cookie Cloudflare |
| `--verbose L` | `quiet`/`error`/`warning`/`info`/`debug` |
| `--skip-cloudflare-check` | Passer le check Cloudflare |
| `--settings` | Menu config |
| `--from-file F` | Batch depuis fichier |
| `--watch` | Mode surveillance |
| `--watch-interval N` | Intervalle en minutes |
| `--max-workers N` | Override workers épisodes |
| `--max-segment-workers N` | Override workers segments |

---

## 🌐 Sites supportés

| Site | Domaine | Scans | Notes |
|------|---------|-------|-------|
| **Anime-Sama** | anime-sama.to | ✅ | Catalogue complet + scans |
| **VoirAnime** | voiranime.rip | ❌ | Site WordPress, animes seulement |

Ajouter un nouveau site = créer un fichier dans `src/sites/` implémentant l'interface `Site`.

## 📺 Sources vidéo supportées

| Source | Type | Notes |
|--------|------|-------|
| SendVid | MP4 direct | Recommandé |
| Sibnet | MP4 direct | Fiable |
| Uqload | M3U8 HLS | Réparé en v3 |
| Vidmoly | M3U8 HLS | Retry sur rate-limit |
| OneUpload | M3U8 HLS | |
| Embed4me | M3U8 AES | |
| Movearnpre / Smoothpre / Mivalyo / Dingtezuni | M3U8 packed-JS | Inconsistants |

---

## ⚙️ Configuration

Le fichier de config est à `~/.config/anime-sama/config.json` (XDG).

```json
{
  "save_template": "./videos/{anime}/{season}",
  "scan_dir": "./scans",
  "max_workers": 8,
  "max_segment_workers": 16,
  "convert_tool": "auto",
  "auto_mp4": true,
  "skip_existing": true,
  "default_site": "anime-sama",
  "filename_template": "{anime}_{num}.mp4",
  "notify_on_complete": false
}
```

---

## ☁️ Cloudflare

Si anime-sama.to est derrière Cloudflare (403/503), tu dois fournir un cookie `cf_clearance` :

1. Ouvre https://anime-sama.to/ dans ton navigateur
2. F12 → Application → Cookies → anime-sama.to
3. Copie la valeur de `cf_clearance`
4. F12 → Console → `navigator.userAgent` → copie la valeur
5. Soit via `--settings` (option 11), soit via CLI :
   ```bash
   python3 main.py --cf-clearance "TA_VALEUR" --user-agent "TON_UA" --url "..."
   ```

---

## 🏗️ Architecture

```
src/
├── ui.py              # Couleurs, prints, status, erreurs
├── sources.py         # Catalogue des sources vidéo (dataclass)
├── network.py         # Session HTTP partagée + retry + pool 50 connexions
├── config.py          # Config JSON + XDG (incluant groq_api_key)
├── cloudflare.py      # Détection + cookies Cloudflare (anime-sama.to)
├── utils.py           # Helpers (sanitize, paths, détection Termux)
├── converter.py       # ts → mp4 (av + ffmpeg avec fallback)
├── downloader.py      # Téléchargement épisodes + resume + 16 workers
├── scan_downloader.py # Téléchargement scans/manga
├── mal.py             # Intégration MyAnimeList (Jikan)
├── cli.py             # Argparse + flow principal + sous-commandes (chat, update, ...)
├── updater.py         # Auto-update depuis GitHub
├── doctor.py          # Health check
├── history.py         # Historique JSONL
├── chatbot.py         # 🤖 Chatbot IA (Groq + Qwen3, function-calling)
├── chatbot_tools.py   # 12 outils actionnables par le chatbot
├── extractors/        # Extracteurs par source vidéo
│   ├── common.py      # unpack_js + m3u8 partagés
│   ├── sendvid.py
│   ├── sibnet.py
│   ├── uqload.py      # ← FIX CRITIQUE v3
│   ├── vidmoly.py
│   ├── oneupload.py
│   ├── embed4me.py
│   └── movearnpre.py
├── catalog/           # Catalogue anime-sama
│   ├── search.py
│   └── expand.py
├── fetchers/          # Récupération episodes + video sources
│   ├── episodes.py
│   └── video_source.py
└── sites/             # Multi-sites (v4.0)
    ├── base.py        # Classe abstraite Site
    ├── registry.py    # Auto-détection
    ├── anime_sama.py  # anime-sama.to
    └── voiranime.py   # voiranime.rip
```

---

## 📜 Licence

GPL v3 — voir [LICENSE](LICENSE).

## ⚠️ Disclaimer

Outil éducatif. Respecte les lois sur le copyright et les CGU des sites.
