"""TS → MP4 and fMP4 → MP4 conversion.

v4.2: Two separate functions:
  - convert_ts_to_mp4: for MPEG-TS input (uses `-bsf:a aac_adtstoasc`)
  - convert_fmp4_to_mp4: for fragmented MP4 input (NO `-bsf:a`, NO `-f mpegts`)

The fMP4-assembled file is already a valid MP4 (init segment + moof/mdat
fragments), so we just remux with `-c copy` to ensure the moov atom is at
the start for fast-start / streaming.

Uses `av` (PyAV) with fallback to `ffmpeg` if av fails or is not installed.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional, Tuple

from src.ui import print_status
from src.utils import ffmpeg_path


def convert_ts_to_mp4(input_path: str, output_path: Optional[str] = None,
                      tool: str = "auto") -> Tuple[bool, Optional[str]]:
    """Convert a .ts (MPEG-TS) file to .mp4.

    Args:
        input_path: path to the .ts file.
        output_path: target .mp4 path. If None, derived from input_path.
        tool: 'auto' (try av, then ffmpeg) | 'av' | 'ffmpeg'.

    Returns:
        (success, output_path_or_none)
    """
    if not os.path.exists(input_path):
        print_status(f"Fichier introuvable: {input_path}", "error")
        return False, None

    if output_path is None:
        output_path = os.path.splitext(input_path)[0] + '.mp4'

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError as e:
            print_status(f"Impossible de supprimer l'ancien fichier: {e}", "error")
            return False, None

    tool = (tool or "auto").lower()
    if tool == "av":
        return _convert_ts_with_av(input_path, output_path)
    if tool == "ffmpeg":
        return _convert_ts_with_ffmpeg(input_path, output_path)
    # auto
    ok, out = _convert_ts_with_av(input_path, output_path)
    if ok:
        return True, out
    print_status("av a échoué — fallback vers ffmpeg", "warning")
    return _convert_ts_with_ffmpeg(input_path, output_path)


def convert_fmp4_to_mp4(input_path: str, output_path: Optional[str] = None,
                        tool: str = "auto") -> Tuple[bool, Optional[str]]:
    """Remux a fragmented MP4 (CMAF) file to a standard MP4.

    The input is a concatenation of: init segment + .m4s fragments.
    This is already a valid fragmented MP4, but we remux to:
      - Place the moov atom at the start (fast-start for streaming)
      - Ensure max compatibility with players (VLC, mobile, browsers)

    IMPORTANT: We do NOT use `-f mpegts` or `-bsf:a aac_adtstoasc` here.
    Those are for MPEG-TS only — applying them to fMP4 produces:
      "could not find corresponding trex"
      "trun track id unknown"
      "Invalid data found when processing input"
    """
    if not os.path.exists(input_path):
        print_status(f"Fichier introuvable: {input_path}", "error")
        return False, None

    if output_path is None:
        output_path = os.path.splitext(input_path)[0] + '.mp4'

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError as e:
            print_status(f"Impossible de supprimer l'ancien fichier: {e}", "error")
            return False, None

    tool = (tool or "auto").lower()
    if tool == "av":
        ok, out = _convert_fmp4_with_av(input_path, output_path)
        if ok:
            return True, out
        print_status("av a échoué — fallback vers ffmpeg", "warning")
        return _convert_fmp4_with_ffmpeg(input_path, output_path)
    if tool == "ffmpeg":
        return _convert_fmp4_with_ffmpeg(input_path, output_path)
    # auto: prefer ffmpeg for fMP4 (more reliable for CMAF), then av
    ok, out = _convert_fmp4_with_ffmpeg(input_path, output_path)
    if ok:
        return True, out
    print_status("ffmpeg a échoué — fallback vers av", "warning")
    return _convert_fmp4_with_av(input_path, output_path)


# ---------------------------------------------------------------------------
# MPEG-TS conversions
# ---------------------------------------------------------------------------
def _convert_ts_with_av(input_path: str, output_path: str) -> Tuple[bool, Optional[str]]:
    try:
        import av
    except ImportError:
        print_status("PyAV non installé", "debug")
        return False, None
    try:
        # Explicit format="mpegts" so av doesn't try to guess
        in_container = av.open(input_path, mode="r", format="mpegts")
        out_container = av.open(output_path, mode="w")
        streams = {}
        for in_stream in in_container.streams:
            if not hasattr(in_stream, "codec_context") or in_stream.type == "data":
                continue
            try:
                out_stream = out_container.add_stream(in_stream.codec_context.name)
                streams[in_stream.index] = out_stream
            except Exception as e:
                print_status(f"Stream skip: {e}", "debug")
                continue
        for packet in in_container.demux():
            if packet.stream.index not in streams:
                continue
            packet.stream = streams[packet.stream.index]
            try:
                out_container.mux(packet)
            except Exception:
                continue
        out_container.close()
        in_container.close()
        return True, output_path
    except Exception as e:
        print_status(f"Conversion av (TS) échouée: {e}", "error")
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False, None


def _convert_ts_with_ffmpeg(input_path: str, output_path: str) -> Tuple[bool, Optional[str]]:
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        print_status("ffmpeg non installé", "error")
        return False, None
    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-c:v", "copy",
        "-c:a", "copy",
        "-bsf:a", "aac_adtstoasc",   # required for ADTS→ASC in MP4
        output_path,
    ]
    print_status(f"ffmpeg (TS): {os.path.basename(output_path)}", "info")
    return _run_ffmpeg(cmd, output_path)


# ---------------------------------------------------------------------------
# fMP4 conversions — NO mpegts format, NO aac_adtstoasc bitstream filter
# ---------------------------------------------------------------------------
def _convert_fmp4_with_av(input_path: str, output_path: str) -> Tuple[bool, Optional[str]]:
    """Remux fragmented MP4 with PyAV.

    PyAV should be able to read a CMAF file (init + m4s) without specifying
    a format — it detects the ISO BMFF (mp4) container from the ftyp/moov
    boxes in the init segment.
    """
    try:
        import av
    except ImportError:
        print_status("PyAV non installé", "debug")
        return False, None
    try:
        # Do NOT pass format="mpegts" — let av auto-detect (will pick mp4)
        in_container = av.open(input_path, mode="r")
        out_container = av.open(output_path, mode="w")
        streams = {}
        for in_stream in in_container.streams:
            if not hasattr(in_stream, "codec_context") or in_stream.type == "data":
                continue
            try:
                out_stream = out_container.add_stream(in_stream.codec_context.name)
                streams[in_stream.index] = out_stream
            except Exception as e:
                print_status(f"Stream skip: {e}", "debug")
                continue
        for packet in in_container.demux():
            if packet.stream.index not in streams:
                continue
            packet.stream = streams[packet.stream.index]
            try:
                out_container.mux(packet)
            except Exception:
                continue
        out_container.close()
        in_container.close()
        return True, output_path
    except Exception as e:
        print_status(f"Conversion av (fMP4) échouée: {e}", "error")
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False, None


def _convert_fmp4_with_ffmpeg(input_path: str, output_path: str) -> Tuple[bool, Optional[str]]:
    """Remux fragmented MP4 with ffmpeg.

    Critical: NO `-f mpegts` input flag, NO `-bsf:a aac_adtstoasc`.
    Just `-c copy` with movflags for fast-start.
    """
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        print_status("ffmpeg non installé", "error")
        return False, None
    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-c:v", "copy",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    print_status(f"ffmpeg (fMP4): {os.path.basename(output_path)}", "info")
    return _run_ffmpeg(cmd, output_path)


# ---------------------------------------------------------------------------
# Common ffmpeg runner
# ---------------------------------------------------------------------------
def _run_ffmpeg(cmd: list, output_path: str) -> Tuple[bool, Optional[str]]:
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            return True, output_path
        print_status(f"ffmpeg code {result.returncode}", "error")
        if result.stdout:
            tail = "\n".join(result.stdout.splitlines()[-5:])
            print_status(tail, "debug")
        return False, None
    except subprocess.TimeoutExpired:
        print_status("ffmpeg a dépassé le timeout (10min)", "error")
        return False, None
    except FileNotFoundError:
        print_status("ffmpeg introuvable dans le PATH", "error")
        return False, None
