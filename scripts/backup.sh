#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' 'KAIROS_BACKUP=FAIL reason=deprecated_entrypoint use=systemctl_start_kairos-backup.service' >&2
exit 64
