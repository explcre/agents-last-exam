#!/usr/bin/env bash
# DuckDB CLI, a single static MIT-licensed binary. No server, no root at run time.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
VERSION=v1.1.3
if command -v duckdb >/dev/null 2>&1; then echo "[pkg duckdb-cli] already present"; exit 0; fi
apt-get update && apt-get install -y curl unzip && rm -rf /var/lib/apt/lists/*
tmp=$(mktemp -d)
curl -sSL -o "$tmp/duckdb.zip" \
  "https://github.com/duckdb/duckdb/releases/download/${VERSION}/duckdb_cli-linux-amd64.zip"
unzip -q -o "$tmp/duckdb.zip" -d /usr/local/bin
chmod +x /usr/local/bin/duckdb
rm -rf "$tmp"
echo "[pkg duckdb-cli] OK"
