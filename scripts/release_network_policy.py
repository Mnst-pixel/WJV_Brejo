"""Fail-closed attribution of exact Docker bridge rules; never changes host networking."""
import hashlib
import ipaddress
import json
import re
import shlex
from collections import Counter

OWN = re.compile(r"^/?kairos(?:[-_]|$)")
SHA = re.compile(r"[a-f0-9]{64}")
C = "counter packets COUNTER bytes COUNTER"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def owned(row):
    return row.get("project") == "kairos" and bool(OWN.match(row.get("name", "")))


def bridge(row):
    return row.get("bridge_option") or "br-" + row["id"][:12]


def projection(value):
    if set(value) != {"version", "containers", "networks"} or value["version"] != 1:
        raise ValueError("invalid_ownership_schema")
    maps = {}
    for kind in ("containers", "networks"):
        rows = value[kind]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not SHA.fullmatch(row.get("id", "")) or not isinstance(row.get("name"), str) for row in rows):
            raise ValueError("invalid_ownership_identity")
        if len({row["id"] for row in rows}) != len(rows) or len({row["name"] for row in rows}) != len(rows):
            raise ValueError("duplicate_ownership_identity")
        maps[kind] = {row["id"]: row for row in rows}
    networks, containers = maps["networks"], maps["containers"]
    for net in networks.values():
        if not owned(net):
            continue
        if net.get("driver") != "bridge" or type(net.get("internal")) is not bool or net.get("bridge_option") not in (None, "", "br-" + net["id"][:12]) or net.get("bridge_options"):
            raise ValueError("unsupported_or_ambiguous_owned_bridge")
        if not isinstance(net.get("subnets"), list) or len(net["subnets"]) != 1:
            raise ValueError("unsupported_owned_subnets")
        subnet = ipaddress.ip_network(net["subnets"][0]["subnet"], strict=True)
        private_ranges = [ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
        if subnet.version != 4 or subnet.prefixlen < 16 or not any(subnet.subnet_of(scope) for scope in private_ranges):
            raise ValueError("unsupported_owned_address_family_or_scope")
        if ipaddress.ip_address(net["subnets"][0]["gateway"]) not in subnet:
            raise ValueError("invalid_owned_gateway")
        endpoint_ids, endpoint_ips = set(), set()
        for endpoint in net["containers"]:
            container = containers.get(endpoint["id"])
            if not container or not owned(container) or endpoint["name"] != container["name"].lstrip("/"):
                raise ValueError("shared_or_alien_endpoint")
            address = ipaddress.ip_interface(endpoint["ipv4"])
            if endpoint.get("ipv6") or address.network != subnet or endpoint["id"] in endpoint_ids or str(address.ip) in endpoint_ips:
                raise ValueError("ambiguous_network_endpoint")
            endpoint_ids.add(endpoint["id"])
            endpoint_ips.add(str(address.ip))
            matching = [item for item in container["networks"] if item["id"] == net["id"] and item["name"] == net["name"] and item["ipv4"] == str(address.ip) and not item.get("ipv6")]
            if len(matching) != 1:
                raise ValueError("nonreciprocal_network_endpoint")
    for container in containers.values():
        if not owned(container):
            continue
        if not isinstance(container.get("bindings"), list) or not isinstance(container.get("networks"), list):
            raise ValueError("invalid_container_projection")
        for attachment in container["networks"]:
            net = networks.get(attachment["id"])
            if not net or not owned(net) or net["name"] != attachment["name"]:
                raise ValueError("owned_container_on_foreign_or_unknown_network")
            if attachment.get("ipv4") and not any(item["id"] == container["id"] for item in net["containers"]):
                raise ValueError("missing_reciprocal_endpoint")
    return maps


def firewall_entries(lines, nft):
    table = chain = None
    for line in lines:
        clean = line.strip()
        if nft:
            found = re.fullmatch(r"table (\w+) ([\w-]+) \{", clean)
            if found:
                table = found[1] + ":" + found[2]
            elif found := re.fullmatch(r"chain ([\w-]+) \{", clean):
                chain = found[1]
            elif clean == "}":
                if chain is not None:
                    chain = None
                else:
                    table = None
            yield (table, chain, clean), line
        else:
            if clean.startswith("*"):
                table = "ip:" + clean[1:]
            found = re.match(r"-A ([\w-]+) ", clean)
            yield (table, found[1] if found else None, clean), line


def templates(maps, names, iptables):
    ipt, nft = {}, {}
    def add(table, chain, iprule, nftrule, owner):
        ipt[("ip:" + table, chain, f"-A {chain} {iprule}")] = owner
        nft[("ip:" + table, chain, nftrule)] = owner
    for net in maps["networks"].values():
        if net["name"] not in names:
            continue
        br = bridge(net)
        subnet = net["subnets"][0]["subnet"]
        name = net["name"]
        if net["internal"]:
            add("filter", "DOCKER-FORWARD", f"-i {br} -o {br} -j ACCEPT", f'iifname "{br}" oifname "{br}" {C} accept', name)
            add("filter", "DOCKER-INTERNAL", f"! -s {subnet} -o {br} -j DROP", f'ip saddr != {subnet} oifname "{br}" {C} drop', name)
            add("filter", "DOCKER-INTERNAL", f"! -d {subnet} -i {br} -j DROP", f'ip daddr != {subnet} iifname "{br}" {C} drop', name)
        else:
            add("filter", "DOCKER", f"! -i {br} -o {br} -j DROP", f'iifname != "{br}" oifname "{br}" {C} drop', name)
            add("filter", "DOCKER-BRIDGE", f"-o {br} -j DOCKER", f'oifname "{br}" {C} jump DOCKER', name)
            add("filter", "DOCKER-CT", f"-o {br} -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT", f'oifname "{br}" ct state related,established {C} accept', name)
            add("filter", "DOCKER-FORWARD", f"-i {br} -j ACCEPT", f'iifname "{br}" {C} accept', name)
            add("nat", "POSTROUTING", f"-s {subnet} ! -o {br} -j MASQUERADE", f'ip saddr {subnet} oifname != "{br}" {C} masquerade', name)
            for endpoint in net["containers"]:
                ip = str(ipaddress.ip_interface(endpoint["ipv4"]).ip)
                add("raw", "PREROUTING", f"-d {ip}/32 ! -i {br} -j DROP", f'ip daddr {ip} iifname != "{br}" {C} drop', name)
    actual = Counter(key for key, _ in firewall_entries(iptables, False))
    for container in maps["containers"].values():
        if not owned(container) or not container["bindings"]:
            continue
        if not any(item["name"] in names for item in container["networks"]):
            continue
        # The phase-2 release permits only the known edge's existing target, never a new port.
        if container["name"] != "/kairos-edge-1":
            raise ValueError("unsupported_owned_binding")
        for binding in container["bindings"]:
            host = binding["host_ip"]
            if binding["container_port"] != "80/tcp" or binding["host_port"] != "4080" or host not in {"0.0.0.0", "127.0.0.1", "::"}:
                raise ValueError("unsupported_edge_binding")
            if host == "::":
                continue  # No IPv6 endpoint: userland listener removal only; ip6tables stays exact.
            prefix = "-d 127.0.0.1/32 " if host == "127.0.0.1" else ""
            nfprefix = "ip daddr 127.0.0.1 " if host == "127.0.0.1" else ""
            candidates = []
            for attachment in container["networks"]:
                net = maps["networks"][attachment["id"]]
                if net["name"] not in names or net["internal"] or not attachment["ipv4"]:
                    continue
                br = bridge(net)
                ip = attachment["ipv4"]
                body = f"{prefix}! -i {br} -p tcp -m tcp --dport 4080 -j DNAT --to-destination {ip}:80"
                if actual[("ip:nat", "DOCKER", "-A DOCKER " + body)] == 1:
                    candidates.append((net, br, ip, body))
            if len(candidates) != 1:
                raise ValueError("ambiguous_or_missing_edge_dnat")
            net, br, ip, body = candidates[0]
            add("nat", "DOCKER", body, f'{nfprefix}iifname != "{br}" tcp dport 4080 {C} dnat to {ip}:80', net["name"])
            add("filter", "DOCKER", f"-d {ip}/32 ! -i {br} -o {br} -p tcp -m tcp --dport 80 -j ACCEPT", f'ip daddr {ip} iifname != "{br}" oifname "{br}" tcp dport 80 {C} accept', net["name"])
            if host == "127.0.0.1":
                add("raw", "PREROUTING", "-d 127.0.0.1/32 ! -i lo -p tcp -m tcp --dport 4080 -j DROP", f'ip daddr 127.0.0.1 iifname != "lo" tcp dport 4080 {C} drop', "kairos-edge-binding")
    return ipt, nft



def barrier_positions(entries, expected, all_networks, nft):
    """Own rules may not cross a global/custom rule that can match the same traffic."""
    protected_names = set(expected.values())
    bridges = {bridge(net) for net in all_networks if net["name"] in protected_names}
    subnets = [ipaddress.ip_network(net["subnets"][0]["subnet"]) for net in all_networks if net["name"] in protected_names]
    counters, positions, unknown = Counter(), {}, set()

    def positive(line, dimension):
        # Parse quoting before selectors: a comment containing '--dport 8080'
        # is not proof that a global rule cannot match the edge's port 4080.
        tokens = shlex.split(line)
        if nft:
            selector = {"i": ["iifname"], "o": ["oifname"], "s": ["ip", "saddr"], "d": ["ip", "daddr"], "port": ["tcp", "dport"]}[dimension]
        else:
            selector = [{"i": "-i", "o": "-o", "s": "-s", "d": "-d", "port": "--dport"}[dimension]]
        for index in range(len(tokens) - len(selector)):
            if tokens[index:index + len(selector)] != selector:
                continue
            if index and tokens[index - 1] in {"!", "comment", "--comment"}:
                continue
            value = tokens[index + len(selector)]
            if value in {"!", "!=", "=="}:
                continue
            pattern = r"\d+" if dimension == "port" else r"[0-9./]+" if dimension in {"s", "d"} else r"[A-Za-z0-9_.:-]+"
            if re.fullmatch(pattern, value):
                return value
        return None

    def disjoint(table, chain, line):
        if table == "ip:filter" and chain in {"DOCKER", "DOCKER-BRIDGE", "DOCKER-CT", "DOCKER-FORWARD"}:
            interface = positive(line, "i" if chain == "DOCKER-FORWARD" else "o")
            # Only a known other Docker bridge is provably disjoint, never a negated selector.
            foreign = {bridge(net) for net in all_networks if net.get("driver") == "bridge" and net["name"] not in protected_names}
            return interface in foreign and interface not in bridges
        if table == "ip:filter" and chain == "DOCKER-INTERNAL":
            return line.endswith(" drop" if nft else " -j DROP")  # DROP commutes with the exact owned DROP rules.
        if (table, chain) in {("ip:raw", "PREROUTING"), ("ip:nat", "POSTROUTING")}:
            dimension = "d" if table == "ip:raw" else "s"
            address = positive(line, dimension)
            if address:
                scope = ipaddress.ip_network(address, strict=False)
                protected = subnets + ([ipaddress.ip_network("127.0.0.1/32")] if table == "ip:raw" else [])
                if all(not scope.overlaps(net) for net in protected):
                    return True
                if table == "ip:raw" and address in {"127.0.0.1", "127.0.0.1/32"}:
                    port = positive(line, "port")
                    return port is not None and port != "4080"
        if (table, chain) == ("ip:nat", "DOCKER"):
            port = positive(line, "port")
            return port is not None and port != "4080"
        return False

    for key, _ in entries:
        table, chain, line = key
        if chain is None or not line or (nft and (line.startswith(("chain ", "type ", "policy ", "#")) or line == "}")):
            continue
        scope = table, chain
        if key in expected:
            positions.setdefault((expected[key], *scope), set()).add(counters[scope])
        elif not disjoint(table, chain, line):
            counters[scope] += 1
            prefix = (f"{C} jump " if nft else "-A DOCKER-FORWARD -j ")
            target = line.removeprefix(prefix)
            if chain != "DOCKER-FORWARD" or not line.startswith(prefix) or target not in {"DOCKER-CT", "DOCKER-INTERNAL", "DOCKER-BRIDGE"}:
                unknown.add(scope)
    return counters, positions, unknown

def evaluate(before, after, manifest, inventories, normalize):
    maps = [projection(value) for value in (before, after)]
    permitted = manifest["network_changes"]
    if not isinstance(permitted, list):
        raise ValueError("invalid_network_changes")
    nets = [{row["name"]: row for row in side["networks"].values()} for side in maps]
    allowed = set()
    for change in permitted:
        if not isinstance(change, dict) or set(change) != {"name", "before", "after"} or not isinstance(change["name"], str) or not OWN.match(change["name"]):
            raise ValueError("invalid_network_change")
        name = change["name"]
        if name in allowed or change["before"] == change["after"]:
            raise ValueError("duplicate_or_unobserved_network_change")
        for index, key in enumerate(("before", "after")):
            row = nets[index].get(name)
            if row is not None and not owned(row):
                raise ValueError("foreign_network_change")
            expected = digest(row) if row else None
            if change[key] != expected or (change[key] is not None and not SHA.fullmatch(change[key])):
                raise ValueError("network_projection_hash_mismatch")
        if name not in nets[0] and (name not in nets[1] or not nets[1][name]["internal"]):
            raise ValueError("new_network_must_be_internal")
        allowed.add(name)
    # Every projected network change must be explicitly reviewed, including endpoint IPs/IDs.
    for name in nets[0].keys() | nets[1].keys():
        if nets[0].get(name) != nets[1].get(name) and name not in allowed:
            raise ValueError("unlisted_network_change")
    all_nets = [row for side in maps for row in side["networks"].values()]
    for net in all_nets:
        if not owned(net):
            continue
        own_range = ipaddress.ip_network(net["subnets"][0]["subnet"])
        for other in all_nets:
            if other["name"] == net["name"] and owned(other):
                continue
            if bridge(other) == bridge(net):
                raise ValueError("ambiguous_bridge_identity")
            for allocation in other.get("subnets", []):
                if allocation.get("subnet"):
                    other_range = ipaddress.ip_network(allocation["subnet"])
                    if own_range.version == other_range.version and own_range.overlaps(other_range):
                        raise ValueError("overlapping_network_ownership")
    edge = manifest["edge_binding_change"]
    if edge is not None and (not isinstance(edge, dict) or set(edge) != {"container", "container_port", "host_port", "before", "after"} or edge["container"] != "kairos-edge-1" or edge["container_port"] != "80/tcp" or edge["host_port"] != "4080" or edge["before"] not in (["0.0.0.0"], ["0.0.0.0", "::"]) or edge["after"] != ["127.0.0.1"]):
        raise ValueError("invalid_edge_binding_exception")
    containers = [{row["name"]: row for row in side["containers"].values()} for side in maps]
    for name in containers[0].keys() | containers[1].keys():
        rows = [side.get(name) for side in containers]
        if not all(row is None or owned(row) for row in rows):
            if rows[0] != rows[1]:
                raise ValueError("foreign_container_projection_changed")
            continue
        bindings = [row.get("bindings", []) if row else [] for row in rows]
        if name == "/kairos-edge-1" and edge:
            for side in containers:
                for other_name, other in side.items():
                    if other_name != name and any(binding.get("host_port") == "4080" and binding.get("container_port", "").endswith("/tcp") for binding in other.get("bindings", [])):
                        raise ValueError("edge_listener_shared_with_other_container")
            for index, key in enumerate(("before", "after")):
                expected = [{"container_port": "80/tcp", "host_port": "4080", "host_ip": ip} for ip in edge[key]]
                if bindings[index] != expected:
                    raise ValueError("edge_binding_projection_mismatch")
                allowed.update(item["name"] for item in rows[index]["networks"])
        elif bindings[0] != bindings[1]:
            raise ValueError("unapproved_container_binding_change")
    if edge and "/kairos-edge-1" not in containers[0]:
        raise ValueError("missing_known_edge")
    result = {"failures": [], "firewalls": {}, "listeners": inventories["listeners.txt"], "audit": {"networks": sorted(allowed), "rules": {}}}
    result["audit"]["ownership"] = {
        key: [{"name": net["name"], "network_id": net["id"], "bridge": bridge(net),
            "subnets": net["subnets"], "endpoints": net["containers"], "projection_sha256": digest(net)}
            for net in side["networks"].values() if net["name"] in allowed]
        for key, side in zip(("before", "after"), maps)
    }
    specs = [templates(side, allowed, normalize(inventories["iptables.txt"][index], False)) for index, side in enumerate(maps)]
    for filename, position in (("iptables.txt", 0), ("nft-ruleset.txt", 1)):
        remainder = []
        counts = []
        anchors = []
        for index in (0, 1):
            entries = list(firewall_entries(normalize(inventories[filename][index], position == 1), position == 1))
            actual = Counter(key for key, _ in entries)
            expected = specs[index][position]
            anchors.append(barrier_positions(entries, expected, all_nets, position == 1))
            # Rules of different bridges can be disjoint; the port ACCEPT and
            # fallback DROP for the same bridge are not. Preserve that safety
            # relationship in each firewall view, even when both are attributed.
            dropped = set()
            for key, _ in entries:
                if key not in expected or key[:2] != ("ip:filter", "DOCKER"):
                    continue
                owner = expected[key]
                if key[2].endswith(" drop" if position else " -j DROP"):
                    dropped.add(owner)
                elif key[2].endswith(" accept" if position else " -j ACCEPT") and owner in dropped:
                    result["failures"].append(filename + ":owned_accept_after_bridge_drop")
            if any(actual[key] != 1 for key in expected):
                result["failures"].append(filename + ":missing_or_duplicate_expected_docker_rule")
            removed = [key for key, _ in entries if key in expected]
            counts.append(len(removed))
            remainder.append("\n".join(line for key, line in entries if key not in expected))
        for key, positions in anchors[1][1].items():
            scope = key[1:]
            previous = anchors[0][1].get(key)
            if previous is not None:
                valid = len(previous) == 1 and positions == previous
            else:
                valid = scope not in anchors[0][2] and scope not in anchors[1][2] and positions == {anchors[0][0][scope]}
            if not valid:
                result["failures"].append(filename + ":owned_rule_crosses_global_policy_barrier")
        result["firewalls"][filename] = remainder
        result["audit"]["rules"][filename] = {"before": counts[0], "after": counts[1],
            "authorized_before_sha256": digest(sorted(specs[0][position])),
            "authorized_after_sha256": digest(sorted(specs[1][position])),
            "protected_before_sha256": digest(remainder[0]), "protected_after_sha256": digest(remainder[1])}
    if edge:
        remaining = []
        for index, key in enumerate(("before", "after")):
            lines = inventories["listeners.txt"][index].splitlines()
            removed = []
            for ip in edge[key]:
                local = "[::]:4080" if ip == "::" else ip + ":4080"
                peer = "[::]:*" if ip == "::" else "0.0.0.0:*"
                pattern = rf'tcp\s+LISTEN\s+0\s+4096\s+{re.escape(local)}\s+{re.escape(peer)}\s+users:\(\("docker-proxy",pid=<dynamic>,fd=\d+\)\)\s*'
                matching = [line for line in lines if re.fullmatch(pattern, line)]
                if len(matching) != 1:
                    raise ValueError("ambiguous_edge_listener")
                removed += matching
            remaining.append("\n".join(line for line in lines if line not in removed))
        result["listeners"] = remaining
    return result
