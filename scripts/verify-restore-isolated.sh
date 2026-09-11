#!/usr/bin/env bash
# Restore only into resources created by this invocation; never uses live Compose.
set -Eeuo pipefail
umask 077

die() { printf 'KAIROS_RESTORE_ISOLATED=FAIL reason=%s\n' "$1" >&2; exit 1; }
[[ $# == 2 ]] || die 'usage: verify-restore-isolated.sh /srv/kairos/backups/kairos-TIMESTAMP.tar.gz.enc /absolute/passphrase-file'
[[ $EUID == 0 ]] || die 'root required for protected backup and Docker access'
[[ -x /usr/bin/docker && -x /usr/bin/env ]] || die 'fixed local Docker runtime required'
# Ignore inherited contexts, remote daemons and Docker config/plugins. Creation,
# inspection and cleanup must all address this same local socket.
docker() { /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/docker --host unix:///var/run/docker.sock "$@"; }
docker_timeout() { local duration=$1; shift; /usr/bin/timeout "$duration" /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/docker --host unix:///var/run/docker.sock "$@"; }
for tool in docker python3 openssl realpath stat df timeout; do command -v "$tool" >/dev/null || die "missing prerequisite: $tool"; done
export COMPOSE_PROJECT_NAME=kairos
root=/srv/kairos/backups
[[ -d $root && ! -L $root && $(realpath -e "$root") == "$root" ]] || die 'invalid backup root'
archive=$(realpath -e -- "$1")
[[ $archive == "$root"/kairos-*.tar.gz.enc && $(dirname "$archive") == "$root" ]] || die 'archive outside backup root'
passfile=$(realpath -e -- "$2")
[[ -f $passfile && $(stat -c '%u:%a' "$passfile") == 0:600 ]] || die 'passphrase file must be root-owned mode 0600'
[[ $(stat -c %s "$passfile") -ge 32 ]] || die 'passphrase file too short'
# File contains only the encryption passphrase and optional terminal newline, NOT .env.
max_bytes=${KAIROS_RESTORE_MAX_BYTES:-2147483648}
[[ $max_bytes =~ ^[0-9]+$ && ${#max_bytes} -le 11 ]] || die 'invalid size budget'
(( max_bytes >= 1048576 && max_bytes <= 17179869184 )) || die 'size budget outside 1 MiB..16 GiB'
(( $(stat -c %s "$archive") <= max_bytes )) || die 'encrypted archive exceeds budget'
available=$(df -PB1 "$root" | awk 'NR==2 {print $4}')
(( available >= max_bytes * 4 + 1073741824 )) || die 'insufficient disk headroom for configured restore budget'

runid="$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 6)"
prefix="kairos-restore-$runid"
work=$(mktemp -d "$root/$prefix.XXXXXXXX")
[[ $(realpath -e "$work") == "$root/$prefix."* ]] || die 'invalid work directory'
evidence="$root/$prefix.evidence"
mkdir -m 0700 "$evidence"
containers=() volumes=() networks=()
label=com.kairos.restore.run
cleanup() {
  local status=$? item actual failed=0
  trap - EXIT INT TERM
  set +e
  for item in "${containers[@]}"; do
    actual=$(docker container inspect -f "{{index .Config.Labels \"$label\"}}" "$item" 2>/dev/null)
    if [[ $actual == "$runid" ]]; then docker rm -f "$item" >/dev/null 2>&1 || failed=1; else failed=1; fi
  done
  for item in "${volumes[@]}"; do
    actual=$(docker volume inspect -f "{{index .Labels \"$label\"}}" "$item" 2>/dev/null)
    if [[ $actual == "$runid" ]]; then docker volume rm "$item" >/dev/null 2>&1 || failed=1; else failed=1; fi
  done
  for item in "${networks[@]}"; do
    actual=$(docker network inspect -f "{{index .Labels \"$label\"}}" "$item" 2>/dev/null)
    if [[ $actual == "$runid" ]]; then docker network rm "$item" >/dev/null 2>&1 || failed=1; else failed=1; fi
  done
  if [[ -d $work && ! -L $work && $(realpath -e "$work") == "$root/$prefix."* ]]; then
    rm -rf --one-file-system -- "$work" || failed=1
  else failed=1; fi
  printf 'exit_status=%s\ncleanup_failed=%s\n' "$status" "$failed" >> "$evidence/result.txt"
  if (( status == 0 && failed == 0 )); then
    printf 'KAIROS_RESTORE_ISOLATED=PASS scope=archived_data evidence=%s\n' "$evidence"
  else
    printf 'KAIROS_RESTORE_ISOLATED=FAIL evidence=%s cleanup_failed=%s\n' "$evidence" "$failed" >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'run=%s\narchive=%s\n' "$runid" "$(basename "$archive")" > "$evidence/result.txt"

# Never print SQL/server logs: a failed restore can contain personal values.
quiet() {
  local status=0
  "$@" > "$work/last-command.log" 2>&1 || status=$?
  if (( status != 0 )); then
    install -m 0600 "$work/last-command.log" "$evidence/private-error.log"
    die "command failed: $1 exit=$status (protected diagnostic retained on VPS)"
  fi
}
image_id() {
  local id
  id=$(docker image inspect -f '{{.Id}}' "$2") || die "local image unavailable: $1"
  [[ $id =~ ^sha256:[0-9a-f]{64}$ ]] || die 'unexpected image ID'
  printf '%s %s\n' "$1" "$id" >> "$evidence/images.txt"
  printf '%s' "$id"
}
pg_image=$(image_id postgres "${KAIROS_RESTORE_PG_IMAGE:-pgvector/pgvector:0.8.6-pg17-trixie}")
my_image=$(image_id mariadb "${KAIROS_RESTORE_MY_IMAGE:-mariadb:12.3.3}")
minio_image=$(image_id minio "${KAIROS_RESTORE_MINIO_IMAGE:-kairos-minio}")
mc_image=$(image_id mc "${KAIROS_RESTORE_MC_IMAGE:-minio/mc:RELEASE.2025-08-13T08-35-41Z}")
probe_image=''
scoped_roles=${KAIROS_RESTORE_SCOPED_ROLES:-0}
[[ $scoped_roles == 0 || $scoped_roles == 1 ]] || die 'invalid scoped restore opt-in'
[[ $scoped_roles == 0 || -n ${KAIROS_RESTORE_API_IMAGE:-} ]] || die 'scoped restore requires a migration candidate'
if [[ -n ${KAIROS_RESTORE_API_IMAGE:-} || -n ${KAIROS_RESTORE_API_REVISION:-} ]]; then
  [[ ${KAIROS_RESTORE_API_IMAGE:-} =~ ^sha256:[0-9a-f]{64}$ && ${KAIROS_RESTORE_API_REVISION:-} =~ ^[0-9a-f]{40}$ ]] || die 'exact migration candidate image and revision required'
  probe_image=$(image_id migration-api "$KAIROS_RESTORE_API_IMAGE")
  [[ $(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$probe_image") == "$KAIROS_RESTORE_API_REVISION" ]] || die 'migration candidate revision mismatch'
  probe_source=$(realpath -e "$(dirname "${BASH_SOURCE[0]}")/restore-migration-probe.py")
  [[ $probe_source == /opt/kairos/runtime/p0/*/source/scripts/restore-migration-probe.py || $probe_source == /opt/kairos/current/scripts/restore-migration-probe.py ]] || die 'unsupported migration probe source'
fi

cat > "$work/archive-check.py" <<'PY'
import hashlib, os, pathlib, re, sys, tarfile

def safe_name(name):
    if not name or name.startswith('/') or '\\' in name or any(ord(c) < 32 for c in name):
        raise ValueError('unsafe archive member name')
    p = pathlib.PurePosixPath(name)
    if '..' in p.parts:
        raise ValueError('archive traversal')
    return p

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

mode, source = sys.argv[1:3]
if mode == 'checksum':
    archive = pathlib.Path(source)
    lines = pathlib.Path(source + '.sha256').read_text().splitlines()
    if len(lines) != 1 or not re.fullmatch(r'[0-9a-fA-F]{64} [ *].+', lines[0]):
        raise ValueError('invalid external checksum')
    if pathlib.Path(lines[0][66:]).name != archive.name or digest(archive) != lines[0][:64].lower():
        raise ValueError('external checksum mismatch')
elif mode == 'extract':
    dest, budget = pathlib.Path(sys.argv[3]), int(sys.argv[4])
    dest.mkdir(mode=0o700)
    total, count, seen = 0, 0, set()
    with tarfile.open(source, 'r|*') as archive:
        for member in archive:
            count += 1
            if count > 100000: raise ValueError('too many archive members')
            relative = safe_name(member.name)
            if str(relative) == '.' and member.isdir(): continue
            if str(relative) in seen: raise ValueError('duplicate archive path')
            seen.add(str(relative))
            if not (member.isdir() or member.isfile()): raise ValueError('links and special archive members refused')
            target = dest.joinpath(*relative.parts)
            if member.isdir(): target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                total += member.size
                if member.size < 0 or total > budget: raise ValueError('archive exceeds extraction budget')
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.extractfile(member) as inp, open(target, 'xb') as out:
                    for block in iter(lambda: inp.read(1024 * 1024), b''): out.write(block)
elif mode == 'manifest':
    base = pathlib.Path(source)
    actual = {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}
    expected = set()
    for line in (base / 'MANIFEST.sha256').read_text().splitlines():
        if not re.fullmatch(r'[0-9a-fA-F]{64} [ *].+', line): raise ValueError('invalid manifest')
        name = str(safe_name(line[66:]))
        if name in expected or name == 'MANIFEST.sha256': raise ValueError('duplicate/recursive manifest')
        expected.add(name)
        if digest(base / name) != line[:64].lower(): raise ValueError('manifest hash mismatch')
    if actual != expected | {'MANIFEST.sha256'}: raise ValueError('manifest coverage mismatch')
    required = {'postgres.dump', 'mariadb.sql', 'wordpress.tar', 'hermes.tar', 'secrets.env', 'git-revision.txt'}
    if not required <= actual: raise ValueError('required backup component missing')
    if not re.fullmatch(r'[0-9a-f]{40}\s*', (base / 'git-revision.txt').read_text()): raise ValueError('invalid Git revision')
    if not (base / 'secrets.env').stat().st_size: raise ValueError('empty config backup')
    if not (base / 'minio-documents').is_dir(): raise ValueError('object storage component missing')
elif mode == 'compare':
    def inventory(base):
        return {p.relative_to(base).as_posix(): (p.stat().st_size, digest(p)) for p in base.rglob('*') if p.is_file()}
    left, right = inventory(pathlib.Path(source)), inventory(pathlib.Path(sys.argv[3]))
    if left != right: raise ValueError('restored objects differ')
    print('object_count=' + str(len(left)))
    print('object_bytes=' + str(sum(value[0] for value in left.values())))
else: raise ValueError('unknown validation mode')
PY
quiet python3 "$work/archive-check.py" checksum "$archive"
quiet openssl enc -d -aes-256-cbc -pbkdf2 -iter 300000 -pass "file:$passfile" -in "$archive" -out "$work/archive.tar.gz"
quiet python3 "$work/archive-check.py" extract "$work/archive.tar.gz" "$work/extracted" "$max_bytes"
quiet python3 "$work/archive-check.py" manifest "$work/extracted"
quiet python3 "$work/archive-check.py" extract "$work/extracted/wordpress.tar" "$work/wordpress" "$max_bytes"
quiet python3 "$work/archive-check.py" extract "$work/extracted/hermes.tar" "$work/hermes" "$max_bytes"
[[ -s $work/wordpress/wp-config.php ]] || die 'WordPress config missing'
find "$work/hermes" -type f -print -quit | grep -q . || die 'Hermes files missing'
printf 'checksum=PASS\nmanifest=PASS\nwordpress_files=PASS\nhermes_files=PASS\nprotected_config=PASS\n' >> "$evidence/result.txt"

new_volume() {
  local name="$prefix-$1"
  docker volume inspect "$name" >/dev/null 2>&1 && die 'volume name collision'
  quiet docker volume create --label "$label=$runid" --label com.kairos.scope=restore "$name"
  volumes+=("$name")
  printf 'volume=%s\n' "$name" >> "$evidence/resources.txt"
}
create_container() {
  local name="$prefix-$1"; shift
  docker container inspect "$name" >/dev/null 2>&1 && die 'container name collision'
  quiet docker create --name "$name" --pull never --label "$label=$runid" --label com.kairos.scope=restore \
    --restart no --cpus 0.5 --memory 640m --memory-swap 640m --pids-limit 128 \
    --security-opt no-new-privileges --log-driver none "$@"
  containers+=("$name")
  printf 'container=%s\n' "$name" >> "$evidence/resources.txt"
}
wait_ready() {
  local container=$1; shift
  for (( attempt=0; attempt<90; attempt++ )); do
    if docker_timeout 5 exec "$container" "$@" > /dev/null 2>&1; then return; fi
    sleep 2
  done
  die 'temporary database did not become ready'
}

pw=$(openssl rand -hex 32)
printf 'POSTGRES_USER=kairos_restore\nPOSTGRES_DB=kairos_restore\nPOSTGRES_PASSWORD=%s\n' "$pw" > "$work/pg.env"
new_volume pg
create_container pg --network none --env-file "$work/pg.env" --mount "type=volume,src=$prefix-pg,dst=/var/lib/postgresql/data" "$pg_image"
quiet docker start "$prefix-pg"
wait_ready "$prefix-pg" pg_isready -h 127.0.0.1 -U kairos_restore -d kairos_restore
quiet docker_timeout 600 exec -i "$prefix-pg" pg_restore -U kairos_restore -d kairos_restore --no-owner --no-privileges --exit-on-error < "$work/extracted/postgres.dump"
quiet docker exec "$prefix-pg" psql -U kairos_restore -d kairos_restore -v ON_ERROR_STOP=1 -Atc \
  "DO \$\$ BEGIN IF (SELECT count(*) FROM django_migrations)=0 OR (SELECT count(*) FROM core_user)=0 THEN RAISE EXCEPTION 'required database data missing'; END IF; IF EXISTS (SELECT 1 FROM pg_constraint WHERE NOT convalidated) OR EXISTS (SELECT 1 FROM pg_index WHERE NOT indisvalid) THEN RAISE EXCEPTION 'invalid database structures'; END IF; END \$\$;"
docker exec "$prefix-pg" psql -U kairos_restore -d kairos_restore -v ON_ERROR_STOP=1 -Atc \
  "SELECT 'tables='||count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'; SELECT 'users='||count(*) FROM core_user; SELECT 'migrations='||count(*) FROM django_migrations;" > "$evidence/postgres-counts.txt" 2> "$work/pg-errors"
if [[ -n $probe_image ]]; then
  # Share only the network-none namespace created above. Loopback reaches this
  # disposable PostgreSQL; there is no production network, broker or storage.
  cp -- "$work/pg.env" "$work/probe.env"
  printf 'POSTGRES_HOST=127.0.0.1\nDJANGO_SECRET_KEY=%s\nKAIROS_RESTORE_RUN_ID=%s\nPYTHONPATH=/app\n' "$pw" "$runid" >> "$work/probe.env"
  if [[ $scoped_roles == 1 ]]; then
    # The provisioning SQL intentionally supports only database kairos. Make a
    # second copy in this fresh network-none cluster; the archived restore remains.
    quiet docker exec "$prefix-pg" createdb -U kairos_restore --template=kairos_restore kairos
    sed -i 's/^POSTGRES_DB=kairos_restore$/POSTGRES_DB=kairos/' "$work/probe.env"
    printf 'KAIROS_RESTORE_SCOPED_ROLES=1\n' >> "$work/probe.env"
  fi
  create_container migration-probe --network "container:$prefix-pg" --user 10001:10001 --cap-drop ALL --read-only \
    --tmpfs /tmp:rw,nosuid,size=64m,uid=10001,gid=10001 --env-file "$work/probe.env" \
    --mount "type=bind,src=$(dirname "$probe_source"),dst=/restore-probes,readonly" --entrypoint python "$probe_image" /restore-probes/restore-migration-probe.py
  quiet docker_timeout 300 start -a "$prefix-migration-probe"
  [[ $(docker container inspect -f '{{.State.ExitCode}}' "$prefix-migration-probe") == 0 ]] || die 'migration probe failed'
  install -m 0600 "$work/last-command.log" "$evidence/migration-probe.json"
  quiet python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["status"] == "PASS"' "$evidence/migration-probe.json"
  printf 'candidate_forward_migrations=PASS\ncandidate_revision=%s\n' "$KAIROS_RESTORE_API_REVISION" >> "$evidence/result.txt"
fi
quiet docker stop -t 30 "$prefix-pg"
printf 'postgres_restore=PASS\n' >> "$evidence/result.txt"

printf 'MARIADB_DATABASE=kairos_restore\nMARIADB_ROOT_PASSWORD=%s\n' "$pw" > "$work/my.env"
new_volume my
create_container my --network none --env-file "$work/my.env" --mount "type=volume,src=$prefix-my,dst=/var/lib/mysql" "$my_image"
quiet docker start "$prefix-my"
wait_ready "$prefix-my" healthcheck.sh --connect --innodb_initialized
quiet docker_timeout 600 exec -i "$prefix-my" sh -ec 'exec mariadb --user=root --password="$MARIADB_ROOT_PASSWORD" kairos_restore' < "$work/extracted/mariadb.sql"
quiet docker_timeout 300 exec "$prefix-my" sh -ec 'exec mariadb-check --user=root --password="$MARIADB_ROOT_PASSWORD" --check kairos_restore'
docker exec "$prefix-my" sh -ec 'exec mariadb --user=root --password="$MARIADB_ROOT_PASSWORD" --batch --skip-column-names kairos_restore -e "SELECT COUNT(*) FROM wp_options; SELECT COUNT(*) FROM wp_users;"' > "$work/my-counts" 2> "$work/my-errors"
[[ $(wc -l < "$work/my-counts") == 2 ]] || die 'MariaDB counts missing'
while read -r count; do [[ $count =~ ^[1-9][0-9]*$ ]] || die 'required WordPress data missing'; done < "$work/my-counts"
printf 'wp_options=%s\nwp_users=%s\n' "$(sed -n 1p "$work/my-counts")" "$(sed -n 2p "$work/my-counts")" > "$evidence/mariadb-counts.txt"
quiet docker stop -t 30 "$prefix-my"
printf 'mariadb_restore=PASS\n' >> "$evidence/result.txt"

net="$prefix-net"
docker network inspect "$net" >/dev/null 2>&1 && die 'network name collision'
quiet docker network create --internal --label "$label=$runid" --label com.kairos.scope=restore "$net"
networks+=("$net")
printf 'network=%s\n' "$net" >> "$evidence/resources.txt"
printf 'MINIO_ROOT_USER=kairos_restore\nMINIO_ROOT_PASSWORD=%s\n' "$pw" > "$work/minio.env"
new_volume minio
create_container minio-init --network none --user 0:0 \
  --mount "type=volume,src=$prefix-minio,dst=/data" --entrypoint /bin/sh "$minio_image" -ec 'chown 1000:1000 /data'
quiet docker_timeout 30 start -a "$prefix-minio-init"
[[ $(docker container inspect -f '{{.State.ExitCode}}' "$prefix-minio-init") == 0 ]] || die 'temporary MinIO volume initialization failed'
create_container minio --network "$net" --network-alias restore-minio --env-file "$work/minio.env" \
  --mount "type=volume,src=$prefix-minio,dst=/data" "$minio_image" server /data --console-address :9001
quiet docker start "$prefix-minio"
mkdir -m 0700 "$work/objects-returned"
create_container mc --network "$net" --env-file "$work/minio.env" \
  --mount "type=bind,src=$work/extracted/minio-documents,dst=/backup,readonly" \
  --mount "type=bind,src=$work/objects-returned,dst=/returned" \
  --entrypoint /bin/sh "$mc_image" -ec '
    ready=0
    for n in $(seq 1 90); do
      if mc alias set restore http://restore-minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 && mc ready restore >/dev/null 2>&1; then ready=1; break; fi
      sleep 2
    done
    test "$ready" = 1
    mc mb restore/documents >/dev/null
    mc mirror /backup restore/documents >/dev/null
    mc mirror restore/documents /returned >/dev/null
  '
quiet docker_timeout 600 start -a "$prefix-mc"
[[ $(docker container inspect -f '{{.State.ExitCode}}' "$prefix-mc") == 0 ]] || die 'MinIO client restore failed'
python3 "$work/archive-check.py" compare "$work/extracted/minio-documents" "$work/objects-returned" > "$evidence/minio-counts.txt" 2> "$work/object-errors"
printf 'minio_restore_and_hashes=PASS\n' >> "$evidence/result.txt"
printf '%s\n' \
  'NOT_VERIFIED=cross_system_point_in_time_consistency,original_row_count_equivalence,ownership_and_grants,object_versions_and_policies,application_runtime,external_configuration,offsite_recovery,no_touch_comparison' \
  'This result proves recovery of archived data only; independent no-touch and application gates remain mandatory.' >> "$evidence/result.txt"
# Success is emitted only by cleanup after owned resource removal succeeds.
