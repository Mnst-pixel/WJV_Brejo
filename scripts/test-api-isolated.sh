#!/usr/bin/env bash
# Synthetic-data integration tests against existing runtime images, no pulls.
set -Eeuo pipefail
umask 077
[[ $# == 2 && $EUID == 0 ]] || { echo 'usage: test-api-isolated.sh /opt/kairos/runtime/p0/RUN/source/apps/api /opt/kairos/runtime/p0/RUN/wheels' >&2; exit 1; }
source_dir=$(realpath -e "$1")
wheels_dir=$(realpath -e "$2")
[[ $source_dir == /opt/kairos/runtime/p0/*/source/apps/api && $wheels_dir == /opt/kairos/runtime/p0/*/wheels ]]
[[ -f $source_dir/kairos/integration_test_settings.py ]]
(( $(awk '/MemAvailable:/ {print $2}' /proc/meminfo) > 2200000 ))
export COMPOSE_PROJECT_NAME=kairos
runid="$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 6)"
prefix="kairos-test-$runid"
work="/opt/kairos/runtime/tests/$prefix"
[[ ! -e $work ]]
mkdir -p -m 0700 "$work"
label=com.kairos.test.run
containers=()
net=''
cleanup() {
  local status=$? name actual failed=0
  trap - EXIT INT TERM
  set +e
  for name in "${containers[@]}"; do
    actual=$(docker container inspect -f "{{index .Config.Labels \"$label\"}}" "$name" 2>/dev/null)
    if [[ $actual == "$runid" ]]; then docker rm -fv "$name" >/dev/null 2>&1 || failed=1; else failed=1; fi
  done
  if [[ -n $net ]]; then
    actual=$(docker network inspect -f "{{index .Labels \"$label\"}}" "$net" 2>/dev/null)
    if [[ $actual == "$runid" ]]; then docker network rm "$net" >/dev/null 2>&1 || failed=1; else failed=1; fi
  fi
  rm -f -- "$work/test.env"
  printf 'test_exit=%s\ncleanup_failed=%s\n' "$status" "$failed" >> "$work/result.txt"
  if (( status == 0 && failed == 0 )); then echo "KAIROS_INTEGRATION=PASS evidence=$work"; else echo "KAIROS_INTEGRATION=FAIL evidence=$work"; status=1; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
api_image=$(docker container inspect -f '{{.Image}}' kairos-api-1)
pg_image=$(docker container inspect -f '{{.Image}}' kairos-postgres-1)
redis_image=$(docker container inspect -f '{{.Image}}' kairos-redis-1)
for id in "$api_image" "$pg_image" "$redis_image"; do [[ $id =~ ^sha256:[0-9a-f]{64}$ ]]; done
printf 'api=%s\npostgres=%s\nredis=%s\n' "$api_image" "$pg_image" "$redis_image" > "$work/images.txt"
pw=$(openssl rand -hex 32)
cat > "$work/test.env" <<EOF
POSTGRES_USER=kairos_test
POSTGRES_DB=kairos_test
POSTGRES_PASSWORD=$pw
KAIROS_TEST_POSTGRES_PASSWORD=$pw
KAIROS_TEST_REDIS_PASSWORD=$pw
DJANGO_SECRET_KEY=$pw
KAIROS_TEST_RUN_ID=$runid
KAIROS_ALLOWED_HOSTS=testserver,localhost
EOF
new_net="$prefix-net"
docker network inspect "$new_net" >/dev/null 2>&1 && exit 1
docker network create --internal --label "$label=$runid" "$new_net" >/dev/null
net=$new_net
create() {
  local name="$prefix-$1"; shift
  docker container inspect "$name" >/dev/null 2>&1 && exit 1
  docker create --name "$name" --pull never --network "$net" --label "$label=$runid" \
    --restart no --cpus 1 --memory 1g --memory-swap 1g --pids-limit 128 \
    --security-opt no-new-privileges --log-driver none --env-file "$work/test.env" "$@" >/dev/null
  containers+=("$name")
}
create pg --network-alias kairos-test-postgres --tmpfs /var/lib/postgresql/data:rw,size=256m "$pg_image"
docker start "$prefix-pg" >/dev/null
ready=0
for ((n=0;n<60;n++)); do
  if docker exec "$prefix-pg" pg_isready -h 127.0.0.1 -U kairos_test -d kairos_test >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[[ $ready == 1 ]]
create redis --network-alias kairos-test-redis --tmpfs /data:rw,size=64m --entrypoint /bin/sh "$redis_image" -ec \
  'exec redis-server --save "" --appendonly no --requirepass "$KAIROS_TEST_REDIS_PASSWORD" --maxmemory 128mb --maxmemory-policy noeviction'
docker start "$prefix-redis" >/dev/null
ready=0
for ((n=0;n<60;n++)); do
  if docker exec "$prefix-redis" sh -ec 'REDISCLI_AUTH="$KAIROS_TEST_REDIS_PASSWORD" redis-cli ping' 2>/dev/null | grep -q PONG; then ready=1; break; fi
  sleep 1
done
[[ $ready == 1 ]]
mkdir -m 0700 "$work/results"
chown 10001:10001 "$work/results"
create api --user 10001:10001 --read-only --tmpfs /tmp:rw,nosuid,size=256m,uid=10001,gid=10001 \
  --mount "type=bind,src=$source_dir,dst=/candidate,readonly" \
  --mount "type=bind,src=$wheels_dir,dst=/wheels,readonly" \
  --mount "type=bind,src=$work/results,dst=/results" --workdir /candidate --entrypoint /bin/sh "$api_image" -ec '
    python -m pip install --no-index --find-links /wheels --target /tmp/testlibs pytest==8.4.2 pytest-django==4.11.1
    export PYTHONPATH=/tmp/testlibs:/candidate
    python -m pytest --ds=kairos.integration_test_settings -q --tb=short -p no:cacheprovider --junitxml=/results/integration.xml
  '
timeout 600 docker start -a "$prefix-api" > "$work/test.log" 2>&1
test_exit=$(docker container inspect -f '{{.State.ExitCode}}' "$prefix-api")
[[ $test_exit == 0 ]]
tail -n 3 "$work/test.log"
