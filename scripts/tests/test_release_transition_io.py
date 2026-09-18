import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


io = load("transition_io_test", ROOT / "release_transition_io.py")
model_tests = load("transition_io_model_fixture", ROOT / "tests/test_release_transition_plan.py")


class TransitionCollectorTests(unittest.TestCase):
    def test_foreign_container_image_is_not_inspected(self):
        projection = model_tests.fixtures.fixture()[0]
        projection["containers"].append({"id": "e" * 64, "name": "/foreign-app", "project": "foreign", "networks": [], "bindings": []})
        def run(args):
            if args[0] == "image":
                self.assertEqual(args[-1], "sha256:" + "f" * 64)
                return "null"
            foreign = args[-1] == "e" * 64
            return json.dumps({"id": ("e" if foreign else "b") * 64, "name": "/foreign-app" if foreign else "/kairos-edge-1", "project": "foreign" if foreign else "kairos", "service": "app" if foreign else "edge", "image": "sha256:" + ("0" if foreign else "f") * 64})
        with patch.object(io.snapshot, "collect", side_effect=[projection, projection]):
            value = io.collect(run)
        self.assertIsNone(value["runtime"][1]["revision"])

    def test_docker_is_pinned_to_local_socket_without_ambient_environment(self):
        with patch.object(io.subprocess, "check_output", return_value="[]\n") as run:
            self.assertEqual(io.docker(["ps", "-aq"]), "[]")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "ps", "-aq"])
        self.assertEqual(set(kwargs["env"]), {"PATH", "LANG"})
        self.assertEqual(kwargs["timeout"], 30)
        self.assertNotIn("shell", kwargs)

    def test_collector_inspects_only_metadata_and_rechecks_network_state(self):
        projection = model_tests.fixtures.fixture()[0]
        called = []
        def run(args):
            called.append(args)
            if args[0] == "image":
                return "null"
            return json.dumps({"id": "b" * 64, "name": "/kairos-edge-1", "project": "kairos", "service": "edge", "image": "sha256:" + "f" * 64})
        with patch.object(io.snapshot, "collect", side_effect=[projection, projection]) as collect:
            value = io.collect(run)
        self.assertEqual(collect.call_count, 2)
        self.assertEqual(value, model_tests.state(projection))
        self.assertEqual([call[0] for call in called], ["container", "image"])
        self.assertTrue(all(".Env" not in str(call) and ".Cmd" not in str(call) for call in called))
        changed = copy.deepcopy(projection)
        changed["containers"][0]["id"] = "a" * 64
        with patch.object(io.snapshot, "collect", side_effect=[projection, changed]), self.assertRaises(ValueError):
            io.collect(run)


@unittest.skipUnless(os.name == "posix", "Protected evidence requires Linux/POSIX fixture")
class ProtectedTransitionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = model_tests.fixtures.NetworkReleaseV2Tests(methodName="test_unchanged_baseline_passes_without_network_exceptions")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.baselines = self.fixture.before.parent
        self.root = self.baselines / "kairos-transitions"
        self.root.mkdir(mode=0o700)
        self.directory = self.root / "kairos-case"
        self.before = model_tests.state(self.fixture.load(self.fixture.before))
        self.plan = model_tests.plan(self.before)
        self.inspector = lambda: copy.deepcopy(self.before)
        self.refresh(self.fixture.before)
        self.refresh(self.fixture.after)

    def refresh(self, directory):
        lines = []
        for path in sorted(directory.iterdir()):
            if path.name != "MANIFEST.sha256":
                path.chmod(0o600)
                lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  ./" + path.name)
        manifest = directory / "MANIFEST.sha256"
        manifest.write_text("\n".join(lines) + "\n")
        manifest.chmod(0o600)

    def freeze(self):
        return io.freeze(self.directory, self.plan, self.fixture.before, self.inspector, self.root, self.baselines)

    def start(self, inspect=None):
        return io.before_mutation(self.directory, inspect or self.inspector, self.root, self.baselines)

    def seal(self):
        return io.seal(self.directory, self.fixture.after, self.inspector, self.root, self.baselines)

    def test_freeze_start_seal_are_exclusive_and_mode_0600(self):
        digest = self.freeze()
        self.assertEqual(self.start(), digest)
        self.assertEqual(self.seal()["result"], "PASS")
        for path in self.directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for action in (self.freeze, self.start, self.seal):
            with self.subTest(action=action), self.assertRaises(FileExistsError):
                action()

    def test_changed_plan_cannot_start(self):
        self.freeze()
        path = self.directory / "plan.json"
        path.write_bytes(path.read_bytes().replace(b'"release_commit":"c', b'"release_commit":"d'))
        with self.assertRaises(ValueError):
            self.start()
        self.assertFalse((self.directory / "STARTED.json").exists())

    def test_changed_snapshot_is_rejected_even_if_its_manifest_is_regenerated(self):
        self.freeze()
        (self.fixture.before / "containers.txt").write_text("changed\n")
        with self.assertRaises(ValueError):
            self.start()
        self.refresh(self.fixture.before)
        with self.assertRaises(ValueError):
            self.start()

    def test_runtime_drift_after_freeze_is_rejected(self):
        self.freeze()
        changed = copy.deepcopy(self.before)
        changed["runtime"][0]["image"] = "sha256:" + "e" * 64
        with self.assertRaises(ValueError):
            self.start(lambda: changed)

    def test_seal_requires_start_and_unchanged_firewall(self):
        self.freeze()
        with self.assertRaises(FileNotFoundError):
            self.seal()
        self.start()
        path = self.fixture.after / "iptables.txt"
        path.write_text(path.read_text().replace("-A INPUT -p tcp --dport 22 -j ACCEPT", "-A INPUT -j ACCEPT"))
        self.refresh(self.fixture.after)
        with self.assertRaises(ValueError):
            self.seal()
        self.assertFalse((self.directory / "RECEIPT.json").exists())

    def test_unprotected_files_links_and_symlink_directories_are_rejected(self):
        self.freeze()
        path = self.directory / "plan.json"
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.start()
        path.chmod(0o600)
        duplicate = self.directory / "duplicate.json"
        os.link(path, duplicate)
        with self.assertRaises(ValueError):
            self.start()
        duplicate.unlink()
        symlink = self.root / "alias"
        symlink.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            io.frozen(symlink, self.root, self.baselines)

    def test_missing_snapshot_rows_and_traversal_manifest_are_rejected(self):
        manifest = self.fixture.before / "MANIFEST.sha256"
        original = manifest.read_text()
        manifest.write_text("a" * 64 + "  ./../outside\n")
        with self.assertRaises(ValueError):
            self.freeze()
        manifest.write_text("\n".join(line for line in original.splitlines() if "network-ownership.json" not in line) + "\n")
        with self.assertRaises(ValueError):
            self.freeze()

    def test_optional_config_inventory_cannot_be_added_after_freeze(self):
        self.freeze()
        optional = self.fixture.before / "release-config-hashes.txt"
        self.assertFalse(optional.exists())
        optional.write_text("")
        optional.chmod(0o600)
        with self.assertRaises(ValueError):
            self.start()
        self.assertFalse((self.directory / "STARTED.json").exists())

    def test_writable_parent_above_namespace_is_rejected(self):
        self.freeze()
        previous = self.baselines.stat().st_mode & 0o777
        try:
            self.baselines.chmod(0o777)
            with self.assertRaises(ValueError):
                self.start()
        finally:
            self.baselines.chmod(previous)

    def test_concurrent_freeze_accepts_exactly_one(self):
        from concurrent.futures import ThreadPoolExecutor
        def attempt():
            try:
                self.freeze()
                return "ok"
            except FileExistsError:
                return "exists"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        self.assertEqual(sorted(results), ["exists", "ok"])
        self.start()
