#!/usr/bin/env bash
set -Eeuo pipefail

root=/srv/kairos
[[ "$(realpath -m -- "$root")" == /srv/kairos ]]
install -d -o root -g root -m 0755 "$root"
install -d -o 999 -g 999 -m 0700 "$root/postgres" "$root/mariadb"
install -d -o 999 -g 999 -m 0750 "$root/redis"
install -d -o 1000 -g 1000 -m 0750 "$root/minio" "$root/caddy-data" "$root/caddy-config"
install -d -o 33 -g 33 -m 0750 "$root/wordpress"
install -d -o 100 -g 101 -m 0750 "$root/clamav"
install -d -o root -g root -m 0750 "$root/models" "$root/localai-backends" "$root/localai-data"
install -d -o 10000 -g 10000 -m 0700 "$root/hermes"
install -d -o 10001 -g 10001 -m 0750 "$root/mcp-brasil-cache"
install -d -o root -g root -m 0700 "$root/backups"
install -d -o root -g root -m 0750 "$root/observability"
echo "KAIROS_STORAGE_PROVISION=PASS"
