#!/bin/sh
set -eu

mode="${1:-api}"

case "$mode" in
  api)
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
  beat)
    exec celery -A kairos beat --loglevel=INFO --schedule=/tmp/kairos-celerybeat
    ;;
  migrate)
    exec python manage.py migrate --noinput
    ;;
  *)
    echo 'Unsupported runtime mode; use api, worker or explicit migrate job.' >&2
    exit 64
    ;;
esac
