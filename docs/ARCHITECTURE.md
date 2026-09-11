# Architecture

## Educational product P3–P6

The first product increment adds a Django-rendered editorial workspace at `/admin/editorial/`. It reuses the content workflow services and canonical database, with action-specific RBAC, human separation of duties and mandatory MFA even for non-staff editors. Next.js retains login and student interfaces; WordPress does not store private learning data. The specialist Django Admin remains available for existing operational forms, while taxonomy creation uses the locked editorial command. Established topic relationships cannot be reassigned by the specialist admin. Implementation and availability are tracked separately in [P3-P6-ENTREGA.md](P3-P6-ENTREGA.md).

## Trust and network boundaries

The canonical configuration in this branch is a Docker Compose project named `kairos`. Deployment of this foundation release is still gated; the live baseline and exact deployed image remain recorded in [P0-P2-ENTREGA.md](P0-P2-ENTREGA.md). The earlier five-network Hermes/MCP topology is historical, not the target runtime contract.

- `kairos-edge`: the Kairós-only reverse proxy and HTTP-facing application surfaces.
- `kairos-app`: Next.js, Django API, WordPress, and background workers.
- `kairos-data`: PostgreSQL+pgvector, MariaDB, Redis, and MinIO.
- `kairos-ai`: Django policy client and stateless LocalAI inference.
- `kairos-mcp`: retained historical network; historical Hermes/MCP containers are absent from the canonical service list and must be retired through the controlled release.
- `kairos-parser`: private worker-to-parser network, without a route to the internet or application/database credentials in the parser.

Only `kairos-edge` publishes host port 4080, bound to loopback in the candidate. The existing host Kairós Nginx virtual host terminates TLS. Database, Redis, MinIO, LocalAI and parser ports stay private. No application container receives the Docker socket. Service credentials are explicit projections in `config/service-secrets.json`; the full recovery environment is never an application env file.

## Request flow

The Kairós edge routes `/` to WordPress, `/app` to Next.js, `/api` and `/admin` to Django, and internal health endpoints to service-specific probes. Authenticated learning state is canonical in Django/PostgreSQL. WordPress is editorial only and does not authenticate the learning application.

Legal-assistant flow:

`Django permission and ownership policy -> approved versioned retrieval -> stateless LocalAI request -> bounded structured response -> redaction and persisted audit`.

The machine tool boundary is implemented in Django with its own service identities, explicit scopes and delegated user authorization. A service principal cannot grant itself scope, inherit a human role or receive administrative tools through a model response. External legal-source adapters remain separately configured; absence of SMTP, INLABS, DataJud or off-host storage does not imply readiness of those integrations.

WordPress administrative requests require both current Kairós administrative permission/MFA and the existing WordPress identity. Caddy obtains a short-lived signed authorization proof from Django; the read-only MU-plugin verifies it at WordPress as well. Public reads have a distinct proof that cannot authenticate a WordPress user. This introduces a fail-closed dependency on API availability for dynamic blog requests, documented in [P0-WORDPRESS-MFA.md](P0-WORDPRESS-MFA.md).

Retrieved documents are untrusted data. Their text can never modify system policy or tool permissions.

## Persistence

All named volumes begin with `kairos_`. Bind-mounted persistent data resides only below `/srv/kairos`. Deployment configuration resides below `/opt/kairos`. Backups are written to `/srv/kairos/backups`, separate from live service volumes, while off-host backup remains an external dependency.

Study progress, activities, preferences, panel state, Pomodoro, notes, goals, answers, attempts and upload metadata are owned by the authenticated user in PostgreSQL. Browser import creates provenance receipts and deduplicates without overwriting canonical records. Legacy legal content remains unverified until accountable review. Exam attempts preserve frozen question/rubric context and deterministic results. Optimistic versions, database constraints and row locks protect concurrent writes.

Uploads pass quota/size/type/magic/hash validation, quarantine, ClamAV and the separate parser before release to private storage. Downloads go through the authenticated ownership-checked API. The parser child has syscall, filesystem exposure, resource, output and archive limits; it has no database, S3, inference or administrative secret. Detailed contracts and their remaining live-test gates are in [P0-UPLOAD-LIVE-TEST.md](P0-UPLOAD-LIVE-TEST.md).

## Reproducible release boundary

A release binds a clean Git commit, configuration hashes and immutable image IDs in a protected manifest. `kairos-compose.py` validates that descriptor and rejects drift, implicit bootstraps, unlisted services and ambient Docker/Compose redirection. API, worker, beat and migration use the same source artifact. Migrations run explicitly under the migration role; application and upload worker use separate least-privilege roles. The operation lock coordinates deployment, backup and role reconciliation. These contracts require isolated runtime and rollback proof before production activation.

## Degraded operation

The web application, authentication, exams, notes, files, dashboard, and history continue to work if Hermes, LocalAI, the MCP stack, or an external legal source is unavailable. AI-specific actions return a clear temporary-unavailability state.

## Legal publication boundary

Ingestion states are immutable and audited:

`discovered -> downloaded -> quarantined -> parsed -> normalized -> classified -> verified -> human_review -> approved -> indexed -> published`.

Only an authorized reviewer can transition from human review to approval. Publication and indexing reject absent approval records.

Objective questions extend the existing version tables with `QuestionMetadata` and `QuestionWorkflow`. A human approval signs question text, alternatives, answer key and legal metadata as one package. Student serialization and attempt capture verify that package. Practice uses the existing transactional attempt engine; results and bookmarks remain owned by the authenticated user. See [P5-QUESTOES.md](P5-QUESTOES.md) for endpoints, migrations and rollback.

Student simulation preparation selects published questions inside an owner-locked transaction and freezes both the selection and configuration fingerprint. A confirmation UUID survives uncertain browser responses; autosave uses optimistic versions and full answer/review snapshots. PostgreSQL remains canonical; temporary browser envelopes only recover unconfirmed requests. Final submission freezes deterministic scoring and formal elapsed time. See [P5-SIMULADOS.md](P5-SIMULADOS.md).

Second-phase exams reuse practical-case versions and rubric rows, extending them with areas, discursive questions and criterion metadata. Editorial approval signs the full reserved package. Written submissions have separate owned responses/checkpoints and a final integrity receipt; student projections exclude the rubric and expected answers. Both exam phases share formal-assistance admission policy. Correction/review tables prepare the next phase without pretending an evaluator is operational. See [P6-SEGUNDA-FASE.md](P6-SEGUNDA-FASE.md).

Reading progress records the reviewed ContentVersion explicitly. New publications require review while preserving the prior confirmed progress in ReadingHistory. Owned learning aggregates and deterministic next-step recommendations share the formal-exam admission lock. The Next dashboard uses these facts instead of demonstration data. See [P4-ESTUDO.md](P4-ESTUDO.md).

Account administration uses ordinary Django workspace forms over guarded commands. New accounts receive student scope and an unusable password; explicit email delivery lets the owner define access. Profile, role and access changes serialize account locks and revoke prior sessions. Recovery email uniqueness is enforced by a partial case-insensitive database constraint. See [P3-USUARIOS.md](P3-USUARIOS.md).

Subscription workspace forms reuse Plan, Enrollment and UploadPolicy. Signed state receipts, account locks and a settings mutex serialize administrative decisions; legacy Django admin writes are disabled and GET bookmarks redirect to the canonical forms. This layer governs private upload eligibility and quotas, not billing. See [P3-ASSINATURAS.md](P3-ASSINATURAS.md).

Visual content uses a bounded rich-text AST inside ContentVersion.structured_data while body remains the canonical plain projection. Shared revision/approval/publication commands validate the structure and exact text correspondence; existing version hashes cover formatting. Django and React emit fixed escaped elements. No external editor dependency or migration was introduced. See [P3-EDITOR-VISUAL.md](P3-EDITOR-VISUAL.md).

Personal notes have owner-scoped creation receipts, optimistic editing and optional reviewed publication references. The library uses canonical paginated API data; browser recovery holds only unconfirmed text and reconciles before resending. Deletion remains disabled until receipts can survive it. See [P4-ANOTACOES.md](P4-ANOTACOES.md).
