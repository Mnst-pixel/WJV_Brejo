#!/usr/bin/env bash
set -Eeuo pipefail

port="${1:-4080}"
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
  echo "invalid unprivileged TCP port: $port" >&2
  exit 64
fi

if ss -H -lnt "sport = :$port" | grep -q .; then
  echo "PORT_FREE=0 PORT=$port"
  exit 1
fi

echo "PORT_FREE=1 PORT=$port"

