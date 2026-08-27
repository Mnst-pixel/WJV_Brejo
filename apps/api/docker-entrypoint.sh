#!/bin/sh
set -eu

mode="${1:-api}"

case "$mode" in
  api)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    python manage.py bootstrap_roles
    python manage.py bootstrap_admin
    exec gunicorn kairos.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-2}" \
      --threads "${GUNICORN_THREADS:-2}" \
      --timeout 60 \
      --access-logfile - \
      --error-logfile -
    ;;
  worker)
    exec celery -A kairos worker --loglevel="${KAIROS_LOG_LEVEL:-INFO}" --concurrency="${CELERY_CONCURRENCY:-1}"
    ;;
  *)
    exec "$@"
    ;;
esac
