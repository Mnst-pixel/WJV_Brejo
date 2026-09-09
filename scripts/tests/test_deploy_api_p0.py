"""Independent synthetic deploy review; no Docker, network, or VPS operations."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

TARGET = Path(__file__).resolve().parents[1] / "deploy-api-p0.py"
OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64
NAMES = ("core/mfa.py", "core/views.py", "core/serializers.py", "kairos/settings.py")


def scenario(case):
    spec = importlib.util.spec_from_file_location("reviewed_deploy", TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="kairos-deploy-review-") as td:
        root = Path(td)

        def mapped(value):
            text = str(value)
            if Path(value).is_absolute() and Path(value).is_relative_to(root):
                return Path(value)
            return root / text.lstrip("/") if text.startswith("/") else Path(value)

        run = mapped("/opt/kairos/runtime/p0/review")
        restore = mapped("/srv/kairos/backups/restore-evidence")
        tested = mapped("/opt/kairos/runtime/tests/review")
        for directory in (run, restore, tested / "results"):
            directory.mkdir(parents=True)

        def write(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf8")

        for name in NAMES:
            write(run / "source/apps/api" / name, "synthetic " + name)
        hashes = {
            n: hashlib.sha256((run / "source/apps/api" / n).read_bytes()).hexdigest()
            for n in NAMES
        }
        write(run / "source/infra/compose/p0-api.override.yaml", "synthetic override")
        write(
            mapped("/opt/kairos/current/infra/compose/compose.yaml"),
            "synthetic compose",
        )
        write(
            run / "build-result.txt",
            f"base_image={OLD}\ncandidate_image={NEW}\nsource_revision={'c' * 40}\n",
        )
        archive_name = "kairos-predeploy-20260909T220000Z-aaaaaaaaaaaa.tar.gz.enc"
        archive = mapped("/srv/kairos/backups") / archive_name
        archive.write_bytes(b"synthetic-encrypted-fixture")
        os.utime(archive, (time.time() - 10,) * 2)
        write(
            archive.with_name(archive_name + ".sha256"),
            hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive_name,
        )
        restore_text = "".join(
            n + "=PASS\n"
            for n in (
                "checksum",
                "manifest",
                "postgres_restore",
                "mariadb_restore",
                "minio_restore_and_hashes",
            )
        )
        write(
            restore / "result.txt",
            restore_text + f"exit_status=0\ncleanup_failed=0\narchive={archive_name}\n",
        )
        write(
            tested / "result.txt",
            "test_exit=0\ncleanup_failed=0\nartifact_code_hashes=PASS\ngunicorn_smoke=PASS\nadmin_static_smoke=PASS\n",
        )
        write(tested / "images.txt", "api=" + NEW)
        xml = (
            "<testsuites><testsuite>" + "<testcase/>" * 48 + "</testsuite></testsuites>"
        )
        write(tested / "results/integration.xml", xml)
        state = {"image": OLD, "ups": [], "commands": [], "comparisons": 0}

        def command(args, env=None, **kwargs):
            state["commands"].append(args)
            result, code = "", 0
            if args[:3] == ["docker", "container", "inspect"]:
                if "Health" in args[4]:
                    result = (
                        "unhealthy"
                        if case == "health_failure" and state["image"] == NEW
                        else "healthy"
                    )
                else:
                    result = state["image"]
            elif args[:2] == ["docker", "compose"]:
                if "config" in args:
                    result = {
                        "services": {
                            "api": {
                                "image": (env or {}).get("KAIROS_P0_API_IMAGE", OLD),
                                "command": ["app"],
                                "networks": ["kairos-app"],
                            }
                        }
                    }
                    if case == "scope_change" and env:
                        result["services"]["api"]["networks"].append("unrelated")
                    result = json.dumps(result)
                elif "up" in args:
                    assert args[-5:] == ["-d", "--no-deps", "--no-build", "api"][
                        -5:
                    ] or args[-4:] == ["-d", "--no-deps", "--no-build", "api"]
                    image = env["KAIROS_P0_API_IMAGE"]
                    state["ups"].append(image)
                    if case == "rollback_failure" and image == OLD:
                        code = 1
                    else:
                        state["image"] = image
                    if case == "up_failure" and image == NEW:
                        code = 1
                else:
                    raise AssertionError(args)
            elif args[:2] == ["docker", "exec"]:
                result = json.dumps(
                    {}
                    if case
                    in {"hash_failure", "rollback_failure", "rollback_static_failure"}
                    else hashes
                )
            elif args[0] == "git":
                result = (
                    "c" * 40
                    if "rev-parse" in args
                    else (" M tracked" if case == "dirty_git" else "")
                )
            elif args[0] == "bash":
                if args[1].endswith("vps-snapshot.sh"):
                    if case == "after_snapshot_failure" and args[2].endswith("-after"):
                        code = 1
                    else:
                        mapped(args[2]).mkdir(parents=True, exist_ok=True)
                elif args[1].endswith("compare-vps-snapshots.sh"):
                    state["comparisons"] += 1
                    if (
                        case == "no_touch_always_failure"
                        or case == "no_touch_failure"
                        and state["comparisons"] == 1
                    ):
                        code = 1
                    result = "PREEXISTING_RESOURCES_MODIFIED=" + str(code)
                else:
                    raise AssertionError(args)
            else:
                raise AssertionError(args)
            return SimpleNamespace(
                returncode=code,
                stdout=result,
                stderr="synthetic failure" if code else "",
            )

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def http(request, **kwargs):
            url = request if isinstance(request, str) else request.full_url
            if url.endswith("/api/auth/login"):
                raise HTTPError(url, 403, "synthetic CSRF rejection", None, None)
            if url.endswith("/static/admin/css/base.css") and (
                (case == "static_failure" and state["image"] == NEW)
                or (case == "rollback_static_failure" and state["image"] == OLD)
            ):
                raise HTTPError(url, 404, "synthetic missing static asset", None, None)
            if (
                case == "smoke_failure"
                and state["image"] == NEW
                and url.endswith("ready")
            ):
                raise HTTPError(url, 502, "synthetic unavailable", None, None)
            return Response()

        def protected(path, parent):
            # Only Unix ownership is mocked; containment and actual existence remain checked.
            path = mapped(path).resolve(strict=True)
            assert path.is_relative_to(mapped(parent))
            return path

        argv = [str(TARGET), "prepare", str(run), str(restore), str(tested)]
        with (
            patch.object(module, "Path", mapped),
            patch.object(module, "protected", protected),
            patch.object(module.os, "geteuid", lambda: 0, create=True),
            patch.object(module.os, "umask", lambda value: None),
            patch.object(module.subprocess, "run", command),
            patch.object(module, "urlopen", http),
            patch.object(module.time, "sleep", lambda seconds: None),
            patch.object(module.sys, "argv", argv),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            refusal_cases = {
                "expired",
                "bad_checksum",
                "restore_failure",
                "wrong_image",
                "test_skip",
                "few_tests",
                "scope_change",
                "production_changed",
                "dirty_git",
                "static_gate_missing",
            }
            if case == "expired":
                os.utime(archive, (time.time() - 3601,) * 2)
            if case == "static_gate_missing":
                target = tested / "result.txt"
                write(
                    target, target.read_text().replace("admin_static_smoke=PASS\n", "")
                )
            if case == "bad_checksum":
                write(archive.with_name(archive_name + ".sha256"), "bad")
            if case == "restore_failure":
                write(
                    restore / "result.txt",
                    (restore / "result.txt")
                    .read_text()
                    .replace("postgres_restore=PASS", "postgres_restore=FAIL"),
                )
            if case == "wrong_image":
                write(tested / "images.txt", "api=" + OLD)
            if case == "test_skip":
                write(
                    tested / "results/integration.xml",
                    xml.replace("<testcase/>", "<testcase><skipped/></testcase>", 1),
                )
            if case == "few_tests":
                write(
                    tested / "results/integration.xml",
                    xml.replace("<testcase/>", "", 1),
                )
            if case == "production_changed":
                state["image"] = NEW
            try:
                module.release()
            except RuntimeError:
                assert case in refusal_cases, case
                assert not state["ups"]
                return {"case": case, "result": "REFUSED_BEFORE_MUTATION"}
            assert case not in refusal_cases, case
            assert not state["ups"], "prepare changed Docker"
            if case == "prepare":
                return {"case": case, "result": "READ_ONLY_PLAN_CREATED"}
            argv[1] = "apply"
            if case == "plan_changed":
                write(run / "source/apps/api/core/mfa.py", "changed after prepare")
            failed = False
            try:
                module.release()
            except RuntimeError:
                failed = True
            if case == "plan_changed":
                assert failed and not state["ups"]
                return {"case": case, "result": "REFUSED_BEFORE_MUTATION"}
            outcome = json.loads((run / "deploy-result.json").read_text())
            if case == "success":
                assert (
                    not failed
                    and state["ups"] == [NEW]
                    and outcome["deployed"]
                    and outcome["no_touch"]
                )
            else:
                assert (
                    failed and state["ups"] == [NEW, OLD] and not outcome["deployed"]
                ), (case, state, outcome)
                assert outcome["rollback_failed"] == (
                    case in {"rollback_failure", "rollback_static_failure"}
                ), (
                    case,
                    outcome,
                )
                assert outcome["rolled_back"] == (
                    case not in {"rollback_failure", "rollback_static_failure"}
                ), (
                    case,
                    outcome,
                )
                if case == "no_touch_always_failure":
                    assert not outcome["no_touch"]
            return {"case": case, "result": "PASS", "outcome": outcome}


def lock_scenario(blocked):
    spec = importlib.util.spec_from_file_location("reviewed_deploy_lock", TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def flock(descriptor, flags):
        assert descriptor >= 0 and flags == 6
        calls.append("locked")
        if blocked:
            raise BlockingIOError("synthetic competing deployment")

    fake_fcntl = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=flock)
    with tempfile.TemporaryDirectory(prefix="kairos-deploy-lock-") as td:
        target = Path(td) / "deploy.lock"
        with (
            patch.object(module, "Path", lambda value: target),
            patch.object(module.os, "geteuid", lambda: 0, create=True),
            patch.object(module, "release", lambda: calls.append("release")),
            patch.dict(sys.modules, {"fcntl": fake_fcntl}),
        ):
            try:
                module.main()
            except BlockingIOError:
                assert blocked
    assert calls == (["locked"] if blocked else ["locked", "release"])
    return {"case": "competing_lock" if blocked else "lock_order", "result": "PASS"}


if __name__ == "__main__":
    cases = [
        "static_gate_missing",
        "static_failure",
        "rollback_static_failure",
        "prepare",
        "expired",
        "bad_checksum",
        "restore_failure",
        "wrong_image",
        "test_skip",
        "few_tests",
        "scope_change",
        "production_changed",
        "dirty_git",
        "plan_changed",
        "success",
        "up_failure",
        "health_failure",
        "smoke_failure",
        "hash_failure",
        "no_touch_failure",
        "after_snapshot_failure",
        "no_touch_always_failure",
        "rollback_failure",
    ]
    result = [scenario(case) for case in cases] + [
        lock_scenario(False),
        lock_scenario(True),
    ]
    print(
        json.dumps(
            {
                "target_sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
                "result": "PASS",
                "cases": result,
                "limitations": [
                    "All Docker/HTTP calls mocked",
                    "Windows fixtures substitute Unix ownership; namespace/existence checks remain",
                    "No Docker/VPS/network operation",
                ],
            },
            indent=2,
        )
    )
