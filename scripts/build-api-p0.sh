#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $# == 2 && $EUID == 0 ]] || { echo 'usage: build-api-p0.sh /opt/kairos/runtime/p0/RUN/source COMMIT' >&2; exit 1; }
source_dir=$(realpath -e "$1")
revision=$2
[[ $source_dir == /opt/kairos/runtime/p0/*/source && $revision =~ ^[0-9a-f]{40}$ ]]
base_id=$(docker container inspect -f '{{.Image}}' kairos-api-1)
[[ $base_id =~ ^sha256:[0-9a-f]{64}$ ]]
base_tag="kairos-api:p0-base-${base_id#sha256:}"
target="kairos-api:p0-$revision"
if docker image inspect "$base_tag" >/dev/null 2>&1; then
  [[ $(docker image inspect -f '{{.Id}}' "$base_tag") == "$base_id" ]]
else
  docker tag "$base_id" "$base_tag"
fi
[[ ! -e "$source_dir/../build-result.txt" ]]
printf 'source_revision=%s\nbase_image=%s\n' "$revision" "$base_id" > "$source_dir/../build-result.txt"
if docker image inspect "$target" >/dev/null 2>&1; then
  echo 'refusing to overwrite existing candidate tag' >&2
  exit 1
fi
docker build --pull=false --network none --build-arg "BASE_IMAGE=$base_tag" \
  --build-arg "SOURCE_REVISION=$revision" -f "$source_dir/apps/api/Dockerfile.p0" \
  --tag "$target" "$source_dir/apps/api" > "$source_dir/../build.log" 2>&1
candidate=$(docker image inspect -f '{{.Id}}' "$target")
[[ $candidate =~ ^sha256:[0-9a-f]{64}$ ]]
[[ $(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$candidate") == "$revision" ]]
printf 'candidate_image=%s\ncandidate_tag=%s\n' "$candidate" "$target" >> "$source_dir/../build-result.txt"
cat "$source_dir/../build-result.txt"
