#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' 'KAIROS_RESTORE_VERIFY=FAIL reason=deprecated_entrypoint use=verify-restore-isolated.sh_with_exact_archive_and_private_passphrase_file' >&2
exit 64
