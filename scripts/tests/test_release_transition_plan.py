import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transition = load("transition_plan_test", ROOT / "release_transition_plan.py")
fixtures = load("network_fixture_transition", ROOT / "tests/test_release_network_policy.py")


def state(projection):
    return {"docker_socket": transition.SOCKET, "projection": projection, "runtime": [{"id": row["id"], "name": row["name"], "project": row["project"], "service": "edge", "image": "sha256:" + "f" * 64, "revision": None} for row in projection["containers"]]}


def plan(before):
    return {"version": 1, "release_commit": "c" * 40, "baseline_sha256": transition.policy.digest(before), "docker_socket": transition.SOCKET,
        "config_changes": [], "edge_binding_change": None,
        "networks": [{"name": row["name"], "operation": "retain", "previous_id": row["id"], "configuration": transition.configuration(row)} for row in before["projection"]["networks"]],
        "containers": [{"name": row["name"].lstrip("/"), "operation": "retain", "previous_id": row["id"], "service": "edge", "image": "sha256:" + "f" * 64, "revision": None, "bindings": row["bindings"], "networks": [{"name": link["name"], "ipv4": link["ipv4"]} for link in row["networks"]]} for row in before["projection"]["containers"]]}


class TransitionPlanTests(unittest.TestCase):
    def setUp(self):
        self.before = state(fixtures.fixture()[0])
        self.plan = plan(self.before)
        self.after = copy.deepcopy(self.before)

    def replace(self):
        self.plan["containers"][0]["operation"] = "replace"
        self.plan["containers"][0]["networks"][0]["ipv4"] = "dynamic"
        self.after["projection"]["containers"][0]["id"] = "d" * 64
        self.after["projection"]["containers"][0]["networks"][0]["ipv4"] = "172.30.1.7"
        self.after["projection"]["networks"][0]["containers"][0].update(id="d" * 64, ipv4="172.30.1.7/24")
        self.after["runtime"][0]["id"] = "d" * 64

    def test_retained_and_dynamic_replacement_receipt(self):
        manifest, receipt = transition.bind(self.plan, self.before, self.after)
        self.assertEqual(manifest["network_changes"], [])
        self.assertEqual(transition.verify_receipt(self.plan, self.before, self.after, receipt), manifest)
        self.replace()
        transition.validate(self.plan, self.before)
        manifest, receipt = transition.bind(self.plan, self.before, self.after)
        self.assertEqual(len(manifest["network_changes"]), 1)
        self.assertEqual(receipt["allocations"]["containers"]["kairos-edge-1"], "d" * 64)
        self.assertEqual(transition.verify_receipt(self.plan, self.before, self.after, receipt), manifest)

    def test_retained_stopped_container_preserves_absent_address(self):
        self.before["projection"]["containers"][0]["networks"][0]["ipv4"] = ""
        self.before["projection"]["networks"][0]["containers"] = []
        declared = plan(self.before)
        after = copy.deepcopy(self.before)
        transition.bind(declared, self.before, after)
        altered = copy.deepcopy(declared)
        altered["containers"][0]["operation"] = "replace"
        with self.assertRaises(ValueError):
            transition.validate(altered, self.before)
        after["projection"]["containers"][0]["networks"][0]["ipv4"] = "172.30.1.2"
        after["projection"]["networks"][0]["containers"] = [{"id": "b" * 64, "name": "kairos-edge-1", "ipv4": "172.30.1.2/24", "ipv6": ""}]
        with self.assertRaises(ValueError):
            transition.bind(declared, self.before, after)

    def test_receipt_cannot_change_authority_or_digest(self):
        self.replace()
        manifest, receipt = transition.bind(self.plan, self.before, self.after)
        for key, value in (("plan_sha256", "a" * 64), ("docker_socket", "tcp://remote:2375"), ("allocations", {}), ("manifest_sha256", "b" * 64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                transition.verify_receipt(self.plan, self.before, self.after, {**receipt, key: value})
        with self.assertRaises(ValueError):
            transition.verify_receipt(self.plan, self.before, self.after, {**receipt, "extra_scope": "admin"})

    def test_inactive_owned_endpoint_cannot_hide_ipv6(self):
        self.before["projection"]["containers"][0]["networks"][0]["ipv4"] = ""
        self.before["projection"]["networks"][0]["containers"] = []
        declared = plan(self.before)
        after = copy.deepcopy(self.before)
        after["projection"]["containers"][0]["networks"][0]["ipv6"] = "2001:db8::7"
        with self.assertRaises(ValueError):
            transition.bind(declared, self.before, after)
        with self.assertRaises(ValueError):
            transition.validate(plan(after), after)

    def test_missing_legacy_revision_is_preserved_but_new_application_requires_commit(self):
        self.before["runtime"][0]["revision"] = ""
        declared = plan(self.before)
        declared["containers"][0]["revision"] = ""
        transition.bind(declared, self.before, copy.deepcopy(self.before))
        declared["containers"][0].update(service="api", operation="replace")
        with self.assertRaises(ValueError):
            transition.validate(declared, self.before)

    def test_plan_requires_exact_baseline_and_every_owned_identity(self):
        for key, value in (("baseline_sha256", "0" * 64), ("docker_socket", "tcp://remote:2375"), ("containers", []), ("networks", [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                transition.validate({**self.plan, key: value}, self.before)
        self.plan["containers"][0]["previous_id"] = "e" * 64
        with self.assertRaises(ValueError):
            transition.validate(self.plan, self.before)

    def test_retention_cannot_implicitly_replace_or_reallocate(self):
        self.replace()
        self.plan["containers"][0]["operation"] = "retain"
        with self.assertRaises(ValueError):
            transition.bind(self.plan, self.before, self.after)
        self.plan["containers"][0]["networks"][0]["ipv4"] = "172.30.1.2"
        with self.assertRaises(ValueError):
            transition.bind(self.plan, self.before, self.after)

    def test_replacement_runtime_must_match_declared_image_service_revision(self):
        self.replace()
        for key, value in (("image", "sha256:" + "e" * 64), ("service", "admin"), ("revision", "a" * 40), ("project", "other")):
            changed = copy.deepcopy(self.after)
            changed["runtime"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                transition.bind(self.plan, self.before, changed)

    def test_dynamic_address_cannot_escape_subnet_or_take_gateway(self):
        self.replace()
        for address, prefix in (("172.30.2.7", "24"), ("172.30.1.1", "24"), ("172.30.1.0", "24")):
            changed = copy.deepcopy(self.after)
            changed["projection"]["containers"][0]["networks"][0]["ipv4"] = address
            changed["projection"]["networks"][0]["containers"][0]["ipv4"] = address + "/" + prefix
            with self.subTest(address=address), self.assertRaises(ValueError):
                transition.bind(self.plan, self.before, changed)

    def test_foreign_project_with_kairos_name_is_not_own(self):
        self.before["projection"]["containers"][0]["project"] = "other"
        self.before["runtime"][0]["project"] = "other"
        self.plan["baseline_sha256"] = transition.policy.digest(self.before)
        with self.assertRaises(ValueError):
            transition.validate(self.plan, self.before)

    def test_internal_network_creation_is_explicit_and_nonoverlapping(self):
        network = {"name": "kairos-parser", "operation": "create", "previous_id": None, "configuration": {"driver": "bridge", "internal": True, "subnets": [{"subnet": "172.30.2.0/24", "gateway": "172.30.2.1"}], "bridge_option": None, "bridge_options": {}}}
        self.plan["networks"].append(network)
        transition.validate(self.plan, self.before)
        self.after["projection"]["networks"].append({"id": "e" * 64, "name": "kairos-parser", "project": "kairos", "containers": [], **network["configuration"]})
        transition.bind(self.plan, self.before, self.after)
        for key, value in (("internal", False), ("subnets", [{"subnet": "172.30.1.0/24", "gateway": "172.30.1.1"}]), ("bridge_options", {"arbitrary": "1"})):
            altered = copy.deepcopy(self.plan)
            altered["networks"][1]["configuration"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                transition.validate(altered, self.before)

    def test_config_and_binding_cannot_expand_to_other_systems(self):
        altered = copy.deepcopy(self.plan)
        altered["config_changes"] = [{"path": "/etc/nginx/nginx.conf", "before": "a" * 64, "after": "b" * 64}]
        with self.assertRaises(ValueError):
            transition.validate(altered, self.before)
        altered = copy.deepcopy(self.plan)
        altered["containers"][0]["operation"] = "replace"
        altered["containers"][0]["bindings"][0]["host_port"] = "9000"
        with self.assertRaises(ValueError):
            transition.validate(altered, self.before)

    def test_bound_receipt_still_requires_firewall_barriers(self):
        suite = fixtures.NetworkReleaseV2Tests(methodName="test_unchanged_baseline_passes_without_network_exceptions")
        suite.setUp()
        try:
            before = state(suite.load(suite.before))
            declared = plan(before)
            declared["containers"][0]["operation"] = "replace"
            declared["containers"][0]["networks"][0]["ipv4"] = "dynamic"
            suite.move_ip()
            after = state(suite.load(suite.after))
            after["projection"]["containers"][0]["id"] = "d" * 64
            after["projection"]["networks"][0]["containers"][0]["id"] = "d" * 64
            after["runtime"][0]["id"] = "d" * 64
            suite.write_after(after["projection"])
            bound, receipt = transition.bind(declared, before, after)
            self.assertEqual(transition.gate.compare(suite.before, suite.after, transition.verify_receipt(declared, before, after, receipt))["result"], "PASS")
            path = suite.after / "iptables.txt"
            path.write_text(path.read_text().replace("-A INPUT -p tcp --dport 22 -j ACCEPT", "-A INPUT -j ACCEPT"))
            self.assertEqual(transition.gate.compare(suite.before, suite.after, bound)["result"], "FAIL")
        finally:
            suite.doCleanups()
