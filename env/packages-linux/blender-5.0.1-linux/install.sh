#!/usr/bin/env bash
# Blender 5.0.1, the official linux-x64 build. Pinned by checksum: the animation task
# that uses it grades vertex positions to 1e-05, so the build must not drift.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
VERSION=5.0.1
SHA256=8019580ee1b7262e505f4196a00237ccf743c88d205b38d34201510676e60b09
if command -v blender >/dev/null 2>&1 && blender --version | head -1 | grep -q "$VERSION"; then
  echo "[pkg blender-5.0.1-linux] already present"; exit 0
fi
apt-get update && apt-get install -y curl xz-utils libxi6 libxxf86vm1 libxfixes3   libxrender1 libgl1 libsm6 && rm -rf /var/lib/apt/lists/*
tmp=$(mktemp -d)
curl -sSL -o "$tmp/blender.tar.xz" \
  "https://download.blender.org/release/Blender5.0/blender-${VERSION}-linux-x64.tar.xz"
echo "$SHA256  $tmp/blender.tar.xz" | sha256sum -c -
mkdir -p /opt
tar -xf "$tmp/blender.tar.xz" -C /opt
rm -rf "/opt/blender-${VERSION}"
mv "/opt/blender-${VERSION}-linux-x64" "/opt/blender-${VERSION}"
ln -sf "/opt/blender-${VERSION}/blender" /usr/local/bin/blender
rm -rf "$tmp"
blender --version | head -1
echo "[pkg blender-5.0.1-linux] OK"
