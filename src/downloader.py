"""Video downloader — single-episode and threaded multi-episode.

v4.2: Added fMP4 (CMAF) support.
  - fMP4 playlists have an init segment (#EXT-X-MAP) that must be
    written ONCE at the start of the output file, followed by all
    the .m4s fragments in order. The output is a valid fragmented MP4.
  - The .ts extension is kept for MPEG-TS playlists; .mp4 is used for
    fMP4 playlists (so the converter knows not to force `-f mpegts`).
  - Resume still works: a separate init manifest tracks whether the
    init segment has been written.
  - Parallel download + .parts dir + cleanup all preserved.
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
from src.converter import convert_ts_to_mp4, convert_fmp4_to_mp4
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
                     interactive: bool = True,
                     prefer_quality: Optional[str] = None) -> Tuple[bool, Optional[str]]:
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
            prefer_quality=prefer_quality,
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
    # The output_path's extension tells us what we have:
    #   .ts  → MPEG-TS segments concatenated (use convert_ts_to_mp4)
    #   .mp4 → fMP4 already assembled (init + m4s fragments) — already a valid MP4
    if output_path and output_path.endswith('.ts'):
        if automatic_mp4:
            print_status("Conversion .ts → .mp4...", "loading")
            ok, final_path = convert_ts_to_mp4(output_path, final_mp4, tool=tool)
            if ok:
                try:
                    os.remove(output_path)
                except OSError:
                    pass
                print_status(f"Épisode {episode_num} → {final_path}", "success")
                _record_history(anime_name, episode_num, final_path)
                return True, final_path
            else:
                print_status(f"Conversion échouée — .ts conservé: {output_path}", "warning")
                return True, output_path
        else:
            print_status(f"Épisode {episode_num} → {output_path} (.ts)", "success")
            return True, output_path
    else:
        # fMP4 already produces a valid .mp4 — but we may want to remux
        # to optimize for streaming/compatibility. Use convert_fmp4_to_mp4
        # which does NOT force `-f mpegts`.
        if automatic_mp4 and output_path and output_path.endswith('.mp4') and output_path != final_mp4:
            # Output is at output_path (e.g. episode_X.fmp4.mp4) — remux to final_mp4
            print_status("Remux fMP4 → .mp4...", "loading")
            ok, final_path = convert_fmp4_to_mp4(output_path, final_mp4, tool=tool)
            if ok:
                try:
                    os.remove(output_path)
                except OSError:
                    pass
                print_status(f"Épisode {episode_num} → {final_path}", "success")
                _record_history(anime_name, episode_num, final_path)
                return True, final_path
            else:
                # The assembled fMP4 is already a valid MP4 — keep it as fallback
                print_status(f"Remux échoué — fichier fMP4 conservé: {output_path}", "warning")
                _record_history(anime_name, episode_num, output_path)
                return True, output_path
        else:
            print_status(f"Épisode {episode_num} → {output_path}", "success")
            _record_history(anime_name, episode_num, output_path)
            return True, output_path


def _record_history(anime_name: str, episode_num, path: str) -> None:
    try:
        from src.history import record_download
        record_download(anime_name, episode_num, path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core download (direct MP4 or M3U8)
# ---------------------------------------------------------------------------
def download_video(video_url: str, save_path: str,
                   use_ts_threading: bool = False,
                   page_url: str = '',
                   automatic_mp4: bool = True,
                   tool: str = "auto",
                   prefer_quality: Optional[str] = None) -> Tuple[bool, Optional[str]]:
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
            prefer_quality=prefer_quality,
        )

    return _download_direct(video_url, save_path, headers=headers)


# ---------------------------------------------------------------------------
# Direct download (MP4) — speed-optimized
# ---------------------------------------------------------------------------
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
# M3U8 download (segment-by-segment, with resume + fMP4 support)
# ---------------------------------------------------------------------------
def _download_m3u8(m3u8_url: str, save_path: str,
                   headers: dict,
                   use_threads: bool,
                   prefer_quality: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    from src.extractors.common import extract_segments, PlaylistInfo

    playlist = extract_segments(m3u8_url, prefer_quality=prefer_quality)
    if not playlist or not playlist.segments:
        return False, None

    init_url = playlist.init_segment
    segments = playlist.segments
    is_fmp4 = playlist.is_fmp4

    os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)

    # Choose output extension based on format
    # - fMP4 → .mp4 (the assembled file is already a valid MP4)
    # - MPEG-TS → .ts (needs conversion to .mp4 afterwards)
    if is_fmp4:
        # Use a distinct intermediate name so we know it's the fMP4-assembled file
        out_path = save_path.replace('.mp4', '.fmp4.mp4')
    else:
        out_path = save_path.replace('.mp4', '.ts')

    # Resume logic via manifest
    manifest_path = out_path + '.manifest'
    init_manifest_path = out_path + '.init_manifest'
    done_segments = _load_manifest(manifest_path)
    init_done = os.path.exists(init_manifest_path) and os.path.getsize(init_manifest_path) > 0

    # For fMP4: also need to check if init segment was downloaded
    if is_fmp4 and init_url:
        # If the assembled file already exists and init was done, we're good
        if (done_segments and len(done_segments) == len(segments) and init_done
                and os.path.exists(out_path) and os.path.getsize(out_path) > 0):
            print_status("Playlist déjà assemblée — skip", "info")
            try:
                os.remove(manifest_path)
                os.remove(init_manifest_path)
            except OSError:
                pass
            return True, out_path

        # Download init segment first (only once)
        if not init_done:
            print_status("Téléchargement du segment d'initialisation fMP4...", "info")
            init_data = _fetch_segment(init_url, headers, -1)
            if init_data is None:
                print_status("Échec téléchargement init segment", "error")
                return False, None
            # Write init to a dedicated file (we'll prepend it during assembly)
            init_file = out_path + '.init'
            try:
                with open(init_file, 'wb') as f:
                    f.write(init_data)
                # Mark init as done
                with open(init_manifest_path, 'w') as f:
                    f.write("1\n")
            except Exception as e:
                print_status(f"Écriture init échouée: {e}", "error")
                return False, None

    # Check if all segments are already done
    if done_segments and len(done_segments) == len(segments):
        print_status("Segments déjà téléchargés — assemblage...", "info")
        partial_dir = out_path + '.parts'
        if os.path.isdir(partial_dir):
            if _assemble_from_parts(partial_dir, segments, out_path, len(segments),
                                    is_fmp4=is_fmp4, init_path=(out_path + '.init') if is_fmp4 else None):
                try:
                    os.remove(manifest_path)
                    if is_fmp4:
                        os.remove(init_manifest_path)
                        # Remove the .init file (now embedded in the output)
                        init_file = out_path + '.init'
                        if os.path.exists(init_file):
                            os.remove(init_file)
                except OSError:
                    pass
                return True, out_path
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            try:
                os.remove(manifest_path)
                if is_fmp4:
                    os.remove(init_manifest_path)
            except OSError:
                pass
            return True, out_path

    cfg = get_config()
    max_workers = cfg.max_segment_workers if use_threads else 1

    fmt_label = "fMP4" if is_fmp4 else "MPEG-TS"
    print_status(
        f"{fmt_label}: {len(segments)} segments — workers={max_workers}",
        "info",
    )

    if max_workers > 1:
        ok = _download_segments_threaded(
            segments, out_path, headers, max_workers,
            done_indices=done_segments,
            manifest_path=manifest_path,
        )
    else:
        ok = _download_segments_sequential(
            segments, out_path, headers,
            done_indices=done_segments,
            manifest_path=manifest_path,
        )

    if not ok:
        return False, None

    try:
        os.remove(manifest_path)
        if is_fmp4:
            os.remove(init_manifest_path)
            init_file = out_path + '.init'
            if os.path.exists(init_file):
                os.remove(init_file)
    except OSError:
        pass

    print_status(f"Assemblé → {out_path}", "success")
    return True, out_path


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


def _download_segments_sequential(segments: List[str], out_path: str,
                                  headers: dict,
                                  done_indices: set,
                                  manifest_path: str) -> bool:
    """Sequential download. For fMP4, the init segment is prepended during
    assembly (NOT here) so we don't write it multiple times on resume.
    """
    partial = out_path + '.partial'
    if os.path.exists(partial) and not done_indices:
        try:
            os.remove(partial)
        except OSError:
            pass

    mode = 'ab' if done_indices else 'wb'
    try:
        with open(partial, mode) as f:
            with tqdm(total=len(segments), initial=len(done_indices),
                      desc=f"📥 {os.path.basename(out_path)}",
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
        os.rename(partial, out_path)
        return True
    except KeyboardInterrupt:
        print_status("\nInterrompu — segments conservés pour reprise", "warning")
        return False
    except Exception as e:
        print_status(f"Erreur: {e}", "error")
        return False


def _download_segments_threaded(segments: List[str], out_path: str,
                                headers: dict, max_workers: int,
                                done_indices: set,
                                manifest_path: str) -> bool:
    """Download segments in parallel using the SHARED session.

    For fMP4, the init segment is downloaded separately in _download_m3u8
    and stored in out_path + '.init'. It is prepended ONLY during the
    final assembly (_assemble_from_parts), NEVER during segment download.
    This guarantees init is written exactly once.
    """
    partial_dir = out_path + '.parts'
    os.makedirs(partial_dir, exist_ok=True)

    # Determine which segments actually need to be downloaded.
    truly_pending = []
    for i in range(len(segments)):
        if i in done_indices:
            part_file = os.path.join(partial_dir, f"{i:08d}.part")
            if os.path.exists(part_file):
                continue
        truly_pending.append(i)

    if not truly_pending:
        return _assemble_from_parts(partial_dir, segments, out_path, len(segments))

    print_status(f"Téléchargement parallèle ({len(truly_pending)} segments, {max_workers} workers)", "info")

    failed = False
    try:
        with tqdm(total=len(segments), initial=len(segments) - len(truly_pending),
                  desc=f"📥 {os.path.basename(out_path)}",
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

    return _assemble_from_parts(partial_dir, segments, out_path, len(segments))


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
                         out_path: str, count: int,
                         is_fmp4: bool = False,
                         init_path: Optional[str] = None) -> bool:
    """Assemble .part files into the final output.

    For fMP4 (is_fmp4=True):
      - If init_path exists, write it FIRST (the initialization segment
        containing the 'moov' / 'moof' header boxes).
      - Then concatenate all .m4s fragments in order.
      - The result is a valid fragmented MP4 (CMAF).

    For MPEG-TS (is_fmp4=False):
      - Just concatenate the segments in order (same as before).
    """
    print_status("Assemblage des segments...", "loading")
    try:
        with open(out_path, 'wb') as out:
            # For fMP4: write the init segment exactly once at the start
            if is_fmp4 and init_path and os.path.exists(init_path):
                with open(init_path, 'rb') as f:
                    out.write(f.read())
                print_debug_init_written()

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
    """Clean up all intermediate files for the given base paths."""
    for p in paths:
        if not p:
            continue
        for suffix in ('', '.partial', '.manifest', '.init_manifest', '.init', '.fmp4.mp4'):
            f = p + suffix
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        # Also clean .fmp4.mp4 variants
        fmp4_path = p.replace('.ts', '.fmp4.mp4')
        if os.path.exists(fmp4_path):
            try:
                os.remove(fmp4_path)
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


# Inline helper to keep _assemble_from_parts readable
def print_debug_init_written() -> None:
    from src.ui import print_debug
    print_debug("Init segment written (fMP4)")
