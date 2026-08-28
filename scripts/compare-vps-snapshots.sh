#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <before-snapshot> <after-snapshot>" >&2
  exit 64
fi

before="$(realpath -- "$1")"
after="$(realpath -- "$2")"
failures=0

require_subset() {
  local name="$1"
  local before_file="$before/$2"
  local after_file="$after/$2"
  local missing
  missing="$(LC_ALL=C comm -23 <(LC_ALL=C sort -u "$before_file") <(LC_ALL=C sort -u "$after_file"))"
  if [[ -n "$missing" ]]; then
    printf 'MODIFIED_%s=1\n%s\n' "$name" "$missing"
    failures=$((failures + 1))
  else
    printf 'MODIFIED_%s=0\n' "$name"
  fi
}

require_exact_without_kairos_additions() {
  local name="$1"
  local file="$2"
  local filtered_after
  filtered_after="$(mktemp)"
  grep -viE '(^|[|_/.-])kairos([|_/.-]|$)' "$after/$file" > "$filtered_after" || true
  if ! diff -u "$before/$file" "$filtered_after"; then
    printf 'MODIFIED_%s=1\n' "$name"
    failures=$((failures + 1))
  else
    printf 'MODIFIED_%s=0\n' "$name"
  fi
  rm -f -- "$filtered_after"
}

require_exact_without_kairos_additions CONTAINERS containers.txt
require_exact_without_kairos_additions CONTAINER_IDENTITIES container-identities.txt
require_exact_without_kairos_additions NETWORKS networks.txt
require_subset VOLUMES volumes.txt
require_subset IMAGES images.txt
require_subset LISTENERS listeners.txt
require_subset SERVICES services-running.txt
require_subset NGINX_CONFIG nginx-config-hashes.txt
require_subset COMPOSE_CONFIG compose-config-hashes.txt
require_subset CRON cron-hashes.txt
require_subset CERTIFICATES public-certificate-hashes.txt
require_subset IPTABLES iptables.txt
require_subset IP6TABLES ip6tables.txt
require_subset NFT nft-ruleset.txt

if (( failures > 0 )); then
  echo "PREEXISTING_RESOURCES_MODIFIED=1"
  exit 1
fi

echo "PREEXISTING_RESOURCES_MODIFIED=0"
