"""Independent synthetic fixtures plus optional captured baseline verification."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


gate = module("release_gate_v2_test", "compare-release-snapshots.py")
policy = module("release_network_v2_test", "release_network_policy.py")


def fixture():
    network_id, edge_id = "a" * 64, "b" * 64
    network = {"id": network_id, "name": "kairos-app", "project": "kairos", "driver": "bridge", "internal": False,
        "bridge_option": None, "bridge_options": {}, "subnets": [{"subnet": "172.30.1.0/24", "gateway": "172.30.1.1"}],
        "containers": [{"id": edge_id, "name": "kairos-edge-1", "ipv4": "172.30.1.2/24", "ipv6": ""}]}
    edge = {"id": edge_id, "name": "/kairos-edge-1", "project": "kairos", "bindings": [{"container_port": "80/tcp", "host_ip": "0.0.0.0", "host_port": "4080"}],
        "networks": [{"id": network_id, "name": "kairos-app", "ipv4": "172.30.1.2", "ipv6": ""}]}
    iptables = '''*raw
:PREROUTING ACCEPT [0:0]
-A PREROUTING -d 172.30.1.2/32 ! -i br-aaaaaaaaaaaa -j DROP
COMMIT
*filter
:INPUT DROP [0:0]
:DOCKER - [0:0]
:DOCKER-FORWARD - [0:0]
:DOCKER-CT - [0:0]
:DOCKER-BRIDGE - [0:0]
:DOCKER-INTERNAL - [0:0]
-A INPUT -p tcp --dport 22 -j ACCEPT
-A DOCKER -d 172.30.1.2/32 ! -i br-aaaaaaaaaaaa -o br-aaaaaaaaaaaa -p tcp -m tcp --dport 80 -j ACCEPT
-A DOCKER ! -i br-aaaaaaaaaaaa -o br-aaaaaaaaaaaa -j DROP
-A DOCKER-BRIDGE -o br-aaaaaaaaaaaa -j DOCKER
-A DOCKER-CT -o br-aaaaaaaaaaaa -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A DOCKER-FORWARD -i br-aaaaaaaaaaaa -j ACCEPT
COMMIT
*nat
:DOCKER - [0:0]
:POSTROUTING ACCEPT [0:0]
-A POSTROUTING -s 172.30.1.0/24 ! -o br-aaaaaaaaaaaa -j MASQUERADE
-A DOCKER ! -i br-aaaaaaaaaaaa -p tcp -m tcp --dport 4080 -j DNAT --to-destination 172.30.1.2:80
COMMIT
'''
    nft = '''table ip raw {
 chain PREROUTING {
  ip daddr 172.30.1.2 iifname != "br-aaaaaaaaaaaa" counter packets 0 bytes 0 drop
 }
}
table ip filter {
 chain INPUT {
  tcp dport 22 counter packets 0 bytes 0 accept
 }
 chain DOCKER {
  ip daddr 172.30.1.2 iifname != "br-aaaaaaaaaaaa" oifname "br-aaaaaaaaaaaa" tcp dport 80 counter packets 0 bytes 0 accept
  iifname != "br-aaaaaaaaaaaa" oifname "br-aaaaaaaaaaaa" counter packets 0 bytes 0 drop
 }
 chain DOCKER-BRIDGE {
  oifname "br-aaaaaaaaaaaa" counter packets 0 bytes 0 jump DOCKER
 }
 chain DOCKER-CT {
  oifname "br-aaaaaaaaaaaa" ct state related,established counter packets 0 bytes 0 accept
 }
 chain DOCKER-FORWARD {
  iifname "br-aaaaaaaaaaaa" counter packets 0 bytes 0 accept
 }
 chain DOCKER-INTERNAL {
 }
}
table ip nat {
 chain POSTROUTING {
  ip saddr 172.30.1.0/24 oifname != "br-aaaaaaaaaaaa" counter packets 0 bytes 0 masquerade
 }
 chain DOCKER {
  iifname != "br-aaaaaaaaaaaa" tcp dport 4080 counter packets 0 bytes 0 dnat to 172.30.1.2:80
 }
}
'''
    return {"version": 1, "containers": [edge], "networks": [network]}, iptables, nft


class NetworkReleaseV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.before, self.after = [Path(self.temp.name) / name for name in ("before", "after")]
        data, ipt, nft = fixture()
        for folder in (self.before, self.after):
            folder.mkdir()
            for name in gate.REQUIRED:
                (folder / name).write_text("")
            (folder / "network-ownership.json").write_text(json.dumps(data))
            (folder / "iptables.txt").write_text(ipt)
            (folder / "nft-ruleset.txt").write_text(nft)
            (folder / "listeners.txt").write_text('tcp LISTEN 0 4096 0.0.0.0:4080 0.0.0.0:* users:(("docker-proxy",pid=<dynamic>,fd=8))\ntcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=<dynamic>,fd=6))\n')
        self.manifest = {"version": 2, "release_commit": "c" * 40, "config_changes": [], "network_changes": [], "edge_binding_change": None}

    def load(self, folder):
        return json.loads((folder / "network-ownership.json").read_text())

    def write_after(self, data):
        (self.after / "network-ownership.json").write_text(json.dumps(data))
        before = {row["name"]: row for row in self.load(self.before)["networks"]}
        after = {row["name"]: row for row in data["networks"]}
        self.manifest["network_changes"] = [{"name": name, "before": policy.digest(before[name]) if name in before else None, "after": policy.digest(after[name]) if name in after else None} for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]

    def result(self):
        return gate.compare(self.before, self.after, self.manifest)

    def denied(self):
        try:
            self.assertEqual(self.result()["result"], "FAIL")
        except gate.GateError:
            pass

    def move_ip(self):
        data = self.load(self.after)
        data["containers"][0]["networks"][0]["ipv4"] = "172.30.1.9"
        data["networks"][0]["containers"][0]["ipv4"] = "172.30.1.9/24"
        self.write_after(data)
        for filename in ("iptables.txt", "nft-ruleset.txt"):
            path = self.after / filename
            path.write_text(path.read_text().replace("172.30.1.2", "172.30.1.9"))

    def loopback(self):
        self.manifest["edge_binding_change"] = {"container": "kairos-edge-1", "container_port": "80/tcp", "host_port": "4080", "before": ["0.0.0.0"], "after": ["127.0.0.1"]}
        data = self.load(self.after)
        data["containers"][0]["bindings"][0]["host_ip"] = "127.0.0.1"
        self.write_after(data)
        path = self.after / "iptables.txt"
        path.write_text(path.read_text().replace('-A DOCKER ! -i br-aaaaaaaaaaaa -p tcp', '-A DOCKER -d 127.0.0.1/32 ! -i br-aaaaaaaaaaaa -p tcp').replace(':PREROUTING ACCEPT [0:0]\n', ':PREROUTING ACCEPT [0:0]\n-A PREROUTING -d 127.0.0.1/32 ! -i lo -p tcp -m tcp --dport 4080 -j DROP\n'))
        path = self.after / "nft-ruleset.txt"
        path.write_text(path.read_text().replace('  iifname != "br-aaaaaaaaaaaa" tcp dport 4080', '  ip daddr 127.0.0.1 iifname != "br-aaaaaaaaaaaa" tcp dport 4080').replace(' chain PREROUTING {\n', ' chain PREROUTING {\n  ip daddr 127.0.0.1 iifname != "lo" tcp dport 4080 counter packets 0 bytes 0 drop\n'))
        path = self.after / "listeners.txt"
        path.write_text(path.read_text().replace('0.0.0.0:4080', '127.0.0.1:4080'))

    def test_unchanged_baseline_passes_without_network_exceptions(self):
        self.assertEqual(self.result()["result"], "PASS")
        self.assertFalse(self.result()["firewall_exceptions"])

    def test_exclusive_ip_change_passes_both_firewall_views(self):
        self.move_ip()
        self.assertEqual(self.result()["result"], "PASS")
        self.assertEqual(self.result()["network_attribution"]["rules"]["iptables.txt"]["before"], 8)

    def test_exact_edge_loopback_passes(self):
        self.loopback()
        self.assertEqual(self.result()["result"], "PASS")

    def test_foreign_listener_cannot_hide_in_edge_exception(self):
        self.loopback()
        path = self.after / "listeners.txt"
        path.write_text(path.read_text().replace('0.0.0.0:22', '127.0.0.1:22'))
        self.denied()

    def test_foreign_global_firewall_change_and_broad_accept_fail(self):
        self.move_ip()
        for filename, line in (("iptables.txt", "-A DOCKER-FORWARD -s 172.30.1.0/24 -j ACCEPT\n"), ("nft-ruleset.txt", "  ip saddr 172.30.1.0/24 counter packets 0 bytes 0 accept\n")):
            original = (self.after / filename).read_text()
            (self.after / filename).write_text(original + line)
            self.denied()
            (self.after / filename).write_text(original.replace("dport 22", "dport 23"))
            self.denied()
            (self.after / filename).write_text(original)

    def test_missing_or_duplicate_protection_rule_fails(self):
        self.move_ip()
        path = self.after / "iptables.txt"
        original = path.read_text()
        rule = '-A DOCKER-FORWARD -i br-aaaaaaaaaaaa -j ACCEPT\n'
        path.write_text(original.replace(rule, ""))
        self.denied()
        path.write_text(original.replace(rule, rule * 2))
        self.denied()

    def test_alien_or_shared_bridge_endpoint_is_not_authorized(self):
        self.move_ip()
        data = self.load(self.after)
        alien = copy.deepcopy(data["containers"][0])
        alien.update(id="f" * 64, name="/foreign", project="foreign", bindings=[])
        data["containers"].append(alien)
        data["networks"][0]["containers"].append({"id": alien["id"], "name": "foreign", "ipv4": "172.30.1.9/24", "ipv6": ""})
        self.write_after(data)
        self.denied()

    def test_foreign_subnet_overlap_and_nonreciprocal_endpoint_fail(self):
        self.move_ip()
        original = self.load(self.after)
        data = copy.deepcopy(original)
        foreign = copy.deepcopy(data["networks"][0])
        foreign.update(id="f" * 64, name="foreign-network", project="foreign", containers=[])
        data["networks"].append(foreign)
        self.write_after(data)
        self.denied()
        original["containers"][0]["networks"][0]["ipv4"] = "172.30.1.10"
        self.write_after(original)
        self.denied()

    def test_unlisted_network_change_and_other_binding_fail(self):
        self.move_ip()
        self.manifest["network_changes"] = []
        self.denied()
        data = self.load(self.after)
        data["containers"][0]["bindings"][0]["host_port"] = "5000"
        self.write_after(data)
        self.denied()

    def test_nft_own_accept_in_foreign_chain_fails(self):
        self.move_ip()
        path = self.after / "nft-ruleset.txt"
        path.write_text(path.read_text().replace(' chain INPUT {\n', ' chain INPUT {\n  iifname "br-aaaaaaaaaaaa" counter packets 0 bytes 0 accept\n'))
        self.denied()

    def test_new_internal_parser_network_has_complete_isolation_rules(self):
        data = self.load(self.after)
        net = {"id": "c" * 64, "name": "kairos-parser", "project": "kairos", "driver": "bridge", "internal": True, "bridge_option": None, "bridge_options": {}, "subnets": [{"subnet": "172.30.2.0/24", "gateway": "172.30.2.1"}], "containers": [{"id": "d" * 64, "name": "kairos-parser-1", "ipv4": "172.30.2.2/24", "ipv6": ""}]}
        container = {"id": "d" * 64, "name": "/kairos-parser-1", "project": "kairos", "bindings": [], "networks": [{"id": net["id"], "name": net["name"], "ipv4": "172.30.2.2", "ipv6": ""}]}
        data["networks"].append(net)
        data["containers"].append(container)
        self.write_after(data)
        path = self.after / "iptables.txt"
        original = path.read_text()
        addition = "-A DOCKER-FORWARD -i br-cccccccccccc -o br-cccccccccccc -j ACCEPT\n-A DOCKER-INTERNAL ! -s 172.30.2.0/24 -o br-cccccccccccc -j DROP\n-A DOCKER-INTERNAL ! -d 172.30.2.0/24 -i br-cccccccccccc -j DROP\n"
        path.write_text(original.replace("-A DOCKER-FORWARD -i br-aaaaaaaaaaaa -j ACCEPT\n", "-A DOCKER-FORWARD -i br-aaaaaaaaaaaa -j ACCEPT\n" + addition))
        path = self.after / "nft-ruleset.txt"
        path.write_text(path.read_text().replace(' chain DOCKER-FORWARD {\n', ' chain DOCKER-FORWARD {\n  iifname "br-cccccccccccc" oifname "br-cccccccccccc" counter packets 0 bytes 0 accept\n').replace(' chain DOCKER-INTERNAL {\n', ' chain DOCKER-INTERNAL {\n  ip saddr != 172.30.2.0/24 oifname "br-cccccccccccc" counter packets 0 bytes 0 drop\n  ip daddr != 172.30.2.0/24 iifname "br-cccccccccccc" counter packets 0 bytes 0 drop\n'))
        self.assertEqual(self.result()["result"], "PASS")
        path = self.after / "iptables.txt"
        path.write_text(path.read_text().replace("-i br-cccccccccccc -o br-cccccccccccc -j ACCEPT", "-i br-cccccccccccc -j ACCEPT"))
        self.denied()

    def test_owned_rule_cannot_cross_docker_global_jumps(self):
        self.move_ip()
        for filename, marker, jump, own_rule in (
            ("iptables.txt", "-A DOCKER-FORWARD -i br-aaaaaaaaaaaa -j ACCEPT\n", "-A DOCKER-FORWARD -j DOCKER-CT\n", "-A DOCKER-FORWARD -i br-aaaaaaaaaaaa -j ACCEPT\n"),
            ("nft-ruleset.txt", '  iifname "br-aaaaaaaaaaaa" counter packets 0 bytes 0 accept\n', '  counter packets 0 bytes 0 jump DOCKER-CT\n', '  iifname "br-aaaaaaaaaaaa" counter packets 0 bytes 0 accept\n'),
        ):
            original = [(folder / filename).read_text() for folder in (self.before, self.after)]
            for folder, text in zip((self.before, self.after), original):
                (folder / filename).write_text(text.replace(marker, jump + marker))
            self.assertEqual(self.result()["result"], "PASS")
            path = self.after / filename
            path.write_text(path.read_text().replace(jump + own_rule, own_rule + jump))
            self.denied()
            for folder, text in zip((self.before, self.after), original):
                (folder / filename).write_text(text)

    def test_foreign_container_on_edge_port_is_ambiguous(self):
        self.loopback()
        for folder in (self.before, self.after):
            data = self.load(folder)
            data["containers"].append({"id": "f" * 64, "name": "/foreign-proxy", "project": "foreign", "networks": [], "bindings": [{"container_port": "80/tcp", "host_ip": "::", "host_port": "4080"}]})
            (folder / "network-ownership.json").write_text(json.dumps(data))
        self.denied()

    def test_loopback_subnet_cannot_be_claimed_as_private_docker_network(self):
        data = self.load(self.after)
        data = json.loads(json.dumps(data).replace("172.30.1.", "127.30.1."))
        self.write_after(data)
        for name in ("iptables.txt", "nft-ruleset.txt"):
            path = self.after / name
            path.write_text(path.read_text().replace("172.30.1.", "127.30.1."))
        self.denied()

    def test_foreign_project_with_kairos_name_cannot_hide_restart(self):
        for folder in (self.before, self.after):
            data = self.load(folder)
            data["containers"].append({"id": "f" * 64, "name": "/kairos-foreign", "project": "other", "networks": [], "bindings": []})
            (folder / "network-ownership.json").write_text(json.dumps(data))
            (folder / "container-identities.txt").write_text("f" * 64 + "|/kairos-foreign|running|before|0|other|web|hash|config\n")
        path = self.after / "container-identities.txt"
        path.write_text(path.read_text().replace("|before|0|", "|after|1|"))
        self.denied()

    def test_negated_or_quoted_port_is_not_a_disjoint_global_barrier(self):
        self.move_ip()
        path_before = self.before / "iptables.txt"
        path_after = self.after / "iptables.txt"
        original = [path.read_text() for path in (path_before, path_after)]
        for barrier in (
            "-A DOCKER -p tcp -m tcp ! --dport 8080 -j RETURN\n",
            '-A DOCKER -m comment --comment "not a selector --dport 8080 " -j RETURN\n',
        ):
            with self.subTest(barrier=barrier):
                for index, (path, text, ip) in enumerate(zip(
                    (path_before, path_after), original, ("172.30.1.2", "172.30.1.9")
                )):
                    own = f"-A DOCKER ! -i br-aaaaaaaaaaaa -p tcp -m tcp --dport 4080 -j DNAT --to-destination {ip}:80\n"
                    path.write_text(text.replace(own, barrier + own if index == 0 else own + barrier))
                self.denied()

    def test_owned_port_accept_cannot_move_after_its_bridge_drop(self):
        self.move_ip()
        for filename, accept, drop in (
            ("iptables.txt",
             "-A DOCKER -d 172.30.1.9/32 ! -i br-aaaaaaaaaaaa -o br-aaaaaaaaaaaa -p tcp -m tcp --dport 80 -j ACCEPT\n",
             "-A DOCKER ! -i br-aaaaaaaaaaaa -o br-aaaaaaaaaaaa -j DROP\n"),
            ("nft-ruleset.txt",
             '  ip daddr 172.30.1.9 iifname != "br-aaaaaaaaaaaa" oifname "br-aaaaaaaaaaaa" tcp dport 80 counter packets 0 bytes 0 accept\n',
             '  iifname != "br-aaaaaaaaaaaa" oifname "br-aaaaaaaaaaaa" counter packets 0 bytes 0 drop\n'),
        ):
            with self.subTest(filename=filename):
                path = self.after / filename
                original = path.read_text()
                self.assertIn(accept + drop, original)
                path.write_text(original.replace(accept + drop, drop + accept))
                self.denied()
                path.write_text(original)

    def test_captured_real_baseline_compares_with_itself(self):
        evidence = Path(os.environ.get("KAIROS_NETWORK_BASELINE_DIR", ROOT.parent / "evidencias"))
        if not (evidence / "p0p2-network-network-ownership.json").exists():
            self.skipTest("Captured redacted VPS network baseline is external to the repository")
        for name in ("network-ownership.json", "iptables.txt", "ip6tables.txt", "nft-ruleset.txt", "listeners.txt"):
            text = (evidence / ("p0p2-network-" + name)).read_text(encoding="utf-8-sig")
            for folder in (self.before, self.after):
                (folder / name).write_text(text, encoding="utf-8")
        self.assertEqual(self.result()["result"], "PASS")
        # Simulate container replacement with retained endpoint IPs: validate real Docker templates.
        data = self.load(self.after)
        api = next(row for row in data["containers"] if row["name"] == "/kairos-api-1")
        old_id = api["id"]
        api["id"] = "e" * 64
        for net in data["networks"]:
            for endpoint in net["containers"]:
                if endpoint["id"] == old_id:
                    endpoint["id"] = api["id"]
        self.write_after(data)
        self.assertEqual(self.result()["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
