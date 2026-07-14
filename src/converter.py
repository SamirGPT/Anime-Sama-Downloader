"""TS → MP4 conversion.

Uses `av` (PyAV, preferred — no external binary needed) with fallback
to `ffmpeg` if av fails or is not installed.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional, Tuple

from src.ui import print_status
from src.utils import ffmpeg_path


def convert_ts_to_mp4(input_path: str, output_path: Optional[str] = None,
                      tool: str = "auto") -> Tuple[bool, Optional[str]]:
    """Convert a .ts file to .mp4.

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

    # If the output exists, prompt — but in non-interactive contexts, overwrite
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError as e:
            print_status(f"Impossible de supprimer l'ancien fichier: {e}", "error")
            return False, None

    tool = (tool or "auto").lower()
    if tool == "av":
        return _convert_with_av(input_path, output_path)
    if tool == "ffmpeg":
        return _convert_with_ffmpeg(input_path, output_path)
    # auto
    ok, out = _convert_with_av(input_path, output_path)
    if ok:
        return True, out
    print_status("av a échoué — fallback vers ffmpeg", "warning")
    return _convert_with_ffmpeg(input_path, output_path)


def _convert_with_av(input_path: str, output_path: str) -> Tuple[bool, Optional[str]]:
    try:
        import av
    except ImportError:
        print_status("PyAV non installé", "debug")
        return False, None
    try:
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
        print_status(f"Conversion av échouée: {e}", "error")
        # Cleanup partial output
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False, None


def _convert_with_ffmpeg(input_path: str, output_path: str) -> Tuple[bool, Optional[str]]:
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        print_status("ffmpeg non installé", "error")
        return False, None
    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-c:v", "copy",
        "-c:a", "copy",
        "-bsf:a", "aac_adtstoasc",   # common fix for TS audio
        output_path,
    ]
    print_status(f"ffmpeg: {os.path.basename(output_path)}", "info")
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,   # 10 min cap
        )
        if result.returncode == 0:
            return True, output_path
        print_status(f"ffmpeg code {result.returncode}", "error")
        # Print last few lines of stderr for debug
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
