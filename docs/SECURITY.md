# Security

Implementation and deployment status are distinct. This branch contains the foundation controls below; live activation and acceptance remain pending in [P0-P2-ENTREGA.md](P0-P2-ENTREGA.md). Historical verification does not certify the new code or the still-running legacy services.

## Core controls

- Independent random credentials per service; no human password reuse.
- Protected environment file, mode `0600`; secrets excluded from Git and logs.
- Private data/AI/MCP networks and no Docker socket mounts.
- Backend RBAC, object ownership checks, progressive lockout, session revocation, CSRF, secure cookie policy, and rate limits.
- Administrator MFA is required before final acceptance.
- Uploads use size limits, magic-byte detection, randomized internal names, immutable hashes, quarantine, ClamAV, parser isolation, and private object storage.
- Legal sources and retrieved content are untrusted data and cannot instruct the agent.
- The Django machine boundary uses dedicated service principals, explicit scopes, delegated user authorization, replay protection, allowlisted query tools, timeouts, output limits and persisted audit. Stateless LocalAI calls cannot execute model-supplied tools; historical Hermes/MCP containers are excluded from the canonical release.
- WordPress disables the file editor, limits login, restricts XML-RPC, uses the minimum plugin set, and keeps uploads non-executable.

The candidate adds current backend administrative MFA to WordPress through Caddy and a request-bound HMAC MU-plugin; the plugin also rejects unsigned direct internal HTTP access. The new signing key is restricted to API/WordPress. API redaction covers configured signing, inference, storage, database, Redis/broker and SMTP credentials. Caddy access logs delete custom internal proof headers in addition to its default cookie/Authorization redaction.

Python dependency updates, source-inventory checks and exact package/wheel hashes are documented in [P0-DEPENDENCIES.md](P0-DEPENDENCIES.md). An OSV result for Python packages is not a complete operating-system vulnerability assessment. No P0 completion claim is permitted while live integration, privilege reconciliation, container/edge verification or an independent security gate remains unresolved.

## Secret response

Formal-exam assistance is denied by authenticated user state, not by an optional attempt identifier supplied by the client. Both AI consultation and MCP delegation/calls enforce this boundary, including tokens minted before the exam started. Invalid UUIDs and missing/foreign resources fail with controlled client errors. Simulation preparation replay is scoped to the owner and a frozen configuration fingerprint; final submissions remain immutable.

Second-phase candidate projections exclude expected answers, piece type and rubric criteria from student responses. The reviewed case/rubric package is verified before admission; written responses must match the exact frozen target set, and final reads verify the submission hash. Both exam phases share formal-mode restrictions. Generic admin cannot rewrite practical-case publication pointers. SQL reconciliation extends immutable-table grants to rubric criteria, metadata, checkpoints and correction versions; live activation remains a release gate.

The objective-question candidate verifies reviewed package hashes at publication, student serialization and frozen attempt capture. Runtime grants deny UPDATE/DELETE of alternatives and question metadata after reconciliation. One active formal attempt blocks new attempts and cross-attempt answer-key/statistical oracles; owner locks serialize admission. Browser confirmation retries reuse their UUID; validation denials unlock the interface, while uncertain network/server failures preserve the pending confirmation. These controls are candidate code until deployment and real privilege verification are recorded.

If a secret is found in Git history, treat it as compromised, block deployment, rotate it through the owning provider, and document the incident without reproducing the value.

Bootstrap root and administrator credentials must be rotated by the owner after handoff; Kairós will not rotate them without explicit authorization.

The September 10 value scan matched `DATAJUD_API_KEY` between the live configuration and the existing `.env.example`. Its value was not emitted; the example now leaves the field empty. No external credential was rotated and history was preserved. Confirm the official key's public status and current validity with CNJ before enabling DataJud; the match alone is not proof of a private-user credential compromise. The integration remains externally unverified.
