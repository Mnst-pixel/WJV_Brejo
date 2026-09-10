#!/usr/bin/env python3
"""Catalogued, recoverability-gated backup routine. Python standard library only."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid


ARCHIVE_RE = re.compile(r"kairos-predeploy-\d{8}T\d{6}Z-[a-f0-9]{12}\.tar\.gz\.enc")
DEFAULTS = {
    "checkout": "/opt/kairos/current",
    "backup_root": "/srv/kairos/backups",
    "state_dir": "/opt/kairos/runtime/backup",
    "secret_file": "/opt/kairos/secrets/.env",
    "offhost_config": "/opt/kairos/secrets/backup-offhost.json",
    "lock_file": "/opt/kairos/runtime/.operation.lock",
    "snapshot_root": "/opt/kairos/runtime/baselines",
    "retention_days": 14,
    "minimum_valid_backups": 3,
    "command_timeout_seconds": 7200,
    "minimum_free_disk_bytes": 10 * 1024**3,
    "minimum_available_memory_bytes": 1024**3,
}


class RoutineError(Exception):
    pass


def private_file(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise RoutineError("protected_file_permissions")
    if hasattr(os, "getuid") and info.st_uid != 0:
        raise RoutineError("protected_file_owner")
    return path


def atomic_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_passphrase(path):
    values = []
    for line in private_file(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if key.strip() != "BACKUP_ENCRYPTION_PASSPHRASE":
            continue
        if not separator:
            raise RoutineError("invalid_passphrase_configuration")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values.append(value)
    if len(values) != 1 or len(values[0]) < 32 or any(ord(c) < 32 for c in values[0]):
        raise RoutineError("invalid_passphrase_configuration")
    return values[0]


@contextlib.contextmanager
def operation_lock(path):
    import fcntl

    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RoutineError("invalid_operation_lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RoutineError("operation_already_running") from exc
        yield
    finally:
        os.close(descriptor)


def run_command(command, log, timeout):
    """Keep private command diagnostics off stdout; terminate the complete process group."""
    with open(log, "xb") as stream:
        os.chmod(log, 0o600)
        process = subprocess.Popen(
            command, stdout=stream, stderr=stream, start_new_session=True
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise RoutineError("command_timeout") from None
    if code:
        raise RoutineError("command_failed")
    if Path(log).stat().st_size > 2 * 1024 * 1024:
        raise RoutineError("command_output_limit")
    return Path(log).read_text(encoding="utf-8", errors="replace")


def archive_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(root, name, expected=None):
    if not ARCHIVE_RE.fullmatch(name):
        raise RoutineError("invalid_archive_name")
    path = Path(root) / name
    private_file(path)
    if path.resolve().parent != Path(root).resolve() or path.stat().st_size == 0:
        raise RoutineError("invalid_archive_path")
    checksum = private_file(str(path) + ".sha256").read_text(encoding="ascii").strip()
    fields = checksum.split(maxsplit=1)
    if len(fields) != 2 or fields[1].lstrip("*") != str(path):
        raise RoutineError("invalid_checksum_path")
    digest = archive_hash(path)
    if fields[0] != digest or (expected and digest != expected):
        raise RoutineError("checksum_mismatch")
    return path, digest


def retained_catalog(config, catalog, now):
    """Only delete verified pairs created by this routine; never enumerate historical backups."""
    entries = catalog["backups"]
    valid = sorted(
        (row for row in entries if row.get("restore") == "PASS"),
        key=lambda row: row["verified_at"],
    )
    protected = {row["archive"] for row in valid[-config["minimum_valid_backups"] :]}
    for row in valid[-config["minimum_valid_backups"] :]:
        verify_archive(config["backup_root"], row["archive"], row["sha256"])
    cutoff = now - config["retention_days"] * 86400
    kept = []
    deleted = []
    for row in entries:
        eligible = (
            row.get("managed_by") == "kairos-backup-routine-v1"
            and row.get("restore") == "PASS"
            and row["archive"] not in protected
            and row["verified_at"] < cutoff
        )
        if not eligible:
            kept.append(row)
            continue
        path = Path(config["backup_root"]) / row["archive"]
        if not ARCHIVE_RE.fullmatch(row["archive"]):
            raise RoutineError("invalid_catalog_archive")
        if not path.exists() and not path.is_symlink():
            # Recover a previous interruption between pair deletion and catalog commit.
            checksum = Path(str(path) + ".sha256")
            if checksum.exists() or checksum.is_symlink():
                private_file(checksum)
                checksum.unlink()
            deleted.append(row["archive"])
            continue
        path, _ = verify_archive(config["backup_root"], row["archive"], row["sha256"])
        # Under the shared lock, preserve the checksum if deleting the archive fails.
        path.unlink()
        Path(str(path) + ".sha256").unlink()
        deleted.append(row["archive"])
    return {"version": 1, "backups": kept}, deleted


def execute(config, runner=run_command, now=None):
    """Caller must hold the shared operation lock. Dependency injection is for isolated tests."""
    if runner is run_command:
        validate_operational_paths(config)
    started = int(time.time() if now is None else now)
    state_dir = Path(config["state_dir"])
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state_dir.is_symlink():
        raise RoutineError("invalid_state_directory")
    os.chmod(state_dir, 0o700)
    run_id = (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(started))
        + "-"
        + uuid.uuid4().hex[:12]
    )
    run_dir = state_dir / run_id
    run_dir.mkdir(mode=0o700)
    status = {
        "version": 1,
        "run_id": run_id,
        "started_at": started,
        "local": "RUNNING",
        "offhost": "NOT_ATTEMPTED",
    }
    phase = "baseline_before"
    before = Path(config["snapshot_root"]) / ("backup-" + run_id + "-before")
    after = Path(config["snapshot_root"]) / ("backup-" + run_id + "-after")
    before_completed = False
    after_attempted = False
    atomic_json(state_dir / "status.json", status)
    try:
        scripts = Path(config["checkout"]) / "scripts"
        runner(
            ["bash", str(scripts / "vps-snapshot.sh"), str(before)],
            run_dir / "before.log",
            config["command_timeout_seconds"],
        )
        before_completed = True
        phase = "backup"
        output = runner(
            ["bash", str(scripts / "backup-predeploy.sh")],
            run_dir / "backup.log",
            config["command_timeout_seconds"],
        )
        matches = re.findall(
            r"^KAIROS_PREDEPLOY_BACKUP=PASS scope=archive_created archive=(.+)$",
            output,
            re.MULTILINE,
        )
        if len(matches) != 1 or Path(matches[0]).parent != Path(config["backup_root"]):
            raise RoutineError("backup_evidence_missing")
        archive, digest = verify_archive(config["backup_root"], Path(matches[0]).name)
        status.update(archive=archive.name, sha256=digest)
        phase = "restore"
        passfile = run_dir / "restore-passphrase"
        try:
            descriptor = os.open(passfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(read_passphrase(config["secret_file"]))
            output = runner(
                [
                    "bash",
                    str(scripts / "verify-restore-isolated.sh"),
                    str(archive),
                    str(passfile),
                ],
                run_dir / "restore.log",
                config["command_timeout_seconds"],
            )
        finally:
            passfile.unlink(missing_ok=True)
        matches = re.findall(
            r"^KAIROS_RESTORE_ISOLATED=PASS scope=archived_data evidence=(.+)$",
            output,
            re.MULTILINE,
        )
        if len(matches) != 1:
            raise RoutineError("restore_evidence_missing")
        evidence = Path(matches[0])
        if evidence.parent != Path(config["backup_root"]) or not re.fullmatch(
            r"kairos-restore-\d{8}T\d{6}Z-[a-f0-9]{12}\.evidence", evidence.name
        ):
            raise RoutineError("invalid_restore_evidence")
        proof = private_file(evidence / "result.txt").read_text(encoding="utf-8")
        required = (
            "archive=" + archive.name,
            "postgres_restore=PASS",
            "mariadb_restore=PASS",
            "minio_restore_and_hashes=PASS",
            "exit_status=0",
            "cleanup_failed=0",
        )
        if not all(value in proof.splitlines() for value in required):
            raise RoutineError("incomplete_restore_evidence")
        verify_archive(config["backup_root"], archive.name, digest)
        phase = "no_touch"
        after_attempted = True
        runner(
            ["bash", str(scripts / "vps-snapshot.sh"), str(after), str(before)],
            run_dir / "after.log",
            config["command_timeout_seconds"],
        )
        runner(
            [
                "bash",
                str(scripts / "compare-vps-snapshots.sh"),
                str(before),
                str(after),
            ],
            run_dir / "no-touch.log",
            config["command_timeout_seconds"],
        )
        status["no_touch"] = "PASS"
        status.update(local="PASS", restore_evidence=str(evidence), verified_at=started)
        phase = "catalog"
        catalog_path = state_dir / "catalog.json"
        catalog = (
            json.loads(private_file(catalog_path).read_text())
            if catalog_path.exists()
            else {"version": 1, "backups": []}
        )
        if catalog.get("version") != 1 or not isinstance(catalog.get("backups"), list):
            raise RoutineError("invalid_catalog")
        if any(row["archive"] == archive.name for row in catalog["backups"]):
            raise RoutineError("duplicate_catalog_archive")
        catalog["backups"].append(
            {
                "managed_by": "kairos-backup-routine-v1",
                "archive": archive.name,
                "sha256": digest,
                "verified_at": started,
                "restore": "PASS",
                "restore_evidence": str(evidence),
            }
        )
        atomic_json(catalog_path, catalog)
        phase = "offhost"
        if not Path(config["offhost_config"]).exists():
            status["offhost"] = "EXTERNAL_BLOCKER"
        else:
            try:
                output = runner(
                    [
                        sys.executable,
                        str(scripts / "backup-offhost.py"),
                        "--config",
                        config["offhost_config"],
                        "--archive",
                        str(archive),
                    ],
                    run_dir / "offhost.log",
                    config["command_timeout_seconds"],
                )
                report = json.loads(output)
                if report.get("status") not in {"PASS", "EXTERNAL_BLOCKER"}:
                    raise RoutineError("offhost_verification_failed")
                status["offhost"] = report["status"]
            except Exception:
                status["offhost"] = "FAIL"
        phase = "retention"
        catalog, deleted = retained_catalog(config, catalog, started)
        atomic_json(catalog_path, catalog)
        status["retention_deleted"] = len(deleted)
        status["result"] = "PASS" if status["offhost"] != "FAIL" else "FAIL"
    except Exception as exc:
        status.update(result="FAIL", failed_phase=phase, error=type(exc).__name__)
        if status["local"] != "PASS":
            status["local"] = "FAIL"
        if before_completed and not after_attempted:
            try:
                runner(
                    ["bash", str(scripts / "vps-snapshot.sh"), str(after), str(before)],
                    run_dir / "after.log",
                    config["command_timeout_seconds"],
                )
                runner(
                    [
                        "bash",
                        str(scripts / "compare-vps-snapshots.sh"),
                        str(before),
                        str(after),
                    ],
                    run_dir / "no-touch.log",
                    config["command_timeout_seconds"],
                )
                status["no_touch"] = "PASS"
            except Exception:
                status["no_touch"] = "FAIL"
        elif phase == "no_touch":
            status["no_touch"] = "FAIL"
    status["finished_at"] = int(time.time())
    status["alert"] = (
        status["result"] == "FAIL" or status["offhost"] == "EXTERNAL_BLOCKER"
    )
    atomic_json(run_dir / "result.json", status)
    atomic_json(state_dir / "status.json", status)
    atomic_json(
        state_dir / "alert.json",
        {
            "active": status["alert"],
            "run_id": run_id,
            "local": status["local"],
            "offhost": status["offhost"],
            "result": status["result"],
        },
    )
    return status


def validate_operational_paths(config):
    """Production path validation precedes every mkdir/chmod/lock/delete operation."""
    for key in ("checkout", "backup_root", "state_dir", "secret_file", "offhost_config", "lock_file", "snapshot_root"):
        value = config[key]
        namespace = "/srv/kairos" if key == "backup_root" else "/opt/kairos"
        if not isinstance(value, str):
            raise RoutineError("invalid_operational_path")
        lexical = PurePosixPath(value)
        if not lexical.is_absolute() or ".." in lexical.parts or str(lexical) != value:
            raise RoutineError("invalid_operational_path")
        if not lexical.is_relative_to(namespace) or str(lexical) == namespace:
            raise RoutineError("path_outside_kairos_namespace")
        resolved = Path(value).resolve(strict=False)
        if not resolved.is_relative_to(Path(namespace).resolve(strict=False)):
            raise RoutineError("resolved_path_outside_kairos_namespace")
        # The namespace root itself may not redirect into a different project's tree.
        if str(Path(namespace).resolve(strict=False)) != namespace:
            raise RoutineError("redirected_kairos_namespace")


def load_config(path=None):
    config = dict(DEFAULTS)
    if path:
        supplied = json.loads(private_file(path).read_text(encoding="utf-8"))
        if not isinstance(supplied, dict) or supplied.keys() - config.keys():
            raise RoutineError("invalid_configuration_keys")
        config.update(supplied)
    for key in (
        "checkout",
        "backup_root",
        "state_dir",
        "secret_file",
        "offhost_config",
        "lock_file",
        "snapshot_root",
    ):
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise RoutineError("absolute_paths_required")
    for key, lower, upper in (
        ("retention_days", 1, 3650),
        ("minimum_valid_backups", 2, 1000),
        ("command_timeout_seconds", 60, 14400),
    ):
        if type(config[key]) is not int or not lower <= config[key] <= upper:
            raise RoutineError("invalid_configuration_limits")
    for key in ("minimum_free_disk_bytes", "minimum_available_memory_bytes"):
        if type(config[key]) is not int or config[key] < 1024**3:
            raise RoutineError("invalid_capacity_limit")
    validate_operational_paths(config)
    return config


def check_capacity(config):
    if (
        shutil.disk_usage(config["backup_root"]).free
        < config["minimum_free_disk_bytes"]
    ):
        raise RoutineError("insufficient_disk_headroom")
    memory = Path("/proc/meminfo").read_text(encoding="ascii")
    available = re.search(r"^MemAvailable:\s+(\d+) kB$", memory, re.MULTILINE)
    if (
        not available
        or int(available[1]) * 1024 < config["minimum_available_memory_bytes"]
    ):
        raise RoutineError("insufficient_memory_headroom")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", help="Optional root:root 0600 JSON operational configuration"
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if os.geteuid() != 0:
            raise RoutineError("root_required")
        config = load_config(args.config)
        with operation_lock(config["lock_file"]):
            check_capacity(config)
            status = execute(config)
        print(json.dumps(status, sort_keys=True))
        return 0 if status["result"] == "PASS" else 1
    except Exception as exc:
        # Do not overwrite the running job's status when lock acquisition fails.
        print(
            json.dumps(
                {"result": "FAIL", "phase": "startup", "error": type(exc).__name__}
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
