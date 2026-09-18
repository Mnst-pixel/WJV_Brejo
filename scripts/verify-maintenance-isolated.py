"""Exercise a maintenance response without publishing ports or touching live services."""
import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import subprocess
import sys
import tarfile

REVISION = "c12e53a7416902315391d1b8c0a48603cbb1db6e"
ARCHIVE_SHA = "0f147ae327c9c26ccb9e84574f763af448a8148ef0c7ad0c94cb7c9b1d81311a"
EDGE = "sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648"
WEB = "sha256:651bf1767d3a6d90924e212bf7579dadd8196e53a2e7c20c42f6a02d7cef6824"
DOCKER = ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent",
       "DOCKER_HOST": "unix:///var/run/docker.sock", "COMPOSE_PROJECT_NAME": "kairos",
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
IDENTITY = '{"name":{{json .Name}},"image":{{json .Image}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"run":{{json (index .Config.Labels "com.kairos.maintenance.probe")}}}'
CLIENT = r"""
const expected = 'Kairós está em manutenção. Os dados já salvos permanecem preservados. Tente novamente em alguns minutos.';
async function request(path,method) {
  const r=await fetch('http://127.0.0.1:80'+path,{method,redirect:'manual',signal:AbortSignal.timeout(2000),
    headers:{'Content-Type':'application/json'},...(method==='POST'?{body:'{"canary":"private-input"}'}:{})});
  const body=await r.text();
  if(r.status!==503 || r.headers.get('retry-after')!=='60' || r.headers.get('cache-control')!=='private, no-store'
    || r.headers.get('x-kairos-maintenance')!=='1' || r.headers.has('server') || r.headers.has('x-powered-by')
    || r.headers.has('set-cookie') || r.headers.has('location') || r.headers.get('x-content-type-options')!=='nosniff'
    || r.headers.get('content-security-policy')!=="default-src 'none'; frame-ancestors 'none'"
    || r.headers.get('referrer-policy')!=='no-referrer'
    || r.headers.get('content-type')!=='text/plain; charset=utf-8'
    || body!==(method==='HEAD'?'':expected)) throw Error('maintenance_contract');
}
try {
  let ready=false;
  for(let i=0;i<20;i++){try{await request('/','GET');ready=true;break}catch{await new Promise(r=>setTimeout(r,100));}}
  if(!ready)throw Error('not_ready');
  let cases=0;
  for(const path of ['/','/app','/api/auth/login','/wp-admin/','/api/uploads/?token=canary','/wp-json/'])
    for(const method of ['GET','POST','HEAD','OPTIONS','PUT','DELETE']){await request(path,method);cases++;}
  process.stdout.write(JSON.stringify({status:'PASS',cases}));
}catch{process.stdout.write(JSON.stringify({status:'FAIL'}));process.exitCode=1;}
"""


def require(condition):
    if not condition:
        raise RuntimeError("maintenance verification invariant failed")


def protected(path, directory=False):
    info = path.lstat()
    require(info.st_uid == 0 and not info.st_mode & 0o022)
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022)


def run(args, timeout=30):
    return subprocess.run(args, env=ENV, capture_output=True, timeout=timeout)


def checked(args):
    result = run(args)
    require(result.returncode == 0)
    return result.stdout.decode().strip()


def extract_helpers(data, target):
    require(hashlib.sha256(data).hexdigest() == ARCHIVE_SHA)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            part = PurePosixPath(member.name)
            require(not part.is_absolute() and ".." not in part.parts and (member.isfile() or member.isdir()))
            if member.isfile() and part.parts[0] == "scripts":
                path = target.joinpath(*part.parts)
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(archive.extractfile(member).read())


def verify(config):
    os.umask(0o077)
    sys.dont_write_bytecode = True
    protected(config)
    root = Path("/opt/kairos/runtime/tests")
    checkout = Path("/opt/kairos/releases") / REVISION
    protected(root, True)
    protected(checkout, True)
    require(checked(["/usr/bin/git", "-C", str(checkout), "rev-parse", "HEAD"]) == REVISION)
    archive = run(["/usr/bin/git", "-C", str(checkout), "archive", "--format=tar", REVISION])
    require(archive.returncode == 0 and hashlib.sha256(archive.stdout).hexdigest() == ARCHIVE_SHA)
    for image, volumes in [(EDGE, {"/data", "/config"}), (WEB, set())]:
        require(checked(DOCKER + ["image", "inspect", "--format", "{{.Id}}", image]) == image)
        actual = json.loads(checked(DOCKER + ["image", "inspect", "--format", "{{json .Config.Volumes}}", image])) or {}
        require(set(actual) <= volumes)
    require("userns" not in checked(DOCKER + ["info", "--format", "{{json .SecurityOptions}}"] ))
    runid = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    work = root / ("kairos-maintenance-" + runid)
    report = {"schema": 1, "production_deploy": False, "whole_release_rollback": "NOT_TESTED",
              "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(), "checks": {}, "cleanup": {}}
    created = []
    lock = os.open("/opt/kairos/runtime/.operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        work.mkdir(mode=0o700)
        extract_helpers(archive.stdout, work / "verification")
        mounted = work / "Caddyfile"
        with mounted.open("xb") as stream:
            stream.write(config.read_bytes())
        mounted.chmod(0o644)
        before = "/opt/kairos/runtime/baselines/maintenance-" + runid + "-before"
        after = "/opt/kairos/runtime/baselines/maintenance-" + runid + "-after"
        for name in [before, after]:
            require(not Path(name).exists() and not Path(name).is_symlink())
        snapshot = str(work / "verification/scripts/vps-snapshot.sh")

        def logged(label, args):
            with (work / (label + ".log")).open("xb") as output:
                return subprocess.run(args, env=ENV, stdout=output, stderr=subprocess.STDOUT, timeout=120).returncode

        require(logged("before", ["/bin/bash", snapshot, before]) == 0)
        manifest = work / "no-changes.json"
        manifest.write_text(json.dumps({"version": 2, "release_commit": REVISION,
                                       "config_changes": [], "network_changes": [], "edge_binding_change": None}))

        def create(kind, image, network, options, command):
            name = "kairos-test-maintenance-" + kind + "-" + runid
            require(not checked(DOCKER + ["ps", "-aq", "--filter", "name=^/" + name + "$"]))
            record = {"name": name, "image": image, "id": None}
            created.append(record)
            identity = checked(DOCKER + ["create", "--name", name, "--pull", "never", "--network", network,
                "--label", "com.docker.compose.project=kairos", "--label", "com.kairos.maintenance.probe=" + runid,
                "--no-healthcheck", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "64", "--memory", "128m", "--memory-swap", "128m", "--cpus", "0.5", *options, image, *command])
            require(re.fullmatch(r"[a-f0-9]{64}", identity))
            record["id"] = identity
            return identity

        try:
            edge = create("edge", EDGE, "none", ["--user", "1000:1000", "--cap-add", "NET_BIND_SERVICE",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m,uid=1000,gid=1000",
                "--tmpfs", "/data:rw,nosuid,size=16m,uid=1000,gid=1000", "--tmpfs", "/config:rw,nosuid,size=16m,uid=1000,gid=1000",
                "--mount", f"type=bind,src={mounted},dst=/etc/caddy/Caddyfile,readonly", "--entrypoint", "caddy"],
                ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"])
            for attempt in range(2):
                checked(DOCKER + ["start", edge])
                client = create("client" + str(attempt), WEB, "container:" + edge,
                                ["--user", "10001:10001", "--entrypoint", "node"], ["-e", CLIENT])
                outcome = run(DOCKER + ["start", "-a", client], timeout=60)
                require(outcome.returncode == 0 and json.loads(outcome.stdout) == {"status": "PASS", "cases": 36})
                require(checked(DOCKER + ["inspect", "--format", "{{.State.Running}}|{{.State.ExitCode}}", client]) == "false|0")
                report["checks"]["http_initial" if attempt == 0 else "http_after_restart"] = "PASS_36_CASES"
                checked(DOCKER + ["stop", "--time", "10", edge])
                require(checked(DOCKER + ["inspect", "--format", "{{.State.Running}}|{{.State.ExitCode}}", edge]) == "false|0")
            report["checks"]["maintenance_component_restart"] = "PASS"
        except Exception as error:
            report["failure"] = type(error).__name__
        finally:
            for record in reversed(created):
                name = record["name"]
                try:
                    ids = checked(DOCKER + ["ps", "-aq", "--no-trunc", "--filter", "name=^/" + name + "$"]).splitlines()
                    require(len(ids) <= 1)
                    if ids:
                        identity = ids[0]
                        require(re.fullmatch(r"[a-f0-9]{64}", identity) and record["id"] in (None, identity))
                        actual = json.loads(checked(DOCKER + ["container", "inspect", "--format", IDENTITY, identity]))
                        require(actual == {"name": "/" + name, "image": record["image"], "project": "kairos", "run": runid})
                        checked(DOCKER + ["rm", "-f", identity])
                    report["cleanup"][name] = "PASS"
                except Exception:
                    report["cleanup"][name] = "FAIL"
            report["after_exit"] = logged("after", ["/bin/bash", snapshot, after, before])
            report["no_touch_exit"] = logged("no-touch", ["/usr/bin/python3", "-I", "-B",
                str(work / "verification/scripts/compare-release-snapshots.py"), before, after, "--manifest", str(manifest)]) if report["after_exit"] == 0 else 125
        report["status"] = "PASS" if (not report.get("failure") and len(report["checks"]) == 3
            and len(report["cleanup"]) == 3 and all(value == "PASS" for value in report["cleanup"].values())
            and report["after_exit"] == report["no_touch_exit"] == 0) else "FAIL"
        report["work"] = str(work)
        (work / "result.json").write_text(json.dumps(report, indent=2))
        return report
    finally:
        os.close(lock)


if __name__ == "__main__":
    require(len(sys.argv) == 2)
    result = verify(Path(sys.argv[1]))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
