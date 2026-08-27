#!/usr/bin/env bash
set -Eeuo pipefail

target="${1:-/opt/kairos/secrets/.env}"
target="$(realpath -m -- "$target")"
case "$target" in
  /opt/kairos/secrets/*) ;;
  *) echo "refusing secret output outside /opt/kairos/secrets" >&2; exit 65 ;;
esac

if [[ -e "$target" ]]; then
  echo "refusing to overwrite existing secret file" >&2
  exit 66
fi

umask 077
mkdir -p -- "$(dirname -- "$target")"

secret() { openssl rand -base64 48 | tr -d '\n'; }

{
  echo 'COMPOSE_PROJECT_NAME=kairos'
  echo 'KAIROS_PUBLIC_PORT=4080'
  echo 'KAIROS_BASE_URL=http://2.24.215.183:4080'
  echo 'KAIROS_ALLOWED_HOSTS=2.24.215.183,localhost,127.0.0.1'
  echo 'KAIROS_CORS_ORIGINS=http://2.24.215.183:4080'
  echo 'KAIROS_CSRF_TRUSTED_ORIGINS=http://2.24.215.183:4080'
  echo 'KAIROS_DEBUG=false'
  echo 'KAIROS_LOG_LEVEL=INFO'
  printf 'DJANGO_SECRET_KEY=%s\n' "$(secret)"
  echo 'POSTGRES_DB=kairos'
  echo 'POSTGRES_USER=kairos_app'
  printf 'POSTGRES_PASSWORD=%s\n' "$(secret)"
  printf 'REDIS_PASSWORD=%s\n' "$(secret)"
  echo 'MINIO_ROOT_USER=kairos_minio'
  printf 'MINIO_ROOT_PASSWORD=%s\n' "$(secret)"
  echo 'MARIADB_DATABASE=kairos_wordpress'
  echo 'MARIADB_USER=kairos_wordpress'
  printf 'MARIADB_PASSWORD=%s\n' "$(secret)"
  printf 'MARIADB_ROOT_PASSWORD=%s\n' "$(secret)"
  echo 'WORDPRESS_ADMIN_USER=vinicius'
  echo 'WORDPRESS_ADMIN_PASSWORD='
  echo 'WORDPRESS_ADMIN_EMAIL='
  printf 'HERMES_BEARER_TOKEN=%s\n' "$(secret)"
  printf 'LOCALAI_API_KEY=%s\n' "$(secret)"
  printf 'GATEWAY_BEARER_TOKEN=%s\n' "$(secret)"
  printf 'MCP_API_KEY=%s\n' "$(secret)"
  echo 'DATAJUD_API_KEY='
  echo 'INLABS_ENABLED=false'
  echo 'INLABS_EMAIL='
  echo 'INLABS_PASSWORD='
  echo 'SMTP_URL='
} > "$target"

chmod 600 -- "$target"
echo "SECRETS_CREATED=$target"
