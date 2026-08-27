#!/usr/bin/env bash
set -Eeuo pipefail

compose_dir=/opt/kairos/current/infra/compose
secret_file=/opt/kairos/secrets/.env
backup_root=/srv/kairos/backups
[[ "$(realpath -m -- "$backup_root")" == /srv/kairos/backups ]]
[[ -r "$secret_file" ]]
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
stage="$backup_root/.stage-$stamp"
archive="$backup_root/kairos-$stamp.tar.gz.enc"
passphrase="$(sed -n 's/^BACKUP_ENCRYPTION_PASSPHRASE=//p' "$secret_file")"
[[ ${#passphrase} -ge 32 ]]
install -d -o root -g root -m 0700 "$stage"
cleanup() { [[ "$stage" == "$backup_root"/.stage-* ]] && rm -rf -- "$stage"; }
trap cleanup EXIT

cd -- "$compose_dir"
docker compose --env-file "$secret_file" exec -T postgres \
  sh -ec 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$stage/postgres.dump"
docker compose --env-file "$secret_file" exec -T mariadb \
  sh -ec 'exec mariadb-dump --single-transaction --routines --events --user="$MARIADB_USER" --password="$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
  > "$stage/mariadb.sql"

install -d -m 0700 "$stage/minio-documents"
docker run --rm --network kairos-data --env-file "$secret_file" \
  --volume "$stage/minio-documents:/backup" --entrypoint /bin/sh \
  minio/mc:RELEASE.2025-08-13T08-35-41Z -ec \
  'mc alias set kairos http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc mirror --overwrite kairos/documents /backup'

tar -C /srv/kairos/wordpress --one-file-system -cf "$stage/wordpress.tar" .
tar -C /srv/kairos/hermes --one-file-system -cf "$stage/hermes.tar" .
install -m 0600 "$secret_file" "$stage/secrets.env"
git -C /opt/kairos/current rev-parse HEAD > "$stage/git-revision.txt"
(cd "$stage" && find . -type f ! -name MANIFEST.sha256 -print0 \
  | sort -z | xargs -0 sha256sum > MANIFEST.sha256)

tar -C "$stage" -czf - . \
  | KAIROS_BACKUP_PASSPHRASE="$passphrase" openssl enc -aes-256-cbc -salt -pbkdf2 -iter 300000 \
      -pass env:KAIROS_BACKUP_PASSPHRASE -out "$archive"
chmod 0600 "$archive"
sha256sum "$archive" > "$archive.sha256"
chmod 0600 "$archive.sha256"
find "$backup_root" -maxdepth 1 -type f -name 'kairos-*.tar.gz.enc' -mtime +14 -delete
find "$backup_root" -maxdepth 1 -type f -name 'kairos-*.tar.gz.enc.sha256' -mtime +14 -delete
echo "KAIROS_BACKUP=PASS archive=$archive"
