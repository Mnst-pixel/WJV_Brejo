#!/bin/sh
set -eu

mc alias set kairos http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing kairos/documents
mc anonymous set none kairos/documents

mc admin user add kairos "$MINIO_APP_USER" "$MINIO_APP_PASSWORD" 2>/dev/null || \
  mc admin user enable kairos "$MINIO_APP_USER"
mc admin policy create kairos kairos-documents /policy.json >/dev/null
mc admin policy attach kairos kairos-documents --user "$MINIO_APP_USER" >/dev/null

echo "MINIO_BOOTSTRAP=PASS"
