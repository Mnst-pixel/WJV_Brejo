#!/usr/bin/env bash
# Synthetic-data integration tests against existing runtime images, no pulls.
set -Eeuo pipefail
umask 077
[[ $# == 2 && $EUID == 0 ]] || { echo 'usage: test-api-isolated.sh /opt/kairos/runtime/p0/RUN/source/apps/api /opt/kairos/runtime/p0/RUN/wheels' >&2; exit 1; }
source_dir=$(realpath -e "$1")
wheels_dir=$(realpath -e "$2")
[[ $source_dir == /opt/kairos/runtime/p0/*/source/apps/api && $wheels_dir == /opt/kairos/runtime/p0/*/wheels ]]
[[ -f $source_dir/kairos/integration_test_settings.py ]]
repository_dir=$(realpath -e "$source_dir/../..")
[[ -f $repository_dir/services/parser/child.py ]]
(( $(awk '/MemAvailable:/ {print $2}' /proc/meminfo) > 2200000 ))
export COMPOSE_PROJECT_NAME=kairos
runid="$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 6)"
prefix="kairos-test-$runid"
work="/opt/kairos/runtime/tests/$prefix"
# Validate every existing parent before any creation or write. A namespace string
# alone does not prove ownership when an ancestor redirects through a symlink.
for parent in /opt /opt/kairos /opt/kairos/runtime /opt/kairos/runtime/tests; do
  [[ ! -L $parent ]]
  if [[ -e $parent ]]; then [[ -d $parent && $(realpath -e "$parent") == "$parent" ]]; fi
done
[[ $(realpath -m "$work") == "$work" ]]
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
  if [[ -d $work/clam-db && ! -L $work/clam-db ]]; then
    if [[ $(realpath -e "$work/clam-db") == "$work/clam-db" && $work == /opt/kairos/runtime/tests/kairos-test-* ]]; then
      rm -rf --one-file-system -- "$work/clam-db" || failed=1
    else failed=1; fi
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
api_image=${KAIROS_TEST_API_IMAGE:-$api_image}
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
KAIROS_ALLOWED_HOSTS=testserver,localhost,127.0.0.1
KAIROS_TEST_REPOSITORY=/source
KAIROS_LEGACY_DATA_DIR=/source/legacy/extracted
MINIO_ROOT_USER=kairos_test
MINIO_ROOT_PASSWORD=$pw
PARSER_API_TOKEN=$pw
KAIROS_PROXY_TOKEN=$pw
KAIROS_TEST_LIVE_UPLOAD=1
KAIROS_TEST_CLAMAV_HOST=kairos-test-clamav
EOF
if [[ -n ${KAIROS_TEST_API_IMAGE:-} ]]; then
  printf 'KAIROS_TEST_ARTIFACT_MODE=1\n' >> "$work/test.env"
fi
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
create pg --network-alias kairos-test-postgres --tmpfs /var/lib/postgresql/data:rw,size=512m "$pg_image"
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
clam_image=$(docker container inspect -f '{{.Image}}' kairos-clamav-1)
minio_image=$(docker container inspect -f '{{.Image}}' kairos-minio-1)
parser_image=$KAIROS_TEST_PARSER_IMAGE
for id in "$clam_image" "$minio_image" "$parser_image"; do [[ $id =~ ^sha256:[0-9a-f]{64}$ ]]; done
mkdir -m 0755 "$work/clam-db"
docker cp kairos-clamav-1:/var/lib/clamav/. "$work/clam-db/" >/dev/null
chmod -R a+rX "$work/clam-db"
find "$work/clam-db" -maxdepth 1 -type f -exec sha256sum '{}' + > "$work/clamav-signatures.sha256"
cat > "$work/clam.conf" <<'EOF'
Foreground yes
LogFile /tmp/clamd.log
LogTime yes
PidFile /tmp/clamd.pid
LocalSocket /tmp/clamd.sock
TCPSocket 3310
TCPAddr 0.0.0.0
User clamav
DatabaseDirectory /var/lib/clamav
MaxThreads 2
ConcurrentDatabaseReload no
StreamMaxLength 25M
MaxFileSize 25M
MaxScanSize 50M
MaxRecursion 10
MaxFiles 2000
SelfCheck 0
EOF
chmod 0644 "$work/clam.conf"
create clam --network-alias kairos-test-clamav --read-only --tmpfs /tmp:rw,size=64m \
  --mount "type=bind,src=$work/clam-db,dst=/var/lib/clamav,readonly" \
  --mount "type=bind,src=$work/clam.conf,dst=/test.conf,readonly" --entrypoint clamd "$clam_image" --config-file=/test.conf
docker start "$prefix-clam" >/dev/null
create minio --network-alias kairos-test-minio --user 1000:1000 --cap-drop ALL --read-only \
  --tmpfs /data:rw,size=128m,uid=1000,gid=1000 --tmpfs /tmp:rw,size=32m,uid=1000,gid=1000 \
  "$minio_image" server /data --console-address :9001
docker start "$prefix-minio" >/dev/null
create parser --network-alias parser --user 10001:10001 --cap-drop ALL --read-only \
  --tmpfs /tmp:rw,size=64m,uid=10001,gid=10001 "$parser_image"
docker start "$prefix-parser" >/dev/null
ready=0
for ((n=0;n<90;n++)); do
  if docker exec "$prefix-clam" clamdscan --config-file=/test.conf --ping 1 >/dev/null 2>&1 &&
     docker exec "$prefix-minio" curl -fsS http://127.0.0.1:9000/minio/health/ready >/dev/null 2>&1 &&
     docker exec "$prefix-parser" python -c 'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8090/healthz", timeout=2).status == 200' >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[[ $ready == 1 ]]
mkdir -m 0700 "$work/results"
chown 10001:10001 "$work/results"
create api --user 10001:10001 --read-only --tmpfs /tmp:rw,nosuid,size=256m,uid=10001,gid=10001 \
  --mount "type=bind,src=$source_dir,dst=/candidate,readonly" \
  --mount "type=bind,src=$repository_dir,dst=/source,readonly" \
  --mount "type=bind,src=$wheels_dir,dst=/wheels,readonly" \
  --mount "type=bind,src=$work/results,dst=/results" --workdir /candidate --entrypoint /bin/sh "$api_image" -ec '
    python -m pip install --no-index --find-links /wheels --target /tmp/testlibs pytest==8.4.2 pytest-django==4.11.1
    if test -n "${KAIROS_TEST_ARTIFACT_MODE:-}"; then
      cp /candidate/kairos/integration_test_settings.py /tmp/integration_test_settings.py
      export PYTHONPATH=/tmp/testlibs:/tmp:/app
      cd /app
      python -m pytest /candidate/tests --ds=integration_test_settings -o django_find_project=false -q --tb=short -p no:cacheprovider --junitxml=/results/integration.xml
    else
      export PYTHONPATH=/tmp/testlibs:/candidate
      python -m pytest --ds=kairos.integration_test_settings -q --tb=short -p no:cacheprovider --junitxml=/results/integration.xml
    fi
  '
api_attach_exit=0
timeout 600 docker start -a "$prefix-api" > "$work/test.log" 2>&1 || api_attach_exit=$?
if [[ $(docker container inspect -f '{{.State.Running}}' "$prefix-api") == true ]]; then
  docker stop --time 5 "$prefix-api" >/dev/null
fi
test_exit=$(docker container inspect -f '{{.State.ExitCode}}' "$prefix-api")
if (( api_attach_exit != 0 )); then test_exit=$api_attach_exit; fi
artifact_exit=0
python3 - "$work/results/integration.xml" <<'PY' || artifact_exit=$?
import sys
import xml.etree.ElementTree as ET
matches = [case for case in ET.parse(sys.argv[1]).getroot().iter('testcase') if case.get('name') == 'test_candidate_imports_match_the_git_sources']
assert len(matches) == 1 and all(matches[0].find(kind) is None for kind in ('failure', 'error', 'skipped'))
PY
if [[ $artifact_exit == 0 ]]; then printf 'artifact_code_hashes=PASS\n' >> "$work/result.txt"; else printf 'artifact_code_hashes=FAIL\n' >> "$work/result.txt"; fi
tail -n 3 "$work/test.log"
# Native Linux security and operational contracts use only disposable container
# filesystems and synthetic credentials, without the host Docker socket.
python3 - "$repository_dir" "$work/test.acl" <<'PY'
import importlib.util,sys,pathlib
path = pathlib.Path(sys.argv[1]) / 'scripts/tests/test_redis_acl.py'
spec = importlib.util.spec_from_file_location('fixture', path)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
pathlib.Path(sys.argv[2]).write_text(m.acl.render(m.credentials()))
PY
chmod 0644 "$work/test.acl" # Synthetic hashes only; no production identities.
create redis-acl --network-alias kairos-test-redis-acl --tmpfs /data:rw,size=64m \
  --mount "type=bind,src=$work/test.acl,dst=/test.acl,readonly" "$redis_image" \
  redis-server --save '' --appendonly no --aclfile /test.acl --maxmemory 64mb
docker start "$prefix-redis-acl" >/dev/null
ready=0
for ((n=0;n<30;n++)); do
  if docker exec "$prefix-redis-acl" redis-cli PING 2>&1 | grep -q NOAUTH; then ready=1; break; fi
  sleep 1
done
[[ $ready == 1 ]]
create native --user 0:0 --cap-drop ALL --read-only \
  --tmpfs /tmp:rw,nosuid,size=256m --tmpfs /opt/kairos:rw,nosuid,size=64m \
  --tmpfs /srv/kairos:rw,nosuid,size=64m \
  --tmpfs /root:rw,nosuid,size=16m,mode=0700 \
  --env KAIROS_TEST_REDIS_ACL=1 --env KAIROS_TEST_REDIS_ACL_HOST=kairos-test-redis-acl \
  --env KAIROS_TEST_REDIS_ACL_PORT=6379 \
  --env KAIROS_TEST_DB_ROLES=1 \
  --mount "type=bind,src=$repository_dir,dst=/source,readonly" \
  --mount "type=bind,src=$wheels_dir,dst=/wheels,readonly" \
  --workdir /source --entrypoint /bin/sh "$api_image" -ec '
    python -m pip install --no-index --find-links /wheels --target /tmp/testlibs pytest==8.4.2
    export PYTHONPATH=/tmp/testlibs:/app PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
    python -m pytest scripts/tests services/parser/test_parser.py -q --tb=short -p no:cacheprovider
  '
native_attach_exit=0
timeout 600 docker start -a "$prefix-native" > "$work/native.log" 2>&1 || native_attach_exit=$?
if [[ $(docker container inspect -f '{{.State.Running}}' "$prefix-native") == true ]]; then
  docker stop --time 5 "$prefix-native" >/dev/null
fi
native_exit=$(docker container inspect -f '{{.State.ExitCode}}' "$prefix-native")
if (( native_attach_exit != 0 )); then native_exit=$native_attach_exit; fi
tail -n 3 "$work/native.log"
wp_image=$(docker container inspect -f '{{.Image}}' kairos-wordpress-1)
edge_image=$(docker container inspect -f '{{.Image}}' kairos-edge-1)
for id in "$wp_image" "$edge_image"; do [[ $id =~ ^sha256:[0-9a-f]{64}$ ]]; done
create wp-contract --cap-drop ALL --read-only --tmpfs /tmp:rw,size=16m --tmpfs /var/www/html:rw,size=1m \
  --mount "type=bind,src=$repository_dir/wordpress,dst=/candidate,readonly" \
  --workdir /candidate --entrypoint /bin/sh "$wp_image" -ec \
  'php -l mu-plugins/kairos-admin-gate.php && php tests/test-admin-gate.php'
timeout 60 docker start -a "$prefix-wp-contract" > "$work/wordpress-contract.log" 2>&1
[[ $(docker container inspect -f '{{.State.ExitCode}}' "$prefix-wp-contract") == 0 ]]
tail -n 3 "$work/wordpress-contract.log"
create edge-contract --cap-drop ALL --read-only --tmpfs /tmp:rw,size=16m --tmpfs /data:rw,size=4m --tmpfs /config:rw,size=4m \
  --mount "type=bind,src=$repository_dir/infra/caddy/Caddyfile,dst=/etc/caddy/Caddyfile,readonly" \
  --entrypoint caddy "$edge_image" validate --config /etc/caddy/Caddyfile --adapter caddyfile
timeout 60 docker start -a "$prefix-edge-contract" > "$work/caddy-contract.log" 2>&1
[[ $(docker container inspect -f '{{.State.ExitCode}}' "$prefix-edge-contract") == 0 ]]
tail -n 3 "$work/caddy-contract.log"
# Git contracts use the host Git binary with private temporary repositories;
# these tests never call Docker, read credentials, or change global Git config.
python3 -m unittest discover -s "$repository_dir/scripts/tests" -p test_release_manifest.py > "$work/git-contracts.log" 2>&1
tail -n 3 "$work/git-contracts.log"
if [[ -n ${KAIROS_TEST_API_IMAGE:-} ]]; then
  create smoke --user 10001:10001 --read-only --tmpfs /tmp:rw,nosuid,size=64m,uid=10001,gid=10001 "$api_image"
  docker start "$prefix-smoke" >/dev/null
  ready=0
  for ((n=0;n<60;n++)); do
    if docker exec "$prefix-smoke" python -c 'import http.client; from pathlib import Path; assert Path("/app/staticfiles/staticfiles.json").is_file(); c=http.client.HTTPConnection("127.0.0.1",8000,timeout=3); c.request("GET","/api/health/live"); assert c.getresponse().status==200; c.close(); c=http.client.HTTPConnection("127.0.0.1",8000,timeout=3); c.request("GET","/static/admin/css/base.css"); assert c.getresponse().status==200; c.close(); c=http.client.HTTPConnection("127.0.0.1",8000,timeout=3); c.request("POST","/api/auth/login",body="{}",headers={"Content-Type":"application/json"}); assert c.getresponse().status==403' >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  [[ $ready == 1 ]]
  printf 'gunicorn_smoke=PASS\nadmin_static_smoke=PASS\n' >> "$work/result.txt"
fi
printf 'api_suite_exit=%s\nnative_suite_exit=%s\n' "$test_exit" "$native_exit" >> "$work/result.txt"
[[ $test_exit == 0 && $native_exit == 0 && $artifact_exit == 0 ]]
