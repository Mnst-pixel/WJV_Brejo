# Private Jurisprudêncio integration

The supplied archive contains no declared license. Its source must not be committed or published. Deployment stages a verified private copy under `upstream/`, which is ignored by Git, then applies the narrowly documented security overlay.

The Kairós containers are isolated from any pre-existing host gateway, Redis, Nginx, PM2 process, path, or container. Only the internal `mcp-server` endpoint is consumed by Hermes. URL-secret authentication is disabled; service-to-service access requires a bearer header.

Run `scripts/stage-jurisprudencio.sh /opt/kairos/private/MCP-Jurisprudencio.zip` before the Compose build. The command refuses an unexpected archive hash, unsafe ZIP paths, a nonempty target, dependency drift, or an npm audit at high/critical severity.
