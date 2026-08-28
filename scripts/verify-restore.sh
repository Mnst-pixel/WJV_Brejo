#!/usr/bin/env bash
set -Eeuo pipefail

compose_dir=/opt/kairos/current/infra/compose
secret_file=/opt/kairos/secrets/.env
backup_root=/srv/kairos/backups
archive="${1:---latest}"
if [[ "$archive" == --latest ]]; then
  archive="$(find "$backup_root" -maxdepth 1 -type f -name 'kairos-*.tar.gz.enc' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
fi
archive="$(realpath -e -- "$archive")"
case "$archive" in "$backup_root"/kairos-*.tar.gz.enc) ;; *) echo "invalid backup path" >&2; exit 65 ;; esac
sha256sum --check --status "$archive.sha256"
passphrase="$(sed -n 's/^BACKUP_ENCRYPTION_PASSPHRASE=//p' "$secret_file")"
[[ ${#passphrase} -ge 32 ]]
stamp="$(date -u +%Y%m%d%H%M%S)"
restore_dir="$backup_root/.restore-$stamp"
pg_db="kairos_restore_$stamp"
my_db="kairos_restore_$stamp"
bucket="kairos-restore-$stamp"
install -d -o root -g root -m 0700 "$restore_dir"
cleanup() {
  cd -- "$compose_dir"
  docker compose --env-file "$secret_file" exec -T postgres sh -ec "dropdb -U \"\$POSTGRES_USER\" --if-exists '$pg_db'" >/dev/null 2>&1 || true
  docker compose --env-file "$secret_file" exec -T mariadb sh -ec "mariadb --user=root --password=\"\$MARIADB_ROOT_PASSWORD\" -e 'DROP DATABASE IF EXISTS $my_db'" >/dev/null 2>&1 || true
  docker run --rm --network kairos-data --env-file "$secret_file" --entrypoint /bin/sh minio/mc:RELEASE.2025-08-13T08-35-41Z -ec \
    "mc alias set kairos http://minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null; mc rm --recursive --force kairos/$bucket >/dev/null 2>&1 || true; mc rb --force kairos/$bucket >/dev/null 2>&1 || true" || true
  [[ "$restore_dir" == "$backup_root"/.restore-* ]] && rm -rf -- "$restore_dir"
}
trap cleanup EXIT

KAIROS_BACKUP_PASSPHRASE="$passphrase" openssl enc -d -aes-256-cbc -pbkdf2 -iter 300000 \
  -pass env:KAIROS_BACKUP_PASSPHRASE -in "$archive" | tar -C "$restore_dir" -xzf -
(cd "$restore_dir" && sha256sum --check --status MANIFEST.sha256)
tar -tf "$restore_dir/wordpress.tar" >/dev/null
tar -tf "$restore_dir/hermes.tar" >/dev/null

cd -- "$compose_dir"
docker compose --env-file "$secret_file" exec -T postgres sh -ec "createdb -U \"\$POSTGRES_USER\" '$pg_db'"
docker compose --env-file "$secret_file" exec -T postgres sh -ec "pg_restore -U \"\$POSTGRES_USER\" -d '$pg_db' --exit-on-error" \
  < "$restore_dir/postgres.dump"
docker compose --env-file "$secret_file" exec -T postgres sh -ec "psql -U \"\$POSTGRES_USER\" -d '$pg_db' -v ON_ERROR_STOP=1 -Atc 'SELECT count(*) FROM django_migrations'" \
  | grep -Eq '^[1-9][0-9]*$'

docker compose --env-file "$secret_file" exec -T mariadb sh -ec \
  "mariadb --user=root --password=\"\$MARIADB_ROOT_PASSWORD\" -e 'CREATE DATABASE $my_db'"
docker compose --env-file "$secret_file" exec -T mariadb sh -ec \
  "mariadb --user=root --password=\"\$MARIADB_ROOT_PASSWORD\" '$my_db'" < "$restore_dir/mariadb.sql"
docker compose --env-file "$secret_file" exec -T mariadb sh -ec \
  "mariadb --user=root --password=\"\$MARIADB_ROOT_PASSWORD\" -N '$my_db' -e 'SELECT COUNT(*) FROM wp_options'" \
  | grep -Eq '^[1-9][0-9]*$'

docker run --rm --network kairos-data --env-file "$secret_file" \
  --volume "$restore_dir/minio-documents:/restore:ro" --entrypoint /bin/sh \
  minio/mc:RELEASE.2025-08-13T08-35-41Z -ec \
  "mc alias set kairos http://minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null; mc mb kairos/$bucket >/dev/null; mc mirror /restore kairos/$bucket; test \"\$(mc ls --recursive kairos/$bucket | wc -l)\" -ge 0"

echo "KAIROS_RESTORE_VERIFY=PASS archive=$archive"
