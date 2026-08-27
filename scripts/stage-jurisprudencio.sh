#!/usr/bin/env bash
set -Eeuo pipefail

archive="${1:?usage: stage-jurisprudencio.sh ARCHIVE [TARGET]}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
target="${2:-$repo_root/services/jurisprudencio/upstream}"

python3 "$script_dir/stage-jurisprudencio.py" "$archive" "$target"

node_image="node:24.19.0-alpine3.23"
for component in gateway-jurisprudencio mcp-server; do
  docker run --rm --user "$(id -u):$(id -g)" \
    --env npm_config_cache=/tmp/npm-cache \
    --volume "$target/$component:/work" --workdir /work \
    "$node_image" npm install --package-lock-only --ignore-scripts
  docker run --rm --user "$(id -u):$(id -g)" \
    --env npm_config_cache=/tmp/npm-cache \
    --volume "$target/$component:/work" --volume /work/node_modules --workdir /work \
    "$node_image" sh -ec 'npm ci --ignore-scripts && npm audit --audit-level=high'
done

docker run --rm --user "$(id -u):$(id -g)" \
  --env npm_config_cache=/tmp/npm-cache \
  --volume "$target/gateway-jurisprudencio:/work" --volume /work/node_modules --workdir /work \
  "$node_image" sh -ec 'npm ci --ignore-scripts && npm run check && npm run build'
docker run --rm --user "$(id -u):$(id -g)" \
  --env npm_config_cache=/tmp/npm-cache \
  --volume "$target/mcp-server:/work" --volume /work/node_modules --workdir /work \
  "$node_image" sh -ec 'npm ci --ignore-scripts && node --check src/server.mjs'

echo "JURISPRUDENCIO_AUDIT=PASS"
