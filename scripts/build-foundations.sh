#!/usr/bin/env bash
# Build immutable candidates without restarting or mounting production services.
set -Eeuo pipefail
umask 077
[[ $# == 2 && $EUID == 0 ]] || { echo 'usage: build-foundations.sh /opt/kairos/runtime/p0/RUN/source COMMIT' >&2; exit 64; }
source_dir=$(realpath -e "$1")
revision=$2
[[ $source_dir == /opt/kairos/runtime/p0/*/source && $revision =~ ^[0-9a-f]{40}$ ]]
[[ -f $source_dir/apps/api/requirements.runtime.lock && -d $source_dir/runtime-wheels ]]
(( $(df -B1 --output=avail /opt/kairos | tail -n 1) > 10737418240 ))
(( $(awk '/MemAvailable:/ {print $2}' /proc/meminfo) > 2200000 ))
base_id=sha256:078a0937a5a89cc374cd43c3848d105587d4ea7c0f82807e7f7352fdff417eee
[[ $(docker image inspect -f '{{.Id}}' "$base_id") == "$base_id" ]]
api_target="kairos-api:foundations-$revision"
parser_target="kairos-parser:foundations-$revision"
for target in "$api_target" "$parser_target"; do
  if docker image inspect "$target" >/dev/null 2>&1; then echo 'refusing to overwrite an immutable candidate tag' >&2; exit 65; fi
done
result="$source_dir/../build-result.txt"
[[ ! -e $result ]]
printf 'source_revision=%s\nbase_image=%s\n' "$revision" "$base_id" > "$result"
docker build --pull=false --memory 1536m --memory-swap 1536m \
  --build-arg "BASE_IMAGE=$base_id" --build-arg "SOURCE_REVISION=$revision" \
  -f "$source_dir/apps/api/Dockerfile.release" --tag "$api_target" "$source_dir" \
  > "$source_dir/../api-build.log" 2>&1
api_id=$(docker image inspect -f '{{.Id}}' "$api_target")
[[ $api_id =~ ^sha256:[0-9a-f]{64}$ ]]
[[ $(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$api_id") == "$revision" ]]
printf 'candidate_image=%s\ncandidate_tag=%s\n' "$api_id" "$api_target" >> "$result"
docker build --pull=false --network none --memory 512m --memory-swap 512m \
  --build-arg "KAIROS_API_BASE_IMAGE=$api_id" -f "$source_dir/services/parser/Dockerfile" \
  --tag "$parser_target" "$source_dir" > "$source_dir/../parser-build.log" 2>&1
parser_id=$(docker image inspect -f '{{.Id}}' "$parser_target")
[[ $parser_id =~ ^sha256:[0-9a-f]{64}$ ]]
[[ $(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$parser_id") == "$revision" ]]
printf 'parser_image=%s\nparser_tag=%s\n' "$parser_id" "$parser_target" >> "$result"
cat "$result"
