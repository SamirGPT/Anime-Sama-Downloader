"""Video downloader — single-episode and threaded multi-episode.

v4.0 speed improvements:
- Default max_segment_workers: 8 → 16 (parallel .ts segments)
- Default max_workers: 5 → 8 (parallel episodes)
- Larger chunk size for direct downloads (1MB → 4MB)
- Connection pool reused across segments (HUGE speed gain)
- Skip already-downloaded segments (resume)
- Faster cleanup
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urljoin

from tqdm import tqdm

from src import network
from src.config import get_config
from src.converter import convert_ts_to_mp4
from src.ui import Colors, print_status, print_separator
from src.utils import sanitize_filename


# ---------------------------------------------------------------------------
# Single-episode entry point
# ---------------------------------------------------------------------------
def download_episode(episode_num, url, video_source, anime_name, save_dir,
                     use_ts_threading: bool = False,
                     automatic_mp4: bool = True,
                     tool: str = "auto",
                     no_mal: bool = True,
                     interactive: bool = True) -> Tuple[bool, Optional[str]]:
    if not video_source:
        print_status(f"Pas de source vidéo pour épisode {episode_num}", "error")
        return False, None

    print_separator()
    print_status(f"Traitement épisode {episode_num}", "info")
    print_status(f"Source: {url[:60]}...", "info")

    os.makedirs(save_dir, exist_ok=True)

    base_name = sanitize_filename(anime_name) if anime_name else "episode"
    final_mp4 = os.path.join(save_dir, f"{base_name}_{episode_num}.mp4")
    final_ts = os.path.join(save_dir, f"{base_name}_{episode_num}.ts")

    cfg = get_config()

    # Skip-if-existing logic
    if cfg.skip_existing:
        if os.path.exists(final_mp4) and os.path.getsize(final_mp4) > 0:
            print_status(f"Déjà téléchargé (skip): {final_mp4}", "success")
            return True, final_mp4
        if os.path.exists(final_ts) and os.path.getsize(final_ts) > 0 and not automatic_mp4:
            print_status(f"Déjà téléchargé (skip): {final_ts}", "success")
            return True, final_ts

    print(f"\n{Colors.BOLD}{Colors.HEADER}⬇️  ÉPISODE {episode_num}{Colors.ENDC}")
    print_separator()

    try:
        success, output_path = download_video(
            video_source,
            final_mp4,
            use_ts_threading=use_ts_threading,
            page_url=url,
            automatic_mp4=automatic_mp4,
            tool=tool,
        )
    except KeyboardInterrupt:
        print_status("Interrompu — nettoyage...", "warning")
        _cleanup_partial(final_ts, final_mp4)
        return False, None
    except Exception as e:
        print_status(f"Erreur épisode {episode_num}: {e}", "error")
        return False, None

    if not success:
        print_status(f"Échec épisode {episode_num}", "error")
        return False, None

    # Conversion handling
    if 'm3u8' in video_source and output_path and output_path.endswith('.ts'):
        if automatic_mp4:
            print_status("Conversion .ts → .mp4...", "loading")
            ok, final_path = convert_ts_to_mp4(output_path, final_mp4, tool=tool)
            if ok:
                try:
                    os.remove(output_path)
                except OSError:
                    pass
                print_status(f"Épisode {episode_num} → {final_path}", "success")
                # Record in history
                try:
                    from src.history import record_download
                    record_download(anime_name, episode_num, final_path)
                except Exception:
                    pass
                return True, final_path
            else:
                print_status(f"Conversion échouée — .ts conservé: {output_path}", "warning")
                return True, output_path
        else:
            print_status(f"Épisode {episode_num} → {output_path} (.ts)", "success")
            return True, output_path
    else:
        print_status(f"Épisode {episode_num} → {output_path}", "success")
        try:
            from src.history import record_download
            record_download(anime_name, episode_num, output_path)
        except Exception:
            pass
        return True, output_path


# ---------------------------------------------------------------------------
# Core download (direct MP4 or M3U8)
# ---------------------------------------------------------------------------
def download_video(video_url: str, save_path: str,
                   use_ts_threading: bool = False,
                   page_url: str = '',
                   automatic_mp4: bool = True,
                   tool: str = "auto") -> Tuple[bool, Optional[str]]:
    print_status(f"Démarrage: {os.path.basename(save_path)}", "loading")

    referer = "https://vidmoly.net/"
    origin = ""
    target = page_url or video_url
    if target:
        if not target.startswith(('http://', 'https://')):
            target = 'https://' + target
        parsed = urlparse(target)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        referer = f"{origin}/"

    headers = {
        "Accept": "video/webm,video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": referer,
    }
    if origin:
        headers["Origin"] = origin

    if 'm3u8' in video_url:
        return _download_m3u8(
            video_url, save_path,
            headers=headers,
            use_threads=use_ts_threading,
        )

    return _download_direct(video_url, save_path, headers=headers)


# ---------------------------------------------------------------------------
# Direct download (MP4) — speed-optimized
# ---------------------------------------------------------------------------
# 4MB chunks for maximum throughput on stable connections
_DIRECT_CHUNK_SIZE = 4 * 1024 * 1024


def _download_direct(video_url: str, save_path: str,
                     headers: dict) -> Tuple[bool, Optional[str]]:
    try:
        r = network.get(video_url, headers=headers, timeout=30, stream=True)
    except Exception as e:
        print_status(f"Erreur réseau: {e}", "error")
        return False, None
    if r.status_code != 200:
        print_status(f"HTTP {r.status_code}", "error")
        return False, None

    total = int(r.headers.get('content-length', 0))
    os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)

    partial = save_path + '.partial'
    try:
        with open(partial, 'wb') as f:
            with tqdm(
                total=total or None,
                unit='B', unit_scale=True,
                desc=f"📥 {os.path.basename(save_path)}",
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]',
            ) as pbar:
                for chunk in r.iter_content(chunk_size=_DIRECT_CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
        os.rename(partial, save_path)
        return True, save_path
    except KeyboardInterrupt:
        _cleanup_partial(partial)
        return False, None
    except Exception as e:
        print_status(f"Erreur écriture: {e}", "error")
        _cleanup_partial(partial)
        return False, None


# ---------------------------------------------------------------------------
# M3U8 download (segment-by-segment, with resume)
# ---------------------------------------------------------------------------
def _download_m3u8(m3u8_url: str, save_path: str,
                   headers: dict,
                   use_threads: bool) -> Tuple[bool, Optional[str]]:
    from src.extractors.common import extract_segments

    segments = extract_segments(m3u8_url)
    if not segments:
        return False, None

    os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
    ts_path = save_path.replace('.mp4', '.ts')

    # Resume logic via manifest
    manifest_path = ts_path + '.manifest'
    done_segments = _load_manifest(manifest_path)

    if done_segments and len(done_segments) == len(segments):
        print_status("Segments déjà téléchargés — assemblage...", "info")
        # Check if .parts dir exists (threaded) or .ts already assembled
        partial_dir = ts_path + '.parts'
        if os.path.isdir(partial_dir):
            if _assemble_from_parts(partial_dir, segments, ts_path, len(segments)):
                try:
                    os.remove(manifest_path)
                except OSError:
                    pass
                return True, ts_path
        if os.path.exists(ts_path):
            try:
                os.remove(manifest_path)
            except OSError:
                pass
            return True, ts_path

    cfg = get_config()
    # v4.0: default to threaded mode unless explicitly disabled
    # (use_threads comes from --fast flag or interactive choice)
    max_workers = cfg.max_segment_workers if use_threads else 1

    # Even in "non-threaded" mode, we still benefit from connection pooling
    print_status(f"{len(segments)} segments — workers={max_workers}", "info")

    if max_workers > 1:
        ok = _download_segments_threaded(
            segments, ts_path, headers, max_workers,
            done_indices=done_segments,
            manifest_path=manifest_path,
        )
    else:
        ok = _download_segments_sequential(
            segments, ts_path, headers,
            done_indices=done_segments,
            manifest_path=manifest_path,
        )

    if not ok:
        return False, None

    try:
        os.remove(manifest_path)
    except OSError:
        pass

    print_status(f"Assemblé → {ts_path}", "success")
    return True, ts_path


def _load_manifest(path: str) -> set:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, 'r') as f:
            return set(int(line.strip()) for line in f if line.strip().isdigit())
    except Exception:
        return set()


def _append_manifest(path: str, index: int) -> None:
    try:
        with open(path, 'a') as f:
            f.write(f"{index}\n")
    except Exception:
        pass


def _download_segments_sequential(segments: List[str], ts_path: str,
                                  headers: dict,
                                  done_indices: set,
                                  manifest_path: str) -> bool:
    partial = ts_path + '.partial'
    if os.path.exists(partial) and not done_indices:
        try:
            os.remove(partial)
        except OSError:
            pass

    mode = 'ab' if done_indices else 'wb'
    try:
        with open(partial, mode) as f:
            with tqdm(total=len(segments), initial=len(done_indices),
                      desc=f"📥 {os.path.basename(ts_path)}",
                      unit="seg") as pbar:
                for i, seg_url in enumerate(segments):
                    if i in done_indices:
                        continue
                    data = _fetch_segment(seg_url, headers, i)
                    if data is None:
                        return False
                    f.write(data)
                    f.flush()
                    _append_manifest(manifest_path, i)
                    pbar.update(1)
        os.rename(partial, ts_path)
        return True
    except KeyboardInterrupt:
        print_status("\nInterrompu — segments conservés pour reprise", "warning")
        return False
    except Exception as e:
        print_status(f"Erreur: {e}", "error")
        return False


def _download_segments_threaded(segments: List[str], ts_path: str,
                                headers: dict, max_workers: int,
                                done_indices: set,
                                manifest_path: str) -> bool:
    """Download segments in parallel using the SHARED session.

    v4.0: uses the shared network session (one big connection pool)
    instead of per-thread sessions. This dramatically speeds up
    downloads because connections are reused.
    """
    partial_dir = ts_path + '.parts'
    os.makedirs(partial_dir, exist_ok=True)

    # Determine which segments actually need to be downloaded.
    # A segment is "truly done" only if its .part file exists.
    # If the manifest says done but the .part is missing (e.g. cleaned up
    # after a previous successful assembly), we need to re-download.
    truly_pending = []
    for i in range(len(segments)):
        if i in done_indices:
            part_file = os.path.join(partial_dir, f"{i:08d}.part")
            if os.path.exists(part_file):
                continue  # truly done
        truly_pending.append(i)

    if not truly_pending:
        # All segments already have their .part files
        return _assemble_from_parts(partial_dir, segments, ts_path, len(segments))

    print_status(f"Téléchargement parallèle ({len(truly_pending)} segments, {max_workers} workers)", "info")

    failed = False
    try:
        with tqdm(total=len(segments), initial=len(segments) - len(truly_pending),
                  desc=f"📥 {os.path.basename(ts_path)}",
                  unit="seg") as pbar:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {
                    ex.submit(_fetch_segment_to_file,
                              segments[i], headers, i, partial_dir): i
                    for i in truly_pending
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        ok = future.result()
                        if not ok:
                            print_status(f"Segment {idx+1} échoué", "error")
                            failed = True
                            break
                        _append_manifest(manifest_path, idx)
                        pbar.update(1)
                    except Exception as e:
                        print_status(f"Segment {idx+1} exception: {e}", "error")
                        failed = True
                        break
    except KeyboardInterrupt:
        print_status("\nInterrompu — segments conservés pour reprise", "warning")
        return False

    if failed:
        return False

    return _assemble_from_parts(partial_dir, segments, ts_path, len(segments))


def _fetch_segment(seg_url: str, headers: dict, index: int) -> Optional[bytes]:
    """Fetch a single segment with retry. Uses shared session."""
    for attempt in range(3):
        try:
            r = network.get(seg_url, headers=headers, timeout=20, stream=True)
            if r.status_code != 200:
                if attempt < 2:
                    time.sleep(1.0)
                    continue
                return None
            return r.content
        except Exception:
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
            else:
                return None
    return None


def _fetch_segment_to_file(seg_url: str, headers: dict, index: int,
                           partial_dir: str) -> bool:
    data = _fetch_segment(seg_url, headers, index)
    if data is None:
        return False
    try:
        with open(os.path.join(partial_dir, f"{index:08d}.part"), 'wb') as f:
            f.write(data)
        return True
    except Exception as e:
        print_status(f"Écriture segment {index+1}: {e}", "error")
        return False


def _assemble_from_parts(partial_dir: str, segments: List[str],
                         ts_path: str, count: int) -> bool:
    print_status("Assemblage des segments...", "loading")
    try:
        with open(ts_path, 'wb') as out:
            for i in range(count):
                part = os.path.join(partial_dir, f"{i:08d}.part")
                if not os.path.exists(part):
                    print_status(f"Segment {i+1} manquant", "error")
                    return False
                with open(part, 'rb') as f:
                    out.write(f.read())
        # Cleanup parts
        try:
            for fn in os.listdir(partial_dir):
                os.remove(os.path.join(partial_dir, fn))
            os.rmdir(partial_dir)
        except OSError:
            pass
        return True
    except Exception as e:
        print_status(f"Assemblage échoué: {e}", "error")
        return False


def _cleanup_partial(*paths: str) -> None:
    for p in paths:
        if not p:
            continue
        for suffix in ('', '.partial', '.manifest'):
            f = p + suffix
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        parts_dir = p + '.parts'
        if os.path.isdir(parts_dir):
            try:
                for fn in os.listdir(parts_dir):
                    os.remove(os.path.join(parts_dir, fn))
                os.rmdir(parts_dir)
            except OSError:
                pass
