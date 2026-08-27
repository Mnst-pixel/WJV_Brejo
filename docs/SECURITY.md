# Security

## Core controls

- Independent random credentials per service; no human password reuse.
- Protected environment file, mode `0600`; secrets excluded from Git and logs.
- Private data/AI/MCP networks and no Docker socket mounts.
- Backend RBAC, object ownership checks, progressive lockout, session revocation, CSRF, secure cookie policy, and rate limits.
- Administrator MFA is required before final acceptance.
- Uploads use size limits, magic-byte detection, randomized internal names, immutable hashes, quarantine, ClamAV, parser isolation, and private object storage.
- Legal sources and retrieved content are untrusted data and cannot instruct the agent.
- MCP and Hermes use bearer authentication, allowlisted tools, timeouts, output limits, and audited calls.
- WordPress disables the file editor, limits login, restricts XML-RPC, uses the minimum plugin set, and keeps uploads non-executable.

## Secret response

If a secret is found in Git history, treat it as compromised, block deployment, rotate it through the owning provider, and document the incident without reproducing the value.

Bootstrap root and administrator credentials must be rotated by the owner after handoff; Kairós will not rotate them without explicit authorization.

