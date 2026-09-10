#!/usr/bin/env python3
"""Read-only health evidence for the active Kairós release; no Compose/env fallback."""
import contextlib
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

SERVICES = frozenset("api clamav edge localai mariadb minio postgres redis web wordpress worker migrate parser beat".split())
FIRST_PARTY = frozenset("api web worker migrate parser beat".split())
CONFIG_FILES = ("infra/compose/compose.yaml", "infra/caddy/Caddyfile", "config/service-secrets.json")
UNITS = ("kairos-backup.timer", "kairos-health.timer", "kairos-backup.service", "kairos-health.service")
SHA = re.compile(r"[a-f0-9]{64}")
ARCHIVE = re.compile(r"kairos-predeploy-\d{8}T\d{6}Z-[a-f0-9]{12}\.tar\.gz\.enc")
REPORT = re.compile(r"health-\d{8}T\d{6}Z-[a-f0-9]{12}\.(json|status)")
PUBLIC_HOST = "kairos.2-24-215-183.sslip.io"
MAX_AGE = 36 * 3600


@dataclass(frozen=True)
class Paths:
    checkout: Path = Path("/opt/kairos/current")
    pointer: Path = Path("/opt/kairos/runtime/active-release")
    releases: Path = Path("/opt/kairos/runtime/releases")
    backup_state: Path = Path("/opt/kairos/runtime/backup")
    backups: Path = Path("/srv/kairos/backups")
    reports: Path = Path("/srv/kairos/observability")


class HealthError(Exception):
    """Only fixed reason codes may be put in this exception."""


def protected(path, *, directory=False, private=True):
    path = Path(path)
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid or (hasattr(os, "getuid") and info.st_uid != 0):
        raise HealthError("unsafe_owner_or_type")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o022 or (private and not directory and mode != 0o600):
        raise HealthError("unsafe_permissions")
    if path.resolve() != path.absolute():
        raise HealthError("symlink_path")
    for parent in path.parents:
        parent_info = parent.stat()
        if hasattr(os, "getuid") and (parent_info.st_uid != 0 or parent_info.st_mode & 0o022):
            raise HealthError("unsafe_parent")
    return path


def read_json(path):
    path = protected(path)
    if path.stat().st_size > 1024 * 1024:
        raise HealthError("json_size_limit")
    return json.loads(path.read_text(encoding="utf-8"))


def run(command, timeout=15):
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/root"}
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.DEVNULL, env=env)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise HealthError("command_timeout") from None
        if process.returncode or output.tell() > 1024 * 1024:
            raise HealthError("command_failed_or_output_limit")
        output.seek(0)
        return output.read().decode("utf-8", errors="strict").strip()


def active_release(paths, runner=run):
    pointer = protected(paths.pointer)
    if pointer.stat().st_size > 1024:
        raise HealthError("invalid_release_pointer")
    descriptor = Path(pointer.read_text().strip())
    if not descriptor.is_absolute() or descriptor.parent != paths.releases:
        raise HealthError("invalid_release_namespace")
    protected(descriptor, directory=True)
    protected(paths.checkout, directory=True)
    value = read_json(descriptor / "manifest.json")
    if (value.get("schema") != 1 or not re.fullmatch(r"[a-f0-9]{40}", value.get("commit", ""))
            or set(value.get("images", {})) != SERVICES
            or set(value.get("configuration", {})) != set(CONFIG_FILES)):
        raise HealthError("invalid_release_manifest")
    if any(not re.fullmatch(r"sha256:[a-f0-9]{64}", image) for image in value["images"].values()):
        raise HealthError("invalid_release_image")
    secrets_dir = PurePosixPath(value.get("secrets_dir", ""))
    if not secrets_dir.is_absolute() or not secrets_dir.is_relative_to("/opt/kairos/secrets") or secrets_dir == PurePosixPath("/opt/kairos/secrets") or ".." in secrets_dir.parts:
        raise HealthError("invalid_secret_namespace")
    public = {"COMPOSE_PROJECT_NAME": "kairos", "KAIROS_SECRETS_DIR": str(secrets_dir)}
    public.update({"KAIROS_IMAGE_" + key.upper(): image for key, image in value["images"].items()})
    if protected(descriptor / "release.env").read_text() != "".join(f"{key}={item}\n" for key, item in sorted(public.items())):
        raise HealthError("release_environment_drift")
    if runner(["git", "-C", str(paths.checkout), "rev-parse", "HEAD"]) != value["commit"]:
        raise HealthError("checkout_revision_drift")
    if runner(["git", "-C", str(paths.checkout), "status", "--porcelain", "--untracked-files=normal"]):
        raise HealthError("checkout_not_clean")
    for name, expected in value["configuration"].items():
        source = protected(paths.checkout / name, private=False)
        if not SHA.fullmatch(expected) or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise HealthError("configuration_drift")
    compose = json.loads((paths.checkout / CONFIG_FILES[0]).read_text())
    scopes = json.loads((paths.checkout / CONFIG_FILES[2]).read_text())
    if set(compose["services"]) != SERVICES or set(scopes) - SERVICES:
        raise HealthError("service_scope_drift")
    return value, compose, scopes


PROJECTION = '''{"id":{{json .Id}},"name":{{json .Name}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"managed":{{json (index .Config.Labels "com.kairos.managed")}},"image":{{json .Image}},"state":{{json .State.Status}},"oom":{{json .State.OOMKilled}},"restarts":{{json .RestartCount}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}"none"{{end}}}'''


def containers(value, compose, scopes, runner=run):
    ids = runner(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=kairos", "--no-trunc"]).splitlines()
    if len(ids) > 40 or any(not SHA.fullmatch(item) for item in ids):
        raise HealthError("invalid_container_inventory")
    result, trusted = {}, {}
    for cid in ids:
        row = json.loads(runner(["docker", "inspect", "-f", PROJECTION, cid]))
        service = row.get("service")
        if (row.get("id") != cid or row.get("project") != "kairos" or service not in SERVICES
                or row.get("managed") != "release" or row.get("name") != "/kairos-" + service + "-1"
                or service in result):
            raise HealthError("container_ownership_or_duplicate")
        checks = {"image": row.get("image") == value["images"][service],
                  "running": row.get("state") == "running", "healthy": row.get("health") == "healthy",
                  "no_oom": row.get("oom") is False, "restart_budget": isinstance(row.get("restarts"), int) and row["restarts"] < 3}
        if service in FIRST_PARTY:
            revision = runner(["docker", "image", "inspect", "-f", '{{index .Config.Labels "org.opencontainers.image.revision"}}', value["images"][service]])
            checks["source_revision"] = revision == value["commit"]
        # Only names leave Docker. Credentials are never returned by the template.
        names = runner(["docker", "inspect", "-f", '{{range .Config.Env}}{{index (split . "=") 0}}{{"\\n"}}{{end}}', cid]).splitlines()
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names):
            raise HealthError("invalid_environment_projection")
        allowed = set(scopes.get(service, {})) | set(compose["services"][service].get("environment", {}))
        sensitive = {name for name in names if re.search(r"PASSWORD|SECRET|TOKEN|API_KEY|CREDENTIAL|PRIVATE_KEY", name)}
        checks["credential_scope"] = not (sensitive - allowed)
        if service == "migrate":
            checks["maintenance_absent"] = False
        result[service] = {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
        if all(checks.values()):
            trusted[service] = cid
    for service in sorted(SERVICES - {"migrate"} - result.keys()):
        result[service] = {"status": "FAIL", "reason": "missing"}
    return result, trusted


PROBES = {
    "postgres": ["sh", "-ec", 'exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
    "redis": ["sh", "-ec", 'export REDISCLI_AUTH="$REDIS_PASSWORD"; test "$(redis-cli --no-auth-warning PING)" = PONG'],
    "minio": ["curl", "-fsS", "--max-time", "5", "http://127.0.0.1:9000/minio/health/ready"],
    "mariadb": ["healthcheck.sh", "--connect", "--innodb_initialized"],
    "worker": ["python", "-c", "import socket; from kairos.celery import app; r=app.control.ping(destination=['celery@'+socket.gethostname()], timeout=5); assert len(r)==1 and list(r[0].values())[0].get('ok')=='pong'"],
}


def http_probe(path, connection_factory=http.client.HTTPSConnection):
    conn = connection_factory(PUBLIC_HOST, timeout=8)
    try:
        conn.request("GET", path, headers={"User-Agent": "KairosHealth/1", "Accept": "application/json"})
        response = conn.getresponse()
        body = response.read(65537)
        if response.status != 200:
            raise HealthError("public_http_failed")
        if path == "/api/health/ready":
            if len(body) > 65536:
                raise HealthError("public_output_limit")
            result = json.loads(body)
            if result.get("status") != "ok" or not all(result.get("checks", {}).get(key) is True for key in ("postgres", "redis")):
                raise HealthError("public_readiness_failed")
        return "PASS"
    finally:
        conn.close()


def backup_health(paths, now):
    status = read_json(paths.backup_state / "status.json")
    catalog = read_json(paths.backup_state / "catalog.json")
    running = status.get("local") == "RUNNING"
    if running and not 0 <= now - status.get("started_at", 0) <= 5 * 3600:
        raise HealthError("backup_running_overdue")
    if not running and (status.get("result") != "PASS" or status.get("local") != "PASS" or status.get("no_touch") != "PASS"):
        raise HealthError("backup_last_run_failed")
    if catalog.get("version") != 1 or not isinstance(catalog.get("backups"), list):
        raise HealthError("invalid_backup_catalog")
    rows = [row for row in catalog["backups"] if row.get("restore") == "PASS" and row.get("managed_by") == "kairos-backup-routine-v1"]
    if not rows:
        raise HealthError("restorable_backup_missing")
    row = max(rows, key=lambda item: item.get("verified_at", 0))
    if not running and any(status.get(key) != row.get(key) for key in ("archive", "sha256", "restore_evidence", "verified_at")):
        raise HealthError("backup_status_catalog_mismatch")
    age = now - row.get("verified_at", 0)
    if not 0 <= age <= MAX_AGE:
        raise HealthError("backup_stale_or_future")
    if not ARCHIVE.fullmatch(row.get("archive", "")) or not SHA.fullmatch(row.get("sha256", "")):
        raise HealthError("invalid_backup_reference")
    archive = protected(paths.backups / row["archive"])
    if archive.stat().st_size == 0:
        raise HealthError("backup_empty")
    fields = protected(Path(str(archive) + ".sha256")).read_text().strip().split(maxsplit=1)
    if len(fields) != 2 or fields[0] != row["sha256"] or fields[1].lstrip("*") != str(archive):
        raise HealthError("backup_checksum_reference_mismatch")
    evidence = Path(row.get("restore_evidence", ""))
    if evidence.parent != paths.backups or not re.fullmatch(r"kairos-restore-\d{8}T\d{6}Z-[a-f0-9]{12}\.evidence", evidence.name):
        raise HealthError("invalid_restore_reference")
    lines = protected(evidence / "result.txt").read_text().splitlines()
    required = ("archive=" + archive.name, "postgres_restore=PASS", "mariadb_restore=PASS", "minio_restore_and_hashes=PASS", "exit_status=0", "cleanup_failed=0")
    if not all(line in lines for line in required):
        raise HealthError("restore_proof_incomplete")
    return {"status": "PASS", "age_seconds": age, "archive": archive.name, "sha256": row["sha256"],
            "restore": "PASS", "integrity": "catalog_and_checksum_reference", "full_checksum_at": row["verified_at"],
            "routine_running": running, "offhost": status.get("offhost") if status.get("offhost") in {"PASS", "FAIL", "EXTERNAL_BLOCKER"} else "NOT_ATTEMPTED"}


def unit_health(runner=run):
    result = {}
    for unit in UNITS:
        raw = runner(["systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,Result,UnitFileState,NextElapseUSecRealtime,NextElapseUSecMonotonic,ExecMainStatus"])
        fields = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        ok = fields.get("LoadState") == "loaded"
        if unit.endswith(".timer"):
            ok = ok and fields.get("ActiveState") == "active" and fields.get("UnitFileState") == "enabled" and any(fields.get(key) not in {None, "", "0", "infinity"} for key in ("NextElapseUSecRealtime", "NextElapseUSecMonotonic"))
        elif unit == "kairos-health.service" and fields.get("ActiveState") == "activating":
            # Do not perpetuate a previous failure while this very invocation runs.
            ok = ok and True
        else:
            ok = ok and fields.get("ActiveState") in {"inactive", "active", "activating"} and fields.get("Result") == "success" and fields.get("ExecMainStatus") == "0"
        result[unit] = {"status": "PASS" if ok else "FAIL", "active": fields.get("ActiveState") if fields.get("ActiveState") in {"inactive", "active", "activating", "failed"} else "unknown"}
    # Request metadata only; never MESSAGE, command, SQL, identifiers or log text.
    logs = runner(["journalctl", "--no-pager", "--since=-24h", "--priority=0..3", "-n", "1000", "-o", "json", "--output-fields=__REALTIME_TIMESTAMP,_SYSTEMD_UNIT,UNIT,PRIORITY", "-u", "kairos-backup.service", "-u", "kairos-health.service"])
    count = 0
    for line in logs.splitlines():
        item = json.loads(line)
        if (item.get("_SYSTEMD_UNIT") in UNITS or item.get("UNIT") in UNITS) and str(item.get("PRIORITY")) in {"0", "1", "2", "3"}:
            count += 1
    return {"status": "PASS" if all(row["status"] == "PASS" for row in result.values()) else "FAIL", "units": result, "error_events_24h_capped_1000": count, "log_content": "excluded"}


def collect(paths, runner=run, probe=http_probe, now=None):
    now = int(time.time()) if now is None else now
    report = {"schema": 1, "managed_by": "kairos-health-v1", "timestamp": now, "checks": {}, "warnings": []}

    def check(name, callback):
        try:
            result = callback()
            report["checks"][name] = result if isinstance(result, dict) else {"status": "PASS"}
            return result
        except Exception as exc:
            report["checks"][name] = {"status": "FAIL", "reason": str(exc) if isinstance(exc, HealthError) else type(exc).__name__}
            return None

    release = check("release", lambda: active_release(paths, runner))
    if release:
        value, compose, scopes = release
        report["commit"] = value["commit"]
        found = check("container_inventory", lambda: containers(value, compose, scopes, runner))
        if found:
            service_results, trusted = found
            report["checks"]["container_inventory"] = {"status": "PASS" if all(row["status"] == "PASS" for row in service_results.values()) else "FAIL", "services": service_results}
            for service, command in PROBES.items():
                if service in trusted:
                    check("probe_" + service, lambda service=service, command=command: runner(["docker", "exec", trusted[service], *command], timeout=15))
                else:
                    report["checks"]["probe_" + service] = {"status": "FAIL", "reason": "container_not_trusted"}
    for name, path in {"edge": "/healthz", "api": "/api/health/ready", "web": "/app/api/health", "wordpress": "/"}.items():
        check("public_" + name, lambda path=path: probe(path))
    backup = check("backup", lambda: backup_health(paths, now))
    if backup and backup["offhost"] == "EXTERNAL_BLOCKER":
        report["warnings"].append("offhost_EXTERNAL_BLOCKER")
    check("systemd", lambda: unit_health(runner))
    def capacity():
        usage = shutil.disk_usage(paths.backups)
        memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        available = int(memory["MemAvailable"].strip().split()[0]) * 1024
        return {"status": "PASS" if usage.free / usage.total > .15 and available >= 512 * 1024**2 else "FAIL", "disk_free_bytes": usage.free, "memory_available_bytes": available}
    check("capacity", capacity)
    report["status"] = "PASS" if all(row["status"] == "PASS" for row in report["checks"].values()) else "FAIL"
    report["alert_count"] = sum(row["status"] == "FAIL" for row in report["checks"].values())
    return report


def atomic_write(path, content):
    if path.exists() or path.is_symlink():
        protected(path, private=False)  # Upgrade legacy root-owned 0640 status to 0600.
    fd, temporary = tempfile.mkstemp(prefix=".health-pending-", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(paths, report, now):
    protected(paths.reports, directory=True)
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    stem = "health-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now)) + "-" + digest[:12]
    summary = f"managed_by=kairos-health-v1\ntimestamp={now}\nstatus={report['status']}\nalert_count={report['alert_count']}\nreport={stem}.json\nsha256={digest}\n"
    atomic_write(paths.reports / (stem + ".json"), encoded)
    atomic_write(paths.reports / (stem + ".status"), summary)
    atomic_write(paths.reports / "latest.json", encoded)
    atomic_write(paths.reports / "latest.status", summary)
    for candidate in paths.reports.iterdir():
        if not REPORT.fullmatch(candidate.name) or candidate.suffix != ".json":
            continue
        try:
            previous = read_json(candidate)
            if previous.get("managed_by") != "kairos-health-v1" or not 0 < previous.get("timestamp", now) < now - 30 * 86400:
                continue
            old_digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if not candidate.stem.endswith("-" + old_digest[:12]):
                continue
            sidecar = protected(candidate.with_suffix(".status"))
            lines = sidecar.read_text().splitlines()
            if "managed_by=kairos-health-v1" not in lines or "sha256=" + old_digest not in lines or "report=" + candidate.name not in lines:
                continue
            sidecar.unlink()
            candidate.unlink()
        except (OSError, ValueError, HealthError, TypeError):
            continue


@contextlib.contextmanager
def lock(path):
    import fcntl
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        protected(path, private=False)
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def main():
    try:
        if len(sys.argv) != 1 or os.geteuid() != 0:
            raise HealthError("root_no_arguments_required")
        paths = Paths()
        protected(paths.reports, directory=True)
        with lock(paths.reports / ".health.lock"):
            now = int(time.time())
            result = collect(paths, now=now)
            publish(paths, result, now)
        print(f"KAIROS_HEALTH={result['status']} alerts={result['alert_count']} report=/srv/kairos/observability/latest.json")
        return 0 if result["status"] == "PASS" else 1
    except BlockingIOError:
        print("KAIROS_HEALTH=SKIPPED reason=already_running")
        return 0
    except Exception as exc:
        print("KAIROS_HEALTH=FAIL reason=" + (str(exc) if isinstance(exc, HealthError) else type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
