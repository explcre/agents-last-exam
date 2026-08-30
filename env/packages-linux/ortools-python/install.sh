#!/usr/bin/env bash
# Google OR-Tools (Apache-2.0). Pinned: the scheduling task grades exact optimal
# objective values, so the solver version is part of the environment contract even
# though an optimum is solver independent.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
VERSION=9.15.6755
if python3 -c "import ortools" >/dev/null 2>&1; then
  echo "[pkg ortools-python] already present"; exit 0
fi
apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
python3 -m pip install --no-cache-dir "ortools==${VERSION}"
python3 -c "from ortools.sat.python import cp_model; print('ortools ok')"
echo "[pkg ortools-python] OK"
