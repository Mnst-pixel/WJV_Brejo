"""Controlled API-only release. Prepare first; apply requires exact evidence.

Usage: python3 deploy-api-p0.py prepare|apply RUN_DIR RESTORE_EVIDENCE INTEGRATION_EVIDENCE
All inputs must remain in protected Kairós runtime/backup directories.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def protected(path, parent):
    resolved = Path(path).resolve(strict=True)
    require(resolved.is_relative_to(parent), "Evidence outside approved namespace")
    require(resolved.stat().st_uid == 0 and not resolved.stat().st_mode & 0o022, "Evidence ownership/mode invalid")
    return resolved


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def release():
    require(os.geteuid() == 0 and len(sys.argv) == 5, "Root and four arguments required")
    mode, run_arg, restore_arg, integration_arg = sys.argv[1:]
    require(mode in {"prepare", "apply"}, "Mode must be prepare or apply")
    os.umask(0o077)
    run = protected(run_arg, Path("/opt/kairos/runtime/p0"))
    restored = protected(restore_arg, Path("/srv/kairos/backups"))
    tested = protected(integration_arg, Path("/opt/kairos/runtime/tests"))
    source = run / "source"
    compose_file = Path("/opt/kairos/current/infra/compose/compose.yaml")
    override = source / "infra/compose/p0-api.override.yaml"
    build = values(run / "build-result.txt")
    old_image, candidate = build["base_image"], build["candidate_image"]
    for identifier in (old_image, candidate):
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", identifier), "Invalid image ID")
    require(re.fullmatch(r"[0-9a-f]{40}", build["source_revision"]), "Invalid source revision")
    restore = values(restored / "result.txt")
    for key in ("checksum", "manifest", "postgres_restore", "mariadb_restore", "minio_restore_and_hashes"):
        require(restore.get(key) == "PASS", "Restore gate incomplete")
    require(restore.get("exit_status") == "0" and restore.get("cleanup_failed") == "0", "Restore or cleanup failed")
    archive_name = restore["archive"]
    require(re.fullmatch(r"kairos-predeploy-[0-9TZ]+-[0-9a-f]+\.tar\.gz\.enc", archive_name), "A new predeploy backup is required")
    archive = protected(Path("/srv/kairos/backups") / archive_name, Path("/srv/kairos/backups"))
    require(0 <= time.time() - archive.stat().st_mtime < 3600, "Predeploy backup older than one hour")
    backup_hash = digest(archive)
    require(archive.with_name(archive.name + ".sha256").read_text().split()[0] == backup_hash, "Backup checksum mismatch")
    result = values(tested / "result.txt")
    require(result.get("test_exit") == "0" and result.get("cleanup_failed") == "0", "Integration or cleanup failed")
    require(result.get("artifact_code_hashes") == "PASS" and result.get("gunicorn_smoke") == "PASS", "Artifact gates missing")
    require(values(tested / "images.txt")["api"] == candidate, "Integration tested a different image")
    cases = ET.parse(tested / "results/integration.xml").findall(".//testcase")
    require(len(cases) >= 48 and all(not list(case) for case in cases), "Full candidate suite did not pass without skips")

    log_path = run / "deploy-private.log"

    def execute(args, environment=None, timeout=180):
        completed = subprocess.run(args, env=environment, text=True, capture_output=True, timeout=timeout, check=False)
        if completed.returncode:
            with log_path.open("a") as log:
                log.write(completed.stdout + completed.stderr)
            raise RuntimeError("Command failed; protected diagnostic retained")
        return completed.stdout.strip()

    compose = ["docker", "compose", "--project-name", "kairos", "--env-file", "/opt/kairos/secrets/.env", "-f", str(compose_file)]

    def configured(image):
        return {**os.environ, "COMPOSE_PROJECT_NAME": "kairos", "KAIROS_P0_API_IMAGE": image}

    require(execute(["docker", "container", "inspect", "-f", "{{.Image}}", "kairos-api-1"]) == old_image, "Production API changed after build")
    original = json.loads(execute(compose + ["config", "--format", "json"]))
    proposed = json.loads(execute(compose + ["-f", str(override), "config", "--format", "json"], configured(candidate)))
    for value in (original, proposed):
        for field in ("image", "entrypoint", "command"):
            value["services"]["api"].pop(field, None)
    require(original == proposed, "Compose changes extend beyond API image/entrypoint/command")
    expected_hashes = {name: digest(source / "apps/api" / name) for name in ("core/mfa.py", "core/views.py", "core/serializers.py", "kairos/settings.py")}
    plan = {
        "scope": "api only; no migrations or bootstrap",
        "source_revision": build["source_revision"], "old_image": old_image, "candidate_image": candidate,
        "production_checkout": execute(["git", "-C", "/opt/kairos/current", "rev-parse", "HEAD"]),
        "compose_sha256": digest(compose_file), "override_sha256": digest(override),
        "backup": str(archive), "backup_sha256": backup_hash, "restore_evidence": str(restored),
        "integration_evidence": str(tested), "source_hashes": expected_hashes,
    }
    require(not execute(["git", "-C", "/opt/kairos/current", "status", "--porcelain"]), "Production checkout is not clean")
    plan_path = run / "deploy-plan.json"
    if mode == "prepare":
        require(not plan_path.exists(), "Plan already exists; inspect it before retrying")
        plan_path.write_text(json.dumps(plan, indent=2) + "\n")
        print(json.dumps(plan, indent=2))
        return
    require(json.loads(plan_path.read_text()) == plan, "Prepared release no longer matches current state")
    before = f"/opt/kairos/runtime/baselines/p0-deploy-{run.name}-before"
    after = f"/opt/kairos/runtime/baselines/p0-deploy-{run.name}-after"
    require(not Path(before).exists() and not Path(after).exists(), "Deploy snapshots already exist")
    execute(["bash", str(source / "scripts/vps-snapshot.sh"), before])

    def apply(image):
        execute(compose + ["-f", str(override), "up", "-d", "--no-deps", "--no-build", "api"], configured(image))
        for _ in range(45):
            state = execute(["docker", "container", "inspect", "-f", "{{.State.Health.Status}}", "kairos-api-1"])
            if state == "healthy":
                return
            time.sleep(2)
        raise RuntimeError("API failed to become healthy")

    def smoke():
        base = "https://kairos.2-24-215-183.sslip.io"
        for path in ("/api/health/live", "/api/health/ready"):
            with urlopen(base + path, timeout=10) as response:
                require(response.status == 200, "Public health check failed")
        try:
            urlopen(Request(base + "/api/auth/login", data=b"{}", headers={"Content-Type": "application/json"}), timeout=10)
        except HTTPError as error:
            require(error.code == 403, "Public CSRF check failed")
        else:
            raise RuntimeError("Login accepted a write without CSRF")

    def compare(snapshot, filename):
        execute(["bash", str(source / "scripts/vps-snapshot.sh"), snapshot])
        output = execute(["bash", str(source / "scripts/compare-vps-snapshots.sh"), before, snapshot])
        (run / filename).write_text(output + "\n")

    outcome = {"deployed": False, "rolled_back": False, "no_touch": False, "rollback_failed": False}
    try:
        apply(candidate)
        smoke()
        check = "import hashlib,json,pathlib; names=" + repr(tuple(expected_hashes)) + "; print(json.dumps({n:hashlib.sha256((pathlib.Path('/app')/n).read_bytes()).hexdigest() for n in names}))"
        observed = json.loads(execute(["docker", "exec", "kairos-api-1", "python", "-c", check]))
        require(observed == expected_hashes, "Live source hashes do not match release")
        compare(after, "deploy-no-touch.txt")
        outcome["no_touch"] = True
        outcome["deployed"] = True
    except Exception:
        try:
            apply(old_image)
            # The old API lacks CSRF protection; rollback checks availability only.
            with urlopen("https://kairos.2-24-215-183.sslip.io/api/health/ready", timeout=10) as response:
                require(response.status == 200, "Rollback readiness failed")
            outcome["rolled_back"] = True
        except Exception:
            outcome["rollback_failed"] = True
        try:
            # Never repair another project's resources to make this gate pass.
            compare(after + "-rollback", "rollback-no-touch.txt")
            outcome["no_touch"] = True
        except Exception:
            outcome["no_touch"] = False
    finally:
        try:
            outcome["observed_image"] = execute(["docker", "container", "inspect", "-f", "{{.Image}}", "kairos-api-1"])
        except Exception:
            outcome["observed_image"] = "unavailable"
        (run / "deploy-result.json").write_text(json.dumps(outcome, indent=2) + "\n")
    print(json.dumps(outcome))
    require(outcome["deployed"] and outcome["no_touch"], "Release did not pass all deployment gates")


def main():
    import fcntl

    require(os.geteuid() == 0, "Root required")
    lock_path = Path("/opt/kairos/runtime/p0/.deploy-api.lock")
    require(not lock_path.is_symlink(), "Unsafe deployment lock path")
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        release()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"KAIROS_DEPLOY=FAIL reason={error}", file=sys.stderr)
        sys.exit(1)
