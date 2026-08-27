#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /opt/kairos/runtime/baselines/<snapshot-name>" >&2
  exit 64
fi

output_dir="$(realpath -m -- "$1")"
case "$output_dir" in
  /opt/kairos/runtime/baselines/*) ;;
  *) echo "refusing snapshot output outside /opt/kairos/runtime/baselines" >&2; exit 65 ;;
esac

umask 077
mkdir -p -- "$output_dir"

date --iso-8601=seconds > "$output_dir/captured-at.txt"
hostnamectl > "$output_dir/hostnamectl.txt"
uname -a > "$output_dir/uname.txt"
cat /etc/os-release > "$output_dir/os-release.txt"
lscpu > "$output_dir/lscpu.txt"
free -b > "$output_dir/memory.txt"
swapon --show --bytes > "$output_dir/swap.txt"
lsblk -e7 -o NAME,TYPE,SIZE,FSTYPE,FSVER,MOUNTPOINTS,UUID > "$output_dir/block-devices.txt"
df -BT1 > "$output_dir/disk.txt"
df -i > "$output_dir/inodes.txt"

docker version --format 'client={{.Client.Version}} server={{.Server.Version}} api={{.Server.APIVersion}}' > "$output_dir/docker-version.txt"
docker info --format 'containers={{.Containers}} running={{.ContainersRunning}} paused={{.ContainersPaused}} stopped={{.ContainersStopped}} images={{.Images}} driver={{.Driver}} root={{.DockerRootDir}} cpus={{.NCPU}} memory={{.MemTotal}}' > "$output_dir/docker-info.txt"
docker ps -a --no-trunc --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Ports}}' | LC_ALL=C sort > "$output_dir/containers.txt"
for id in $(docker ps -aq); do
  docker inspect --format '{{.Id}}|{{.Name}}|{{.State.Status}}|{{.State.StartedAt}}|{{.RestartCount}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.config-hash"}}|{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$id"
done | LC_ALL=C sort > "$output_dir/container-identities.txt"
docker image ls --no-trunc --digests --format '{{.ID}}|{{.Repository}}:{{.Tag}}|{{.Digest}}' | LC_ALL=C sort > "$output_dir/images.txt"
docker network ls --no-trunc --format '{{.ID}}|{{.Name}}|{{.Driver}}|{{.Scope}}' | LC_ALL=C sort > "$output_dir/networks.txt"
docker volume ls --format '{{.Name}}|{{.Driver}}' | LC_ALL=C sort > "$output_dir/volumes.txt"

ss -H -lntup | sed -E 's/pid=[0-9]+/pid=<dynamic>/g' | LC_ALL=C sort > "$output_dir/listeners.txt"
ps -eo user,stat,comm --no-headers | LC_ALL=C sort | uniq -c > "$output_dir/process-summary.txt"
systemctl list-units --type=service --state=running --no-legend --no-pager | awk '{print $1"|"$3"|"$4}' | LC_ALL=C sort > "$output_dir/services-running.txt"
systemctl list-unit-files --type=service --state=enabled --no-legend --no-pager | LC_ALL=C sort > "$output_dir/services-enabled.txt"

ip -brief address > "$output_dir/interfaces.txt"
ip route show table all > "$output_dir/routes.txt"
resolvectl dns > "$output_dir/dns.txt" 2>&1 || true
ufw status numbered > "$output_dir/ufw.txt" 2>&1 || true
nft list ruleset > "$output_dir/nft-ruleset.txt" 2>&1 || true
iptables-save > "$output_dir/iptables.txt" 2>&1 || true
ip6tables-save > "$output_dir/ip6tables.txt" 2>&1 || true

find /etc/nginx -xdev -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum > "$output_dir/nginx-config-hashes.txt"
find /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.monthly /etc/cron.weekly /var/spool/cron -xdev -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum > "$output_dir/cron-hashes.txt"
find /etc/letsencrypt -xdev -type f \( -name 'cert.pem' -o -name 'fullchain.pem' -o -name '*.conf' \) -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum > "$output_dir/public-certificate-hashes.txt"

: > "$output_dir/compose-config-hashes.txt"
while IFS='|' read -r _ _ _ _ _ _ _ _ config_files; do
  IFS=',' read -ra paths <<< "$config_files"
  for path in "${paths[@]}"; do
    [[ -f "$path" ]] && sha256sum -- "$path"
  done
done < "$output_dir/container-identities.txt" | LC_ALL=C sort -u > "$output_dir/compose-config-hashes.txt"

(
  cd "$output_dir"
  find . -maxdepth 1 -type f ! -name 'MANIFEST.sha256' -print0 | sort -z | xargs -0 sha256sum
) > "$output_dir/MANIFEST.sha256"

echo "SNAPSHOT_COMPLETE=$output_dir"
