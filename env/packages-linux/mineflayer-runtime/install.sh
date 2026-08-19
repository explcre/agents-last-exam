#!/usr/bin/env bash
# Node.js 20 plus mineflayer/flying-squid, installed to a fixed global prefix.
# Every package here is MIT and pure JavaScript: nothing compiles, and no
# Minecraft asset or Mojang jar is involved. flying-squid is a JS server.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
PREFIX=/opt/mineflayer
NODE_VERSION=v20.18.1

if ! command -v node >/dev/null 2>&1 || [ "$(node -e 'console.log(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)" -lt 18 ]; then
  echo "[pkg mineflayer-runtime] installing Node ${NODE_VERSION}"
  apt-get update && apt-get install -y curl xz-utils && rm -rf /var/lib/apt/lists/*
  mkdir -p /opt/node
  curl -sSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz" \
    | tar -xJ -C /opt/node --strip-components=1
  ln -sf /opt/node/bin/node /usr/local/bin/node
  ln -sf /opt/node/bin/npm /usr/local/bin/npm
fi

mkdir -p "$PREFIX"
cd "$PREFIX"
[ -f package.json ] || npm init -y >/dev/null
npm install --no-audit --no-fund --loglevel=error \
  mineflayer@4.25.0 flying-squid@1.12.0 minecraft-data@3.113.1 vec3 prismarine-registry

# make the stack importable from anywhere, which is how the task's runner loads it
echo "export NODE_PATH=${PREFIX}/node_modules" > /etc/profile.d/mineflayer.sh
chmod +x /etc/profile.d/mineflayer.sh
printf 'NODE_PATH=%s/node_modules\n' "$PREFIX" >> /etc/environment

echo "[pkg mineflayer-runtime] OK"
