#!/usr/bin/env bash
set -Eeuo pipefail
exec /usr/bin/python3 /opt/kairos/current/scripts/health-report.py "$@"
