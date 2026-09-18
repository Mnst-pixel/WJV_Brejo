"""Local-only inspection and exclusive transition evidence. No deploy commands."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess

spec = importlib.util.spec_from_file_location("transition_io_plan", Path(__file__).with_name("release_transition_plan.py"))
transition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transition)
SOCKET, bind, gate, policy = transition.SOCKET, transition.bind, transition.gate, transition.policy
require, sibling, state, validate = transition.require, transition.sibling, transition.state, transition.validate

snapshot = sibling("transition_snapshot_reader", "snapshot-network-ownership.py")
ROOT = Path("/opt/kairos/runtime/transitions")
BASELINES = Path("/opt/kairos/runtime/baselines")


def docker(arguments):
    output = subprocess.check_output(["/usr/bin/docker", "--host", SOCKET, *arguments], text=True,
        stderr=subprocess.DEVNULL, timeout=30, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})
    require(len(output) <= 16 * 1024**2, "docker_output_limit")
    return output.strip()


def collect(run=docker):
    """Only fixed inspection fields; never read Env, command, mounts or secrets."""
    def projected(arguments):
        require(arguments[0] == "docker", "unexpected_snapshot_command")
        return run(arguments[1:])
    projection = snapshot.collect(projected)
    runtime, images = [], {}
    template = '{"id":{{json .Id}},"name":{{json .Name}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"image":{{json .Image}}}'
    for container in projection["containers"]:
        require(re.fullmatch(r"[a-f0-9]{64}", container["id"]), "invalid_inspected_container_id")
        row = json.loads(run(["container", "inspect", "--format", template, container["id"]]))
        require(set(row) == {"id", "name", "project", "service", "image"} and re.fullmatch(r"sha256:[a-f0-9]{64}", row["image"]), "invalid_runtime_inspection")
        row["revision"] = None
        if policy.owned(row):
            if row["image"] not in images:
                images[row["image"]] = json.loads(run(["image", "inspect", "--format", '{{json (index .Config.Labels "org.opencontainers.image.revision")}}', row["image"]]))
            row["revision"] = images[row["image"]]
        runtime.append(row)
    require(snapshot.collect(projected) == projection, "docker_changed_during_inspection")
    value = {"docker_socket": SOCKET, "projection": projection, "runtime": sorted(runtime, key=lambda row: row["id"])}
    state(value)
    return value


def checked_directory(path, root):
    require(os.name == "posix", "transition_evidence_requires_posix")
    path, root = Path(path), Path(root)
    require(path.is_absolute() and root.is_absolute() and path != root and path.is_relative_to(root), "invalid_evidence_namespace")
    require(path.resolve() == path and root.resolve() == root, "evidence_symlink_or_traversal")
    require(root.is_dir(), "missing_evidence_root")
    for parent in [path, *path.parents]:
        if parent.exists():
            info = parent.lstat()
            # A root-owned sticky /tmp protects this user's temporary fixture
            # against rename by other users; an ordinary writable parent does not.
            sticky_tmp = parent == Path("/tmp") and info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            require(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, os.geteuid()} and (not info.st_mode & 0o022 or sticky_tmp), "unprotected_evidence_directory")
    return path


def secure_read(path, limit=16 * 1024**2):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1 and not info.st_mode & 0o077 and info.st_size <= limit, "unprotected_evidence_file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            value = stream.read(limit + 1)
        require(len(value) <= limit, "evidence_size_limit")
        return value
    finally:
        os.close(fd)


def exclusive_json(path, value):
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return hashlib.sha256(data).hexdigest()


def current_configuration(plan):
    for change in plan["config_changes"]:
        path = Path(change["path"])
        if change["before"] is None:
            require(not path.exists() and not path.is_symlink(), "unexpected_existing_configuration")
        else:
            require(gate.kairos_path(str(path.resolve())) and path.is_file() and path.stat().st_size <= 16 * 1024**2, "unsafe_configuration_path")
            require(hashlib.sha256(path.read_bytes()).hexdigest() == change["before"], "configuration_changed_before_mutation")


def snapshot_receipt(directory, root=BASELINES):
    directory = checked_directory(directory, root)
    data = secure_read(directory / "MANIFEST.sha256")
    entries = {}
    for line in data.decode().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  \./([a-zA-Z0-9_.-]+)", line)
        require(match is not None and match[2] not in entries and match[2] not in {".", "..", "MANIFEST.sha256"}, "invalid_snapshot_manifest")
        entries[match[2]] = match[1]
    require(set(gate.REQUIRED) | {"network-ownership.json"} <= entries.keys(), "incomplete_snapshot_manifest")
    require({path.name for path in directory.iterdir()} == set(entries) | {"MANIFEST.sha256"}, "unmanifested_snapshot_entry")
    for name, digest in entries.items():
        require(hashlib.sha256(secure_read(directory / name)).hexdigest() == digest, "snapshot_checksum_mismatch")
    return {"directory": str(directory), "manifest_sha256": hashlib.sha256(data).hexdigest()}


def freeze(directory, plan, baseline, inspect=collect, root=ROOT, baseline_root=BASELINES):
    directory = checked_directory(directory, root)
    before_snapshot = snapshot_receipt(baseline, baseline_root)
    before = inspect()
    require(before["projection"] == json.loads(secure_read(Path(baseline) / "network-ownership.json")), "baseline_not_current")
    validate(plan, before)
    current_configuration(plan)
    # Verify declared old configuration hashes while the frozen baseline is current.
    hashes = {}
    for filename in gate.HASH_FILES:
        path = Path(baseline) / filename
        if path.exists():
            for key, digest in gate.hashes(secure_read(path).decode()).items():
                require(key not in hashes or hashes[key] == digest, "inconsistent_baseline_config")
                hashes[key] = digest
    for change in plan["config_changes"]:
        require(hashes.get(change["path"]) == change["before"], "configuration_before_mismatch")
    directory.mkdir(mode=0o700)  # Exclusive; partial failure cannot be resumed as a fresh plan.
    written = {name: exclusive_json(directory / name, value) for name, value in (("plan.json", plan), ("before.json", before), ("baseline.json", before_snapshot))}
    exclusive_json(directory / "FROZEN.json", {"version": 1, "files": written})
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return policy.digest(plan)


def frozen(directory, root=ROOT, baseline_root=BASELINES):
    directory = checked_directory(directory, root)
    marker = json.loads(secure_read(directory / "FROZEN.json"))
    require(set(marker) == {"version", "files"} and marker["version"] == 1 and set(marker["files"]) == {"plan.json", "before.json", "baseline.json"}, "invalid_freeze_marker")
    values = {}
    for name, digest in marker["files"].items():
        data = secure_read(directory / name)
        require(hashlib.sha256(data).hexdigest() == digest, "frozen_file_changed")
        values[name] = json.loads(data)
    baseline = values["baseline.json"]
    require(snapshot_receipt(baseline["directory"], baseline_root) == baseline, "frozen_baseline_changed")
    validate(values["plan.json"], values["before.json"])
    return values


def before_mutation(directory, inspect=collect, root=ROOT, baseline_root=BASELINES):
    values = frozen(directory, root, baseline_root)
    require(inspect() == values["before.json"], "runtime_drift_before_mutation")
    current_configuration(values["plan.json"])
    digest = policy.digest(values["plan.json"])
    exclusive_json(Path(directory) / "STARTED.json", {"version": 1, "plan_sha256": digest, "before_sha256": policy.digest(values["before.json"])})
    return digest


def seal(directory, after_snapshot, inspect=collect, root=ROOT, baseline_root=BASELINES):
    values = frozen(directory, root, baseline_root)
    started = json.loads(secure_read(Path(directory) / "STARTED.json"))
    require(started == {"version": 1, "plan_sha256": policy.digest(values["plan.json"]), "before_sha256": policy.digest(values["before.json"])}, "invalid_start_receipt")
    captured = snapshot_receipt(after_snapshot, baseline_root)
    after = inspect()
    require(after["projection"] == json.loads(secure_read(Path(after_snapshot) / "network-ownership.json")), "after_snapshot_not_current")
    manifest, receipt = bind(values["plan.json"], values["before.json"], after)
    result = gate.compare(values["baseline.json"]["directory"], after_snapshot, manifest)
    require(result["result"] == "PASS", "full_snapshot_comparator_failed")
    envelope = {"version": 1, "receipt": receipt, "after_snapshot": captured, "after_state": after, "manifest": manifest, "comparison": result}
    exclusive_json(Path(directory) / "RECEIPT.json", envelope)
    return {"result": "PASS", "plan_sha256": receipt["plan_sha256"], "manifest_sha256": receipt["manifest_sha256"]}
