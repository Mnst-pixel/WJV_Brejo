#!/usr/bin/env bash
set -Eeuo pipefail

compose_dir=/opt/kairos/current/infra/compose
secret_file=/opt/kairos/secrets/.env
report_dir=/srv/kairos/observability
backup_root=/srv/kairos/backups
install -d -o root -g root -m 0750 "$report_dir"
exec 9>"$report_dir/.health.lock"
flock -n 9 || exit 0

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
tmp="$(mktemp "$report_dir/.health-$stamp.XXXXXX")"
final="$report_dir/health-$stamp.status"
latest_tmp="$report_dir/.latest-$stamp"
status=PASS
alerts=0
trap 'rm -f -- "$tmp" "$latest_tmp"' EXIT

record() { printf '%s=%s\n' "$1" "$2" >> "$tmp"; }
alert() {
  status=FAIL
  alerts=$((alerts + 1))
  printf 'alert.%03d=%s\n' "$alerts" "$1" >> "$tmp"
}
probe() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    record "probe.$name" PASS
  else
    record "probe.$name" FAIL
    alert "probe_failed:$name"
  fi
}

record timestamp_utc "$(date -u +%FT%TZ)"
record git_revision "$(git -C /opt/kairos/current rev-parse HEAD 2>/dev/null || echo unavailable)"
record host_uptime_seconds "$(cut -d. -f1 /proc/uptime)"
record memory_available_kib "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
memory_available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
if [[ "$memory_available" -lt 524288 ]]; then alert "host_memory_available_below_512MiB"; fi
disk_use="$(df -P /srv/kairos | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
record disk_used_percent "$disk_use"
if [[ "$disk_use" -ge 85 ]]; then alert "disk_usage_at_or_above_85_percent"; fi

cd -- "$compose_dir"
compose=(docker compose --project-name kairos --env-file "$secret_file")
if mapfile -t services < <("${compose[@]}" config --services); then
  record compose_service_count "${#services[@]}"
else
  services=()
  alert "compose_config_unavailable"
fi

cids=()
for service in "${services[@]}"; do
  service_cids="$("${compose[@]}" ps -a -q "$service" 2>/dev/null || true)"
  if [[ -z "$service_cids" ]]; then
    record "service.$service.state" missing
    alert "service_missing:$service"
    continue
  fi
  while IFS= read -r cid; do
    [[ -n "$cid" ]] || continue
    cids+=("$cid")
    state="$(docker inspect --format '{{.State.Status}}' "$cid")"
    exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$cid")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    oom="$(docker inspect --format '{{.State.OOMKilled}}' "$cid")"
    restarts="$(docker inspect --format '{{.RestartCount}}' "$cid")"
    record "service.$service.state" "$state"
    record "service.$service.health" "$health"
    record "service.$service.restarts" "$restarts"
    record "service.$service.oom_killed" "$oom"
    case "$service" in
      minio-init|wordpress-bootstrap|hermes-bootstrap)
        if [[ "$state" != running && !( "$state" == exited && "$exit_code" == 0 ) ]]; then
          alert "oneshot_not_successful:$service:$state:$exit_code"
        fi
        ;;
      *)
        if [[ "$state" != running ]]; then alert "service_not_running:$service:$state"; fi
        ;;
    esac
    if [[ "$health" == unhealthy || "$health" == starting ]]; then alert "service_health:$service:$health"; fi
    if [[ "$oom" == true ]]; then alert "oom_killed:$service"; fi
    if [[ "$restarts" -ge 3 ]]; then alert "crash_loop_suspected:$service:$restarts"; fi
  done <<< "$service_cids"
done

if [[ ${#cids[@]} -gt 0 ]]; then
  printf 'docker_stats_begin\n' >> "$tmp"
  docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.PIDs}}' "${cids[@]}" >> "$tmp" 2>/dev/null || alert "docker_stats_unavailable"
  printf 'docker_stats_end\n' >> "$tmp"
fi

probe edge curl -fsS --max-time 8 http://127.0.0.1:4080/healthz
probe api curl -fsS --max-time 8 http://127.0.0.1:4080/api/health/live
probe web curl -fsS --max-time 8 http://127.0.0.1:4080/app/api/health
probe wordpress curl -fsS --max-time 8 http://127.0.0.1:4080/
probe postgres "${compose[@]}" exec -T postgres sh -ec 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
probe redis "${compose[@]}" exec -T redis sh -ec 'test "$(redis-cli -a "$REDIS_PASSWORD" --no-auth-warning PING)" = PONG'
probe mariadb "${compose[@]}" exec -T mariadb healthcheck.sh --connect --innodb_initialized
probe minio "${compose[@]}" exec -T minio curl -fsS http://127.0.0.1:9000/minio/health/live
probe worker timeout 20 "${compose[@]}" exec -T worker celery -A kairos inspect ping --timeout=5

queue_depth="$("${compose[@]}" exec -T redis sh -ec 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning LLEN celery' 2>/dev/null | tr -d '\r' || echo unavailable)"
record celery_queue_depth "$queue_depth"
if [[ "$queue_depth" =~ ^[0-9]+$ ]] && [[ "$queue_depth" -ge 100 ]]; then alert "celery_queue_at_or_above_100"; fi
if [[ "$queue_depth" == unavailable ]]; then alert "celery_queue_unavailable"; fi

failed_ingestions="$("${compose[@]}" exec -T api python manage.py shell -c 'from datetime import timedelta; from django.db.models import Q; from django.utils import timezone; from core.models import IngestionRun; print(IngestionRun.objects.filter(updated_at__gte=timezone.now()-timedelta(days=1)).filter(Q(status__iexact="failed")|Q(failed_count__gt=0)).count())' 2>/dev/null | tail -n1 | tr -d '\r' || echo unavailable)"
record failed_ingestions_24h "$failed_ingestions"
if [[ "$failed_ingestions" =~ ^[0-9]+$ ]] && [[ "$failed_ingestions" -gt 0 ]]; then alert "corpus_update_failed_in_last_24h"; fi
if [[ "$failed_ingestions" == unavailable ]]; then alert "corpus_status_unavailable"; fi

latest_backup="$(find "$backup_root" -maxdepth 1 -type f -name 'kairos-*.tar.gz.enc' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2- || true)"
if [[ -z "$latest_backup" ]]; then
  record backup_latest none
  alert "backup_missing"
else
  backup_age="$(( $(date +%s) - $(stat -c %Y "$latest_backup") ))"
  record backup_latest "$(basename "$latest_backup")"
  record backup_age_seconds "$backup_age"
  if [[ "$backup_age" -gt 129600 ]]; then alert "backup_older_than_36h"; fi
fi
backup_result="$(systemctl show kairos-backup.service --property=Result --value 2>/dev/null || echo unavailable)"
record backup_unit_result "${backup_result:-unknown}"
if [[ "$backup_result" == failed ]]; then alert "backup_unit_failed"; fi

record alert_count "$alerts"
record status "$status"
chmod 0640 "$tmp"
mv -- "$tmp" "$final"
cp -- "$final" "$latest_tmp"
mv -- "$latest_tmp" "$report_dir/latest.status"
find "$report_dir" -maxdepth 1 -type f -name 'health-*.status' -mtime +30 -delete
trap - EXIT
if [[ "$status" != PASS ]]; then
  echo "KAIROS_HEALTH=FAIL alerts=$alerts report=$final" >&2
  exit 1
fi
echo "KAIROS_HEALTH=PASS report=$final"
