# VPS baseline — read-only gate

Capture window: 2026-08-27 02:18:54–02:21:47 UTC  
Target: `2.24.215.183`  
Mode: observation only. No file, service, package, container, image, network, volume, firewall rule, proxy configuration, database, Redis instance, certificate, or cron entry was changed.

## Host

| Item | Observed value |
|---|---|
| Hostname | `srv1602496` |
| OS | Debian GNU/Linux 13.6 (trixie) |
| Kernel | `6.12.100+deb13-amd64` |
| Architecture | x86_64, KVM/QEMU |
| CPU | 4 vCPU, AMD EPYC 9354P |
| RAM | 15 GiB total, 7.3 GiB available at capture |
| Swap | 4.0 GiB total, 753 MiB used; existing `/swapfile-esculapio` |
| Disk | 200 GiB virtual disk; ext4 root 197 GiB, 61 GiB used, 128 GiB available |
| GPU | No PCI display/GPU device and no NVIDIA driver/tool detected |
| Uptime | 21 days 4 hours 56 minutes |
| Load | 0.01 / 0.20 / 0.27 |

The host is resource-constrained for concurrent local inference. Kairós must use a small CPU quantization, conservative context, explicit memory/CPU/PID limits, and a fail-open product design in which education features remain available when AI is unavailable.

## Container runtime

- Docker client/server: 29.4.1; API 1.54.
- Docker Compose: 5.1.3.
- Storage driver: overlayfs under `/var/lib/docker`.
- Podman: not installed.
- 46 containers existed and all 46 were running at capture.
- 80 images existed at capture.
- 20 Docker networks existed, including the defaults.
- 35 named Docker volumes existed.
- Existing Docker address space occupied contiguous `/24` networks from `172.16.0.0/24` through `172.16.17.0/24`.

### Existing Compose projects

The following project namespaces were observed and are outside Kairós: `jurisprudencio-central`, `ortotropico`, `dashm`, `esculapio`, `mercury-io`, `mcp-brasil`, `autoagendamentogustavo`, `backend-olisses`, `evolution-api-ae6z`, `consulta-api-infosimples-n8n`, and `n8n-ycqa`. An additional `evolution-api-xdxc` network and `naval.ia` network existed without active containers in the captured list.

No container name, image identity, network, volume, bind mount, Compose file, or environment file from those projects may be used by Kairós.

### Existing container health finding

`autoagendamentogustavo-api-1` was already `unhealthy` before Kairós. This is a pre-existing condition and is not in scope for repair. All captured container IDs had restart count zero except `mcp-brasil`, which had restart count one.

The raw identifiers and start times used by the no-touch comparator are captured by `scripts/vps-snapshot.sh` when the repository is staged. The comparison deliberately distinguishes Kairós-owned additions from changes to pre-existing identities.

## Ports and edge

Host Nginx already listened on public TCP 80 and 443. Kairós therefore must not bind 80/443, edit Nginx, reload it, attach to its networks, or use its certificates.

Occupied host TCP ports at capture included:

`22, 53, 80, 90, 443, 444, 1721, 3001, 3010, 3020, 3030, 3210, 3211, 3212, 4030, 4040, 4050, 4062, 4130, 4140, 5432, 6379, 8000, 8010, 8080, 8180, 17820, 32768, 32770, 65529`.

Kairós reserves candidate public port `4080`, subject to a fresh collision check immediately before deploy. Internal PostgreSQL, MariaDB, Redis, MinIO, ClamAV, LocalAI, Hermes, workers, and MCP services will not publish host ports.

## Host services and databases

Running system services included Docker/containerd, Nginx, PostgreSQL 17, Redis 8.0.2, SSH, fail2ban, UFW, Agent OS API, DBZ Contencioso Actions, PM2, Monarx, systemd networking/resolution/time, unattended upgrades, and QEMU guest agent.

- Host PostgreSQL: 17.11 on loopback port 5432, cluster `17/main`.
- Host Redis: 8.0.2 on loopback port 6379; `PING` returned `PONG`.
- Host MariaDB/MySQL: inactive/not installed as a host service.
- Multiple PostgreSQL and Redis containers also existed across unrelated Compose projects.

Kairós will create its own PostgreSQL+pgvector, MariaDB, and Redis instances and will not query or reuse existing databases.

## Proxy and certificates

- Nginx 1.26.3 is active on 80/443.
- Existing virtual hosts serve names under `apijurisprudencio.cloud` and `2-24-215-183.nip.io`.
- Existing Caddy and Traefik instances run inside unrelated containers.
- Let's Encrypt certificates existed for the current applications. Their public certificate metadata and Nginx configuration hashes were observed; private key contents were not read.

The SHA-256 of `/etc/nginx/nginx.conf` at capture was `c66fbe205bf46b5d125502e35605938ed37feef6e2b24325b1c088665caaf477`. Individual site configuration hashes are included in the captured comparator manifest, not duplicated here.

## Firewall, interfaces, routes, and DNS

- UFW was active with default deny inbound behavior.
- Explicit inbound allowances existed for SSH, Nginx Full, and TCP 4050.
- Docker-managed iptables chains were active.
- Primary interface: `eth0`, IPv4 `2.24.215.183/24`, IPv6 `2a02:4780:75:b23f::1/48`.
- Default IPv4 gateway: `2.24.215.254`.
- DNS servers: `153.92.2.6`, `1.1.1.1`, and `8.8.4.4` through systemd-resolved.

Captured firewall fingerprints:

| Source | SHA-256 |
|---|---|
| `nft list ruleset` | `ecacb6a123ba731c252c7a73f3dfdfa7c39e701326cf7ab3e5c537922a0f9aa5` |
| `iptables-save` | `bb6eafad5f926dd36ac92286d889968cb5cab74934663014062511391ea78efb` |
| `ip6tables-save` | `1d909dc9fd4ad12d685cce57892306dc169b6d974bbe304ce263bf92a449eca6` |

Docker necessarily adds rules for newly published Kairós ports and networks. The acceptance comparator therefore verifies that every pre-existing rule remains byte-for-byte present and classifies only Kairós-scoped additions; it does not incorrectly require the whole ruleset hash to remain identical.

## Cron

No root user crontab was present. System cron included package maintenance, statistics, certificate renewal, Monarx updates, and two pre-existing Docker prune jobs. The prune jobs are an operational risk for unused build cache/images but were not changed. Kairós deployment must not rely on untagged or dangling images.

## Baseline gate result

`PHASE_0_READ_ONLY=PASS`

This is not the final no-touch result. The post-deploy comparison must still demonstrate `PREEXISTING_RESOURCES_MODIFIED=0`.

