#!/usr/bin/env bash
# Install script for Anime-Sama Downloader v3
# Works on Termux (Android) and Ubuntu/Debian.

set -e

PYTHON="${PYTHON:-python3}"

echo "=== Anime-Sama Downloader v3 — Installation ==="

# Detect environment
if [[ -n "$PREFIX" && "$PREFIX" == *com.termux* ]]; then
    echo "[*] Environment: Termux (Android)"
    IS_TERMUX=1
else
    echo "[*] Environment: Linux (Ubuntu/Debian)"
    IS_TERMUX=0
fi

# Check Python
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "[!] Python 3 is required but not found."
    if [[ "$IS_TERMUX" == "1" ]]; then
        echo "    Install with: pkg install python"
    else
        echo "    Install with: sudo apt install python3 python3-pip"
    fi
    exit 1
fi

echo "[*] Python: $($PYTHON --version)"

# Install ffmpeg (optional but recommended)
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[!] ffmpeg not found. Installing..."
    if [[ "$IS_TERMUX" == "1" ]]; then
        pkg install -y ffmpeg || echo "[!] Failed to install ffmpeg"
    else
        sudo apt update && sudo apt install -y ffmpeg || echo "[!] Failed to install ffmpeg"
    fi
else
    echo "[*] ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
fi

# Install Python dependencies
echo "[*] Installing Python dependencies..."
$PYTHON -m pip install --user -r requirements.txt || {
    echo "[!] pip install failed. Try with --break-system-packages:"
    $PYTHON -m pip install --break-system-packages -r requirements.txt
}

echo ""
echo "=== Installation complete! ==="
echo ""
echo "Quick start:"
echo "  $PYTHON main.py                                   # Interactive mode"
echo "  $PYTHON main.py chat --setup                      # Configure Groq API key (one-time)"
echo "  $PYTHON main.py chat                              # 🤖 Chatbot mode"
echo "  $PYTHON main.py chat \"télécharge naruto épisode 1\" # One-shot chat"
echo "  $PYTHON main.py --search \"naruto\""
echo "  $PYTHON main.py --url <URL> --episodes 1-10 --mp4 --fast"
echo "  $PYTHON main.py --help                            # Full reference"
echo ""
echo "If Cloudflare blocks access, run:"
echo "  $PYTHON main.py --settings    # then option 11"
echo ""
echo "For the chatbot, get a free API key at: https://console.groq.com/keys"
