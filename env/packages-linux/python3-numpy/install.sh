#!/usr/bin/env bash
# NumPy for Python 3, for array work on decoded video frames
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
need=0; for p in python3-numpy; do dpkg -s "$p" >/dev/null 2>&1 || need=1; done
if [ "$need" = "1" ]; then
  echo "[pkg python3-numpy] installing: python3-numpy"
  apt-get update && apt-get install -y python3-numpy && rm -rf /var/lib/apt/lists/*
fi
echo "[pkg python3-numpy] OK"
