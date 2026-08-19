#!/usr/bin/env bash
# ffmpeg/ffprobe CLI for decoding and inspecting video
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
need=0; for p in ffmpeg; do dpkg -s "$p" >/dev/null 2>&1 || need=1; done
if [ "$need" = "1" ]; then
  echo "[pkg ffmpeg] installing: ffmpeg"
  apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
fi
echo "[pkg ffmpeg] OK"
