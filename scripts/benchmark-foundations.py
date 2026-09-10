#!/usr/bin/env python3
"""Bounded serial public-route baseline from the VPS loopback; no user data."""
import collections
import datetime
import http.client
import json
import math
import statistics
import subprocess
import time


def measure(path, samples=30):
    timings, statuses, sizes = [], collections.Counter(), []
    for index in range(samples + 2):
        connection = http.client.HTTPConnection("127.0.0.1", 4080, timeout=10)
        started = time.perf_counter()
        try:
            connection.request("GET", path, headers={"Host": "kairos.2-24-215-183.sslip.io", "X-Forwarded-Proto": "https"})
            response = connection.getresponse()
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise RuntimeError("benchmark_response_limit")
            if index >= 2:
                timings.append((time.perf_counter() - started) * 1000)
                statuses[response.status] += 1
                sizes.append(len(body))
        finally:
            connection.close()
        time.sleep(0.05)
    ordered = sorted(timings)
    return {"path": path, "samples": samples, "warmup": 2, "concurrency": 1,
            "p50_ms": round(statistics.median(ordered), 3), "p95_ms": round(ordered[math.ceil(samples * .95) - 1], 3),
            "status_counts": dict(statuses), "body_bytes_median": statistics.median(sizes)}


def main():
    projection = '{"image":{{json .Image}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}}}'
    output = subprocess.check_output(["docker", "--host", "unix:///var/run/docker.sock", "inspect", "--format", projection, "kairos-edge-1", "kairos-api-1"], text=True)
    containers = [json.loads(row) for row in output.splitlines()]
    for container, service in zip(containers, ("edge", "api")):
        if container.get("project") != "kairos" or container.get("service") != service:
            raise RuntimeError("benchmark_target_identity_mismatch")
    report = {"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope": "loopback HTTP public routes; not an authenticated workload or database query benchmark",
              "api_image": containers[1]["image"], "routes": []}
    for path in ("/api/health/live", "/api/health/ready", "/app", "/"):
        report["routes"].append(measure(path))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
