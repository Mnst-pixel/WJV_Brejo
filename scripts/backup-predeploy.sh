#!/usr/bin/env bash
# Additive backup for a controlled deployment; never invokes retention or restore.
set +x
set -Eeuo pipefail
umask 077

die() { printf 'KAIROS_PREDEPLOY_BACKUP=FAIL reason=%s\n' "$1" >&2; exit 1; }
[[ $# == 0 && $EUID == 0 ]] || die 'run as root without arguments'
for tool in docker python3 openssl git tar sha256sum realpath stat flock timeout; do
  command -v "$tool" >/dev/null || die "missing prerequisite: $tool"
done
export COMPOSE_PROJECT_NAME=kairos
root=/srv/kairos/backups
code=/opt/kairos/current
secret=/opt/kairos/secrets/.env
[[ -d $root && ! -L $root && $(realpath -e "$root") == "$root" && $(stat -c %u "$root") == 0 ]] || die 'invalid backup root'
[[ -f $secret && ! -L $secret && $(stat -c '%u:%a' "$secret") == 0:600 ]] || die 'protected env must be root-owned mode 0600'
[[ $(realpath -e "$code") == /opt/kairos/* ]] || die 'code checkout outside Kairos namespace'
[[ ! -L $root/.kairos-predeploy.lock ]] || die 'unsafe lock path'
exec 9> "$root/.kairos-predeploy.lock"
flock -n 9 || die 'another predeploy backup is running'

runid="$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 6)"
prefix="kairos-backup-$runid"
work=$(mktemp -d "$root/$prefix.XXXXXXXX")
[[ $(realpath -e "$work") == "$root/$prefix."* ]] || die 'invalid staging directory'
evidence="$root/$prefix.evidence"
mkdir -m 0700 "$evidence"
[[ $(realpath -e "$evidence") == "$evidence" ]] || die 'invalid evidence directory'
payload="$work/payload"
mkdir -m 0700 "$payload"
archive="$root/kairos-predeploy-$runid.tar.gz.enc"
pending="$archive.pending"
checksum_pending="$archive.sha256.pending"
[[ ! -e $archive && ! -e $pending && ! -e $archive.sha256 && ! -e $checksum_pending ]] || die 'backup name collision'
mc_id=''
passphrase=''
phase=preflight
failed_command=''
failed_command_exit=''
cleanup() {
  local status=$? failed=0 owner
  trap - EXIT INT TERM
  set +e
  if (( status != 0 )) && [[ -f $work/private-command.log ]]; then
    install -m 0600 "$work/private-command.log" "$evidence/private-error.log" || failed=1
  fi
  if [[ -n $mc_id ]]; then
    owner=$(docker container inspect -f '{{index .Config.Labels "com.kairos.backup.run"}}' "$mc_id" 2>/dev/null)
    if [[ $owner == "$runid" ]]; then
      # State.Error can contain private paths: project only these fields into a
      # protected file; never print a raw inspect or container output.
      docker container inspect -f '{"ExitCode":{{.State.ExitCode}},"OOMKilled":{{json .State.OOMKilled}},"Error":{{json .State.Error}}}' "$mc_id" \
        > "$evidence/private-mc-state.json" 2> "$evidence/private-inspect-error.log" || failed=1
      chmod 0600 "$evidence/private-mc-state.json" "$evidence/private-inspect-error.log" || failed=1
      docker rm -f "$mc_id" > /dev/null 2> "$evidence/private-cleanup-error.log" || failed=1
      chmod 0600 "$evidence/private-cleanup-error.log" || failed=1
    else failed=1; fi
  fi
  if [[ -d $work && ! -L $work && $(realpath -e "$work") == "$root/$prefix."* ]]; then
    rm -rf --one-file-system -- "$work" || failed=1
  else failed=1; fi
  unset passphrase
  printf 'run=%s\nphase=%s\nexit_status=%s\nfailed_command=%s\nfailed_command_exit=%s\ncleanup_failed=%s\n' \
    "$runid" "$phase" "$status" "$failed_command" "$failed_command_exit" "$failed" > "$evidence/result.txt"
  chmod 0600 "$evidence/result.txt" || failed=1
  if (( status == 0 && failed == 0 )); then
    printf 'KAIROS_PREDEPLOY_BACKUP=PASS scope=archive_created archive=%s\n' "$archive"
    printf 'RECOVERABILITY=NOT_YET_VERIFIED run_the_isolated_restore_for_this_exact_archive\n'
  else
    printf 'KAIROS_PREDEPLOY_BACKUP=FAIL cleanup_failed=%s pending_if_present=%s evidence=%s\n' "$failed" "$pending" "$evidence" >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Diagnostics can contain SQL/private filenames; preserve them privately before
# cleanup. Record only the executable/step name, never command arguments.
command_failed() {
  failed_command_exit=$1
  failed_command=$2
  die "command failed: $failed_command exit=$failed_command_exit (protected diagnostic retained on VPS)"
}
quiet() {
  local command_status=0
  "$@" > "$work/private-command.log" 2>&1 || command_status=$?
  if (( command_status != 0 )); then command_failed "$command_status" "$1"; fi
}
container_id() {
  local id info
  id=$(docker container inspect -f '{{.Id}}' "kairos-$1-1") || die "missing Kairos service: $1"
  info=$(docker container inspect -f '{{.Name}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Running}}' "$id")
  [[ $id =~ ^[0-9a-f]{64}$ && $info == "/kairos-$1-1|kairos|$1|true" ]] || die "unexpected service identity: $1"
  printf '%s' "$id"
}
pg_id=$(container_id postgres)
my_id=$(container_id mariadb)
minio_id=$(container_id minio)
[[ $(docker network inspect -f '{{.Name}}|{{index .Labels "com.docker.compose.project"}}|{{.Internal}}' kairos-data) == 'kairos-data|kairos|true' ]] || die 'unexpected data network ownership'
[[ $(docker container inspect -f '{{with index .NetworkSettings.Networks "kairos-data"}}{{.NetworkID}}{{end}}' "$minio_id") == "$(docker network inspect -f '{{.Id}}' kairos-data)" ]] || die 'MinIO is not on the verified data network'
mc_image=$(docker image inspect -f '{{.Id}}' minio/mc:RELEASE.2025-08-13T08-35-41Z)
[[ $mc_image =~ ^sha256:[0-9a-f]{64}$ ]] || die 'local mc image unavailable'

# Parse selected literal env values without sourcing shell code or interpolating.
cat > "$work/env-value.py" <<'PY'
import pathlib, sys

source, requested = sys.argv[1:3]
values = {}
for line in pathlib.Path(source).read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    key, value = key.strip(), value.strip()
    if key not in {'BACKUP_ENCRYPTION_PASSPHRASE', 'MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD'}:
        continue
    if key in values:
        raise ValueError('duplicate backup credential key')
    if value.startswith(('"', "'")):
        if len(value) < 2 or value[-1] != value[0]:
            raise ValueError('unclosed env quote')
        value = value[1:-1]
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError('invalid literal credential')
    values[key] = value
if requested == 'mc':
    for key in ('MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD'):
        print(key + '=' + values[key])
else:
    value = values[requested]
    if requested == 'BACKUP_ENCRYPTION_PASSPHRASE' and len(value) < 32:
        raise ValueError('backup passphrase is too short')
    print(value, end='')
PY
phase=credentials
passphrase=$(python3 "$work/env-value.py" "$secret" BACKUP_ENCRYPTION_PASSPHRASE 2> "$work/private-command.log") || command_failed "$?" credential_parser
python3 "$work/env-value.py" "$secret" mc > "$work/mc.env" 2> "$work/private-command.log" || command_failed "$?" minio_credential_parser

git -C "$code" rev-parse HEAD > "$payload/git-revision.txt"
git -C "$code" status --porcelain > "$payload/git-status.txt"
[[ ! -s $payload/git-status.txt ]] || die 'deployed checkout is not clean; investigate before backup/deploy'
date -u +%Y-%m-%dT%H:%M:%SZ > "$payload/capture-started-at.txt"
printf 'mc_image=%s\npostgres_container=%s\nmariadb_container=%s\nminio_container=%s\n' "$mc_image" "$pg_id" "$my_id" "$minio_id" > "$payload/backup-identities.txt"

phase=postgres_dump
timeout 900 docker exec "$pg_id" sh -ec 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$payload/postgres.dump" 2> "$work/private-command.log" || command_failed "$?" postgres_dump
phase=mariadb_dump
timeout 900 docker exec "$my_id" sh -ec 'exec mariadb-dump --single-transaction --quick --routines --events --triggers --user="$MARIADB_USER" --password="$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
  > "$payload/mariadb.sql" 2> "$work/private-command.log" || command_failed "$?" mariadb_dump
[[ -s $payload/postgres.dump && -s $payload/mariadb.sql ]] || die 'database dump missing or empty'

mkdir -m 0700 "$payload/minio-documents"
phase=minio_create
docker container inspect "$prefix-mc" >/dev/null 2>&1 && die 'backup container name collision'
mc_id=$(docker create --name "$prefix-mc" --pull never --restart no --network kairos-data \
  --label "com.kairos.backup.run=$runid" --label com.kairos.scope=backup \
  --env-file "$work/mc.env" --mount "type=bind,src=$payload/minio-documents,dst=/backup" \
  --security-opt no-new-privileges --cap-drop ALL --cpus 0.35 --memory 256m --memory-swap 256m --pids-limit 64 \
  --log-driver none --entrypoint /bin/sh "$mc_image" -ec \
  'umask 077; mkdir -m 0700 /tmp/kairos-backup-mc; mc --config-dir /tmp/kairos-backup-mc alias set kairos http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc --config-dir /tmp/kairos-backup-mc mirror kairos/documents /backup >/dev/null' \
  2> "$work/private-command.log") || command_failed "$?" minio_create
[[ $mc_id =~ ^[0-9a-f]{64}$ ]] || die 'invalid backup container ID'
phase=minio_mirror
quiet timeout 900 docker start -a "$mc_id"
mc_exit=$(docker container inspect -f '{{.State.ExitCode}}' "$mc_id")
[[ $mc_exit == 0 ]] || command_failed "$mc_exit" minio_mirror

# Files can change during capture. GNU tar exit 1 is treated as failure, not PASS.
for component in wordpress hermes; do
  phase="${component}_archive"
  [[ -d /srv/kairos/$component && ! -L /srv/kairos/$component && $(realpath -e "/srv/kairos/$component") == "/srv/kairos/$component" ]] || die 'unexpected storage path'
  quiet tar -C "/srv/kairos/$component" --one-file-system -cf "$payload/$component.tar" .
done
install -m 0600 "$secret" "$payload/secrets.env"

mkdir -m 0700 "$payload/configuration"
phase=configuration
copy_config() {
  local source=$1 destination=$2 resolved
  [[ -f $source ]] || die 'required Kairos configuration is missing'
  resolved=$(realpath -e -- "$source")
  case "$resolved" in
    /opt/kairos/*|/etc/nginx/sites-available/kairos-sslip.conf|/etc/nginx/sites-enabled/kairos-sslip.conf|/etc/systemd/system/kairos-*) ;;
    *) die 'configuration resolves outside approved Kairos paths' ;;
  esac
  install -m 0600 "$resolved" "$payload/configuration/$destination"
  printf '%s\t%s\t%s\n' "$source" "$resolved" "$destination" >> "$payload/configuration/origins.tsv"
}
copy_config "$code/infra/compose/compose.yaml" compose.yaml
copy_config "$code/infra/caddy/Caddyfile" Caddyfile
copy_config /etc/nginx/sites-enabled/kairos-sslip.conf kairos-nginx.conf
for unit in kairos-backup.service kairos-backup.timer kairos-health.service kairos-health.timer; do
  copy_config "/etc/systemd/system/$unit" "$unit"
done

copy_api_compose_configs() {
  local api_id config_files path resolved baseline extra=0
  local -a paths
  api_id=$(container_id api)
  config_files=$(docker container inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$api_id")
  [[ -n $config_files && $config_files != '<no value>' && $config_files != ,* && $config_files != *, && $config_files != *,,* ]] || die 'API Compose configuration list missing or malformed'
  [[ $config_files != *[[:cntrl:]]* ]] || die 'API Compose configuration list contains control characters'
  baseline=$(realpath -e -- "$code/infra/compose/compose.yaml")
  IFS=',' read -r -a paths <<< "$config_files"
  printf '%s\n' "$config_files" > "$payload/configuration/api-compose-config-files.txt"
  for path in "${paths[@]}"; do
    [[ $path == /opt/kairos/* ]] || die 'API Compose configuration path is outside Kairos'
    resolved=$(realpath -e -- "$path")
    [[ $resolved == /opt/kairos/* ]] || die 'API Compose configuration resolves outside Kairos'
    [[ $resolved == "$baseline" ]] && continue
    extra=$((extra + 1))
    copy_config "$path" "api-compose-extra-$extra.yaml"
  done
}
copy_api_compose_configs

phase=metadata
python3 - "$payload" <<'PY'
import json, pathlib, subprocess, sys

dest = pathlib.Path(sys.argv[1])
def output(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
ids = output(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=kairos']).splitlines()
template = '{{.Id}}|{{.Name}}|{{.Image}}|{{.State.Status}}|{{.State.StartedAt}}|{{index .Config.Labels "com.docker.compose.service"}}'
containers = []
for identifier in ids:
    fields = output(['docker', 'container', 'inspect', '-f', template, identifier]).split('|')
    if len(fields) != 6 or not fields[1].startswith('/kairos-'):
        raise ValueError('unexpected Kairos container metadata')
    containers.append(dict(zip(('id', 'name', 'image_id', 'status', 'started_at', 'service'), fields)))
images = []
for identifier in sorted({row['image_id'] for row in containers}):
    # Explicit projections exclude environment, arguments and credentials.
    tags = json.loads(output(['docker', 'image', 'inspect', '-f', '{{json .RepoTags}}', identifier]))
    digests = json.loads(output(['docker', 'image', 'inspect', '-f', '{{json .RepoDigests}}', identifier]))
    revision = json.loads(output(['docker', 'image', 'inspect', '-f', '{{json (index .Config.Labels "org.opencontainers.image.revision")}}', identifier]))
    images.append({'id': identifier, 'tags': tags, 'digests': digests, 'revision': revision})
(dest / 'docker-metadata.json').write_text(json.dumps({'containers': containers, 'images': images}, indent=2) + '\n')
PY
date -u +%Y-%m-%dT%H:%M:%SZ > "$payload/capture-finished-at.txt"
printf '%s\n' 'CONSISTENCY=per_database_snapshot_and_live_file_capture' \
  'NOT_VERIFIED=global_atomic_snapshot,object_versions_and_policies,offsite_recovery,restore' > "$payload/backup-scope.txt"
(cd "$payload" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256)
(cd "$payload" && sha256sum --check --status MANIFEST.sha256)

# An interrupted encrypted file retains .pending and is never reported accepted.
phase=encryption
tar -C "$payload" -czf - . 2> "$work/private-command.log" \
  | KAIROS_BACKUP_PASSPHRASE="$passphrase" openssl enc -aes-256-cbc -salt -pbkdf2 -iter 300000 \
      -pass env:KAIROS_BACKUP_PASSPHRASE -out "$pending" 2>> "$work/private-command.log"
[[ -s $pending ]] || die 'encrypted archive missing or empty'
hash=$(sha256sum "$pending" | cut -d ' ' -f 1)
phase=checksum_and_publish
printf '%s  %s\n' "$hash" "$pending" > "$work/pending.sha256"
sha256sum --check --status "$work/pending.sha256"
printf '%s  %s\n' "$hash" "$archive" > "$checksum_pending"
chmod 0600 "$pending" "$checksum_pending"
# Publish checksum first: archive discovery cannot accept a file lacking its pair.
mv -T --no-clobber -- "$checksum_pending" "$archive.sha256"
mv -T --no-clobber -- "$pending" "$archive"
[[ -s $archive && -s $archive.sha256 ]] || die 'final archive pair missing'
sha256sum --check --status "$archive.sha256"
[[ $(stat -c '%u:%a' "$archive") == 0:600 && $(stat -c '%u:%a' "$archive.sha256") == 0:600 ]] || die 'unexpected archive ownership or mode'
phase=complete
# Cleanup emits PASS only after removing the owned temporary reader and plaintext.
