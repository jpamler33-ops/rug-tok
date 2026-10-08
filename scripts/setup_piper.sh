#!/usr/bin/env bash
# Downloads the offline fallback voice (Piper TTS + German 'thorsten' voice) into vendor/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p vendor/piper vendor/voices
tmp=$(mktemp -d)
curl -fsSL -o "$tmp/piper.tar.gz" https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz
tar xzf "$tmp/piper.tar.gz" -C "$tmp"
cp -r "$tmp/piper/"* vendor/piper/
curl -fsSL -o "$tmp/voice.tar.gz" https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-de-thorsten-low.tar.gz
tar xzf "$tmp/voice.tar.gz" -C "$tmp"
cp "$tmp/de-thorsten-low.onnx" "$tmp/de-thorsten-low.onnx.json" vendor/voices/
rm -rf "$tmp"
echo "Piper ready: vendor/piper/piper + vendor/voices/de-thorsten-low.onnx"
