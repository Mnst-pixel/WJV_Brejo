# Architecture

## Trust and network boundaries

Kairós is a five-network Docker Compose project named `kairos`:

- `kairos-edge`: the Kairós-only reverse proxy and HTTP-facing application surfaces.
- `kairos-app`: Next.js, Django API, WordPress, and background workers.
- `kairos-data`: PostgreSQL+pgvector, MariaDB, Redis, and MinIO.
- `kairos-ai`: policy layer, Hermes, and the local inference gateway.
- `kairos-mcp`: Jurisprudêncio gateway, MCP server, and MCP-Brasil adapter.

Only `kairos-edge` publishes one host port selected after collision detection. Data, AI, and MCP services are private. No Docker socket is mounted anywhere.

## Request flow

The Kairós edge routes `/` to WordPress, `/app` to Next.js, `/api` and `/admin` to Django, and internal health endpoints to service-specific probes. Authenticated learning state is canonical in Django/PostgreSQL. WordPress is editorial only and does not authenticate the learning application.

Legal-assistant flow:

`Django policy layer -> approved hybrid RAG -> Hermes -> local inference -> allowlisted MCP tools -> source validation -> audited response`.

Retrieved documents are untrusted data. Their text can never modify system policy or tool permissions.

## Persistence

All named volumes begin with `kairos_`. Bind-mounted persistent data resides only below `/srv/kairos`. Deployment configuration resides below `/opt/kairos`. Backups are written to `/srv/kairos/backups`, separate from live service volumes, while off-host backup remains an external dependency.

## Degraded operation

The web application, authentication, exams, notes, files, dashboard, and history continue to work if Hermes, LocalAI, the MCP stack, or an external legal source is unavailable. AI-specific actions return a clear temporary-unavailability state.

## Legal publication boundary

Ingestion states are immutable and audited:

`discovered -> downloaded -> quarantined -> parsed -> normalized -> classified -> verified -> human_review -> approved -> indexed -> published`.

Only an authorized reviewer can transition from human review to approval. Publication and indexing reject absent approval records.

