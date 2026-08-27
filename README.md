# Kairós

Kairós is an isolated legal-education platform for Brazilian Bar Examination study. It combines an institutional WordPress surface, a Next.js learning application, a Django API, versioned legal content, document ingestion, controlled retrieval-augmented generation, a local AI runtime, and the Jurisprudêncio MCP stack.

## Current state

Implementation is in progress. The mandatory VPS read-only baseline and the supplied artifact hashes have been validated. No production claim is made until both final verification documents pass.

## Safety contract

- The target VPS is shared by unrelated production systems.
- Kairós uses only its own directories, containers, networks, volumes, credentials, and ports.
- Existing Nginx, Docker projects, databases, Redis instances, services, firewall rules, certificates, and data are not reused or reconfigured.
- Legal publication always requires human approval.

## Repository layout

- `apps/web`: Next.js learning application.
- `apps/api`: Django REST API, RBAC, audit, legal versioning, and administration.
- `apps/worker`: Celery worker entry point.
- `services`: isolated AI, MCP, ingestion, and document-processing services.
- `wordpress`: WordPress manifests, editable content seed, media, and operational documentation.
- `database`: schema references, migrations, and safe bootstrap data.
- `infra`: Docker Compose, Kairós edge, backup, restore, and monitoring.
- `legacy`: manifests for source artifacts whose redistribution status is not yet confirmed.
- `scripts`: repeatable safety, deployment, and verification commands.
- `docs`: architecture, operations, legal-data, security, and verification evidence.

See `docs/DEPLOYMENT.md` for the controlled deployment sequence and `docs/PENDING-DECISIONS.md` for external dependencies.

