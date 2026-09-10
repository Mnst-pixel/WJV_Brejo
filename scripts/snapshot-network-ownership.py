#!/usr/bin/env python3
"""Read-only Docker projections for attribution; never inspect environment or command."""

import json
import subprocess


def output(args):
    return subprocess.check_output(
        args, text=True, stderr=subprocess.DEVNULL, timeout=30
    ).strip()


def collect(run=output):
    containers = []
    for identifier in run(["docker", "ps", "-aq", "--no-trunc"]).splitlines():
        template = '{"id":{{json .Id}},"name":{{json .Name}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"networks":{{json .NetworkSettings.Networks}},"bindings":{{json .HostConfig.PortBindings}}}'
        raw = json.loads(
            run(["docker", "container", "inspect", "--format", template, identifier])
        )
        containers.append(
            {
                "id": raw["id"],
                "name": raw["name"],
                "project": raw["project"],
                "networks": sorted(
                    [
                        {
                            "name": name,
                            "id": net.get("NetworkID"),
                            "ipv4": net.get("IPAddress"),
                            "ipv6": net.get("GlobalIPv6Address"),
                        }
                        for name, net in (raw["networks"] or {}).items()
                    ],
                    key=lambda item: item["name"],
                ),
                "bindings": sorted(
                    [
                        {
                            "container_port": port,
                            "host_ip": binding.get("HostIp"),
                            "host_port": binding.get("HostPort"),
                        }
                        for port, bindings in (raw["bindings"] or {}).items()
                        for binding in (bindings or [])
                    ],
                    key=lambda item: (
                        item["container_port"],
                        item["host_ip"],
                        item["host_port"],
                    ),
                ),
            }
        )
    networks = []
    for identifier in run(["docker", "network", "ls", "-q", "--no-trunc"]).splitlines():
        template = '{"id":{{json .Id}},"name":{{json .Name}},"driver":{{json .Driver}},"internal":{{json .Internal}},"project":{{json (index .Labels "com.docker.compose.project")}},"options":{{json .Options}},"ipam":{{json .IPAM.Config}},"containers":{{json .Containers}}}'
        raw = json.loads(
            run(["docker", "network", "inspect", "--format", template, identifier])
        )
        options = raw["options"] or {}
        networks.append(
            {
                "id": raw["id"],
                "name": raw["name"],
                "driver": raw["driver"],
                "internal": raw["internal"],
                "project": raw["project"],
                "bridge_option": options.get("com.docker.network.bridge.name"),
                "bridge_options": {
                    key: value
                    for key, value in options.items()
                    if key
                    in {
                        "com.docker.network.bridge.name",
                        "com.docker.network.bridge.enable_ip_masquerade",
                        "com.docker.network.bridge.enable_icc",
                        "com.docker.network.bridge.host_binding_ipv4",
                        "com.docker.network.bridge.inhibit_ipv4",
                        "com.docker.network.driver.mtu",
                    }
                },
                "subnets": sorted(
                    [
                        {"subnet": item.get("Subnet"), "gateway": item.get("Gateway")}
                        for item in (raw["ipam"] or [])
                    ],
                    key=lambda item: item["subnet"] or "",
                ),
                "containers": sorted(
                    [
                        {
                            "id": cid,
                            "name": item.get("Name"),
                            "ipv4": item.get("IPv4Address"),
                            "ipv6": item.get("IPv6Address"),
                        }
                        for cid, item in (raw["containers"] or {}).items()
                    ],
                    key=lambda item: item["id"],
                ),
            }
        )
    return {
        "version": 1,
        "containers": sorted(containers, key=lambda row: row["id"]),
        "networks": sorted(networks, key=lambda row: row["id"]),
    }


if __name__ == "__main__":
    print(json.dumps(collect(), sort_keys=True, indent=2))
