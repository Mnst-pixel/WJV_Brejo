"""Predeclared Docker transitions; a receipt can fill identities, never policy.

This module does not deploy, change networking, or accept Docker commands.
Its output must still pass the existing full snapshot/firewall comparator.
"""
import copy
import importlib.util
import ipaddress
import re
from pathlib import Path


def sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = sibling("transition_network_policy", "release_network_policy.py")
gate = sibling("transition_snapshot_gate", "compare-release-snapshots.py")
SOCKET = "unix:///var/run/docker.sock"
SHA = re.compile(r"[a-f0-9]{64}")
COMMIT = re.compile(r"[a-f0-9]{40}")
NAME = re.compile(r"kairos[-_][a-z0-9_-]+")
CONFIG = {"driver", "internal", "subnets", "bridge_option", "bridge_options"}
CONTAINER = {"name", "operation", "previous_id", "service", "image", "revision", "bindings", "networks"}
NETWORK = {"name", "operation", "previous_id", "configuration"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def keyed(rows, fields=None):
    require(isinstance(rows, list) and len(rows) <= 10000, "invalid_rows")
    result = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("name"), str), "invalid_row")
        if fields:
            require(set(row) == fields, "unexpected_fields")
        name = row["name"].lstrip("/")
        require(name not in result, "duplicate_name")
        result[name] = row
    return result


def state(value):
    require(isinstance(value, dict) and set(value) == {"docker_socket", "projection", "runtime"} and value["docker_socket"] == SOCKET, "invalid_state_origin")
    policy.projection(value["projection"])
    containers = keyed(value["projection"]["containers"])
    runtime = keyed(value["runtime"], {"id", "name", "project", "service", "image", "revision"})
    require(containers.keys() == runtime.keys(), "runtime_inventory_mismatch")
    for name, row in runtime.items():
        require(row["id"] == containers[name]["id"] and row["project"] == containers[name]["project"], "runtime_identity_mismatch")
        require(isinstance(row["image"], str) and re.fullmatch(r"sha256:[a-f0-9]{64}", row["image"]), "runtime_image_missing")
    return containers, keyed(value["projection"]["networks"]), runtime


def configuration(row):
    return {field: row[field] for field in CONFIG}


def network_config(value):
    require(isinstance(value, dict) and set(value) == CONFIG, "invalid_network_configuration")
    require(value["driver"] == "bridge" and type(value["internal"]) is bool and value["bridge_option"] is None and value["bridge_options"] == {}, "unsupported_network_configuration")
    require(isinstance(value["subnets"], list) and len(value["subnets"]) == 1, "invalid_network_subnets")
    allocation = value["subnets"][0]
    require(isinstance(allocation, dict) and set(allocation) == {"subnet", "gateway"}, "invalid_network_allocation")
    subnet = ipaddress.ip_network(allocation["subnet"], strict=True)
    scopes = [ipaddress.ip_network(scope) for scope in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    require(subnet.version == 4 and 16 <= subnet.prefixlen <= 29 and any(subnet.subnet_of(scope) for scope in scopes), "network_outside_private_scope")
    gateway = ipaddress.ip_address(allocation["gateway"])
    require(gateway in subnet and gateway not in {subnet.network_address, subnet.broadcast_address}, "invalid_gateway")
    return subnet, gateway


def validate(plan, before):
    """Run before the first mutable operation; no future IDs are required."""
    containers, networks, runtime = state(before)
    require(isinstance(plan, dict) and set(plan) == {"version", "release_commit", "baseline_sha256", "docker_socket", "containers", "networks", "config_changes", "edge_binding_change"}, "invalid_plan_schema")
    require(plan["version"] == 1 and plan["docker_socket"] == SOCKET and COMMIT.fullmatch(plan["release_commit"] or ""), "invalid_plan_origin")
    require(plan["baseline_sha256"] == policy.digest(before), "baseline_hash_mismatch")
    try:
        gate.manifest_changes({"version": 2, "release_commit": plan["release_commit"], "config_changes": plan["config_changes"], "network_changes": [], "edge_binding_change": plan["edge_binding_change"]})
    except gate.GateError as error:
        raise ValueError(str(error)) from None
    edge = plan["edge_binding_change"]
    require(edge is None or (isinstance(edge, dict) and set(edge) == {"container", "container_port", "host_port", "before", "after"} and edge["container"] == "kairos-edge-1" and edge["container_port"] == "80/tcp" and edge["host_port"] == "4080" and edge["before"] in (["0.0.0.0"], ["0.0.0.0", "::"]) and edge["after"] == ["127.0.0.1"]), "invalid_edge_binding_exception")
    desired_nets = keyed(plan["networks"], NETWORK)
    desired_containers = keyed(plan["containers"], CONTAINER)
    for desired, observed in ((desired_nets, networks), (desired_containers, containers)):
        require({name for name, row in observed.items() if policy.owned(row)} <= desired.keys(), "missing_owned_resource")
        for name, item in desired.items():
            require(NAME.fullmatch(name) and item["name"] == name, "invalid_resource_name")
            old = observed.get(name)
            require(old is None or policy.owned(old), "foreign_resource_target")
            require(item["previous_id"] == (old["id"] if old else None), "wrong_previous_identity")
            require(item["operation"] in ({"retain", "replace", "remove"} if old else {"create"}), "invalid_identity_operation")
    for name, item in desired_nets.items():
        require(item["operation"] != "replace", "network_recreation_not_supported")
        if item["operation"] == "remove":
            require(item["configuration"] is None, "removed_network_has_configuration")
            continue
        network_config(item["configuration"])
        if item["operation"] == "retain":
            require(item["configuration"] == configuration(networks[name]), "retained_network_configuration_changed")
        else:
            require(item["configuration"]["internal"], "new_network_must_be_internal")
        candidate = ipaddress.ip_network(item["configuration"]["subnets"][0]["subnet"])
        # Include removed networks until the coordinator has completed cleanup.
        for other_name, row in networks.items():
            if name != other_name:
                for allocation in row.get("subnets", []):
                    if allocation.get("subnet"):
                        other = ipaddress.ip_network(allocation["subnet"])
                        require(candidate.version != other.version or not candidate.overlaps(other), "network_overlap")
        for other_name, other in desired_nets.items():
            if other_name != name and other["configuration"]:
                other_range = ipaddress.ip_network(other["configuration"]["subnets"][0]["subnet"])
                require(not candidate.overlaps(other_range), "planned_network_overlap")
    exact_addresses = set()
    for name, item in desired_containers.items():
        if item["operation"] == "remove":
            require(all(item[key] is None for key in ("service", "image", "revision")) and item["bindings"] == [] and item["networks"] == [], "removed_container_has_configuration")
            continue
        require(isinstance(item["service"], str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", item["service"]) and re.fullmatch(r"sha256:[a-f0-9]{64}", item["image"] or ""), "invalid_service_image")
        require(item["revision"] is None or COMMIT.fullmatch(item["revision"]), "invalid_image_revision")
        if item["service"] in {"api", "web", "worker", "beat", "parser"} and item["operation"] != "retain":
            require(item["revision"] == plan["release_commit"], "application_revision_mismatch")
        require(isinstance(item["bindings"], list), "invalid_bindings")
        for binding in item["bindings"]:
            require(isinstance(binding, dict) and set(binding) == {"container_port", "host_ip", "host_port"}, "invalid_binding")
        old_bindings = containers.get(name, {}).get("bindings", [])
        if name == "kairos-edge-1" and edge:
            for actual, key in ((old_bindings, "before"), (item["bindings"], "after")):
                require(actual == [{"container_port": "80/tcp", "host_port": "4080", "host_ip": ip} for ip in edge[key]], "edge_binding_plan_mismatch")
        else:
            require(item["bindings"] == old_bindings, "unapproved_binding_change")
        links = keyed(item["networks"], {"name", "ipv4"})
        for net_name, link in links.items():
            require(net_name in desired_nets and desired_nets[net_name]["operation"] != "remove", "unplanned_membership")
            subnet, gateway = network_config(desired_nets[net_name]["configuration"])
            if link["ipv4"] == "dynamic":
                require(item["operation"] in {"create", "replace"}, "retained_ip_must_be_exact")
            else:
                address = ipaddress.ip_address(link["ipv4"])
                require(address in subnet and address not in {subnet.network_address, subnet.broadcast_address, gateway}, "endpoint_outside_allocation")
                require((net_name, str(address)) not in exact_addresses, "duplicate_planned_address")
                exact_addresses.add((net_name, str(address)))
        if item["operation"] == "retain":
            old, identity = containers[name], runtime[name]
            require(all(item[key] == identity[key] for key in ("service", "image", "revision")) and item["bindings"] == old["bindings"], "retained_runtime_changed")
            require(links == {link["name"]: {"name": link["name"], "ipv4": link["ipv4"]} for link in old["networks"]}, "retained_membership_changed")
    return desired_containers, desired_nets


def bind(plan, before, after):
    """Derive exact v2 hashes only after every predeclared constraint matches."""
    desired_containers, desired_nets = validate(plan, before)
    old_containers, old_nets, old_runtime = state(before)
    containers, networks, runtime = state(after)
    allocations = {"containers": {}, "networks": {}}
    for kind, desired, old, actual in (("containers", desired_containers, old_containers, containers), ("networks", desired_nets, old_nets, networks)):
        expected_names = (old.keys() - desired.keys()) | {name for name, item in desired.items() if item["operation"] != "remove"}
        require(actual.keys() == expected_names, "unplanned_resource_set")
        for name in old.keys() - desired.keys():
            require(old[name] == actual[name], "foreign_resource_changed")
            if kind == "containers":
                require(old_runtime[name] == runtime[name], "foreign_runtime_changed")
        for name, item in desired.items():
            if item["operation"] == "remove":
                continue
            row = actual[name]
            require(policy.owned(row), "wrong_project_identity")
            if item["operation"] == "retain":
                require(row["id"] == item["previous_id"], "retained_identity_changed")
            else:
                require(row["id"] not in {value["id"] for value in old.values()}, "reused_previous_identity")
            allocations[kind][name] = row["id"]
            if kind == "networks":
                require(configuration(row) == item["configuration"], "network_configuration_mismatch")
                continue
            require(all(runtime[name][key] == item[key] for key in ("service", "image", "revision")), "runtime_artifact_mismatch")
            require(row["bindings"] == item["bindings"], "binding_mismatch")
            links = keyed(row["networks"])
            desired_links = keyed(item["networks"])
            require(links.keys() == desired_links.keys(), "membership_mismatch")
            for net_name, link in links.items():
                desired = desired_links[net_name]["ipv4"]
                subnet, gateway = network_config(desired_nets[net_name]["configuration"])
                actual_ip = ipaddress.ip_address(link["ipv4"])
                require(actual_ip in subnet and actual_ip not in {subnet.network_address, subnet.broadcast_address, gateway}, "dynamic_ip_outside_allocation")
                require(desired == "dynamic" or link["ipv4"] == desired, "exact_ip_mismatch")
    manifest = {"version": 2, "release_commit": plan["release_commit"], "config_changes": copy.deepcopy(plan["config_changes"]), "edge_binding_change": copy.deepcopy(plan["edge_binding_change"]), "network_changes": []}
    for name in sorted(old_nets.keys() | networks.keys()):
        if old_nets.get(name) != networks.get(name):
            manifest["network_changes"].append({"name": name, "before": policy.digest(old_nets[name]) if name in old_nets else None, "after": policy.digest(networks[name]) if name in networks else None})
    receipt = {"version": 1, "plan_sha256": policy.digest(plan), "before_sha256": policy.digest(before), "after_sha256": policy.digest(after), "docker_socket": SOCKET, "allocations": allocations, "manifest_sha256": policy.digest(manifest)}
    return manifest, receipt


def verify_receipt(plan, before, after, receipt):
    manifest, expected = bind(plan, before, after)
    require(receipt == expected, "receipt_mismatch")
    return manifest
