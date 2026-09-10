import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "compare_release", ROOT / "compare-release-snapshots.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
SPEC2 = importlib.util.spec_from_file_location(
    "network_projection", ROOT / "snapshot-network-ownership.py"
)
projection = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(projection)


class CompareReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.before = Path(self.temp.name) / "before"
        self.after = Path(self.temp.name) / "after"
        for folder in (self.before, self.after):
            folder.mkdir()
            for name in gate.REQUIRED:
                (folder / name).write_text("")
            for name in ("containers.txt", "container-identities.txt", "networks.txt"):
                (folder / name).write_text(
                    "old|kairos-api-1|old\nforeign-id|other-project|stable\n"
                )
        self.path = "/opt/kairos/current/infra/compose/compose.yaml"
        self.old_hash = "a" * 64
        self.new_hash = "b" * 64
        self.manifest = {"version": 1, "release_commit": "c" * 40, "config_changes": []}

    def change(self, path=None, inventory="compose-config-hashes.txt"):
        path = path or self.path
        (self.before / inventory).write_text(f"{self.old_hash}  {path}\n")
        (self.after / inventory).write_text(f"{self.new_hash}  {path}\n")
        self.manifest["config_changes"].append(
            {"path": path, "before": self.old_hash, "after": self.new_hash}
        )

    def compare(self):
        return gate.compare(self.before, self.after, self.manifest)

    def test_exact_authorized_compose_change_passes(self):
        self.change()
        self.assertEqual(self.compare()["result"], "PASS")

    def test_same_config_recorded_in_two_inventories_requires_consistency(self):
        self.change()
        for directory in (self.before, self.after):
            (directory / "release-config-hashes.txt").write_text(
                (directory / "compose-config-hashes.txt").read_text()
            )
        self.assertEqual(self.compare()["result"], "PASS")
        (self.after / "release-config-hashes.txt").write_text(
            f"{'d' * 64}  {self.path}\n"
        )
        with self.assertRaises(gate.GateError):
            self.compare()

    def test_authorized_nginx_kairos_vhost_passes(self):
        self.change(
            "/etc/nginx/sites-available/kairos-sslip.conf", "nginx-config-hashes.txt"
        )
        self.assertEqual(self.compare()["result"], "PASS")

    def test_foreign_nginx_cannot_be_authorized(self):
        self.change("/etc/nginx/nginx.conf", "nginx-config-hashes.txt")
        with self.assertRaises(gate.GateError):
            self.compare()

    def test_other_vhost_change_fails_even_with_authorized_kairos(self):
        self.change()
        (self.before / "nginx-config-hashes.txt").write_text(
            f"{self.old_hash}  /etc/nginx/sites-available/shop.conf\n"
        )
        (self.after / "nginx-config-hashes.txt").write_text(
            f"{self.new_hash}  /etc/nginx/sites-available/shop.conf\n"
        )
        self.assertEqual(self.compare()["result"], "FAIL")

    def test_foreign_new_nginx_file_cannot_hide_as_addition(self):
        (self.after / "nginx-config-hashes.txt").write_text(
            f"{self.new_hash}  /etc/nginx/extra.conf\n"
        )
        self.assertEqual(self.compare()["result"], "FAIL")

    def test_wrong_expected_before_or_after_hash_fails(self):
        self.change()
        for field in ("before", "after"):
            original = self.manifest["config_changes"][0][field]
            self.manifest["config_changes"][0][field] = "d" * 64
            self.assertEqual(self.compare()["result"], "FAIL")
            self.manifest["config_changes"][0][field] = original

    def test_unobserved_permission_is_not_silently_accepted(self):
        self.manifest["config_changes"].append(
            {"path": self.path, "before": self.old_hash, "after": self.new_hash}
        )
        self.assertEqual(self.compare()["result"], "FAIL")

    def test_exact_new_kairos_config_can_be_added(self):
        path = "/opt/kairos/releases/" + "d" * 40 + "/infra/compose/compose.yaml"
        self.manifest["config_changes"].append(
            {"path": path, "before": None, "after": self.new_hash}
        )
        (self.after / "compose-config-hashes.txt").write_text(
            f"{self.new_hash}  {path}\n"
        )
        self.assertEqual(self.compare()["result"], "PASS")

    def test_old_configuration_deletion_rejected(self):
        self.change()
        self.manifest["config_changes"][0]["after"] = None
        with self.assertRaises(gate.GateError):
            self.compare()

    def test_duplicate_wildcard_traversal_secret_paths_rejected(self):
        for value in (
            "/etc/nginx/sites-available/kairos-other.conf",
            "/opt/kairos/current/infra/*",
            "/opt/kairos/current/infra/../../secrets/.env",
            "/opt/kairos/secrets/.env",
        ):
            self.manifest["config_changes"] = [
                {"path": value, "before": self.old_hash, "after": self.new_hash}
            ]
            if "*" in value:
                # Literal wildcard filenames are never expanded; still must be forbidden by contract.
                self.assertFalse(gate.kairos_path(value))
            else:
                with self.assertRaises(gate.GateError):
                    self.compare()

    def test_duplicate_manifest_paths_rejected(self):
        self.change()
        self.manifest["config_changes"].append(dict(self.manifest["config_changes"][0]))
        with self.assertRaises(gate.GateError):
            self.compare()

    def test_missing_required_inventory_rejected(self):
        (self.after / "listeners.txt").unlink()
        with self.assertRaises(gate.GateError):
            self.compare()

    def test_foreign_container_image_name_kairos_does_not_hide_identity(self):
        (self.before / "containers.txt").write_text("old|shop|kairos-image\n")
        (self.after / "containers.txt").write_text("new|shop|kairos-image\n")
        self.assertEqual(self.compare()["result"], "FAIL")

    def test_kairos_container_replacement_passes(self):
        (self.after / "containers.txt").write_text(
            "new|kairos-api-1|new\nforeign-id|other-project|stable\n"
        )
        self.assertEqual(self.compare()["result"], "PASS")

    def test_listener_4080_change_remains_blocked(self):
        (self.before / "listeners.txt").write_text(
            "tcp LISTEN 0 4096 0.0.0.0:4080 0.0.0.0:*\n"
        )
        (self.after / "listeners.txt").write_text(
            "tcp LISTEN 0 4096 127.0.0.1:4080 0.0.0.0:*\n"
        )
        result = self.compare()
        self.assertEqual(result["result"], "FAIL")
        self.assertFalse(result["listener_exceptions"])

    def test_shared_firewall_rule_addition_remains_blocked(self):
        (self.after / "iptables.txt").write_text("-A DOCKER-USER -j ACCEPT\n")
        self.assertEqual(self.compare()["result"], "FAIL")

    def test_firewall_rule_reordering_blocked(self):
        (self.before / "iptables.txt").write_text(
            "-A INPUT -j DROP\n-A INPUT -j ACCEPT\n"
        )
        (self.after / "iptables.txt").write_text(
            "-A INPUT -j ACCEPT\n-A INPUT -j DROP\n"
        )
        self.assertEqual(self.compare()["result"], "FAIL")

    def test_firewall_counters_are_only_normalization(self):
        (self.before / "iptables.txt").write_text(
            "# Generated by iptables-save on yesterday\n:INPUT ACCEPT [1:30]\n-A INPUT -c 1 2 -j ACCEPT\n"
        )
        (self.after / "iptables.txt").write_text(
            "# Generated by iptables-save on today\n:INPUT ACCEPT [3:99]\n-A INPUT -c 3 9 -j ACCEPT\n"
        )
        self.assertEqual(self.compare()["result"], "PASS")

    def test_unrelated_network_ip_change_blocks(self):
        data = {
            "version": 1,
            "containers": [
                {
                    "id": "foreign",
                    "name": "/shop",
                    "project": "shop",
                    "networks": ["ip1"],
                }
            ],
            "networks": [],
        }
        (self.before / "network-ownership.json").write_text(json.dumps(data))
        data["containers"][0]["networks"] = ["ip2"]
        (self.after / "network-ownership.json").write_text(json.dumps(data))
        self.assertEqual(self.compare()["result"], "FAIL")

    def test_without_manifest_calls_original_comparator_and_preserves_exit(self):
        calls = []

        def runner(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=7)

        self.assertEqual(gate.run(self.before, self.after, legacy_runner=runner), 7)
        self.assertTrue(calls[0][1].endswith("compare-vps-snapshots.sh"))

    def test_kairos_named_network_with_foreign_endpoint_is_fully_protected(self):
        data = {
            "version": 1,
            "containers": [{"id": "foreign", "name": "/shop", "project": "shop"}],
            "networks": [{"id": "network", "name": "kairos-shared", "project": "kairos", "internal": False, "containers": [{"id": "foreign"}]}],
        }
        (self.before / "network-ownership.json").write_text(json.dumps(data))
        data["networks"][0]["internal"] = True
        (self.after / "network-ownership.json").write_text(json.dumps(data))
        self.assertEqual(self.compare()["result"], "FAIL")


class NetworkProjectionTests(unittest.TestCase):
    def test_projection_excludes_environment_commands_arbitrary_labels(self):
        commands = []

        def docker(args):
            commands.append(args)
            if args[1:3] == ["ps", "-aq"]:
                return "cid"
            if args[1:3] == ["network", "ls"]:
                return "nid"
            if args[1:3] == ["container", "inspect"]:
                return json.dumps(
                    {
                        "id": "cid",
                        "name": "/kairos-edge-1",
                        "project": "kairos",
                        "networks": {
                            "kairos-edge": {
                                "NetworkID": "nid",
                                "IPAddress": "172.31.0.2",
                                "GlobalIPv6Address": "",
                                "Aliases": ["ignored"],
                            }
                        },
                        "bindings": {
                            "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4080"}]
                        },
                    }
                )
            return json.dumps(
                {
                    "id": "nid",
                    "name": "kairos-edge",
                    "driver": "bridge",
                    "internal": True,
                    "project": "kairos",
                    "options": {
                        "com.docker.network.bridge.name": "kairosbr0",
                        "irrelevant": "omitted",
                    },
                    "ipam": [{"Subnet": "172.31.0.0/24", "Gateway": "172.31.0.1"}],
                    "containers": {
                        "cid": {
                            "Name": "kairos-edge-1",
                            "IPv4Address": "172.31.0.2/24",
                            "IPv6Address": "",
                        }
                    },
                }
            )

        data = projection.collect(docker)
        self.assertEqual(data["containers"][0]["bindings"][0]["host_port"], "4080")
        self.assertEqual(data["networks"][0]["bridge_option"], "kairosbr0")
        self.assertNotIn("ignored", json.dumps(data))
        self.assertNotIn("omitted", json.dumps(data))
        self.assertNotIn(".Config.Env", str(commands))
        self.assertNotIn(".Config.Cmd", str(commands))


if __name__ == "__main__":
    unittest.main()
