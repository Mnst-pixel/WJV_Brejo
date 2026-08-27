# Hermes

Only the official `NousResearch/hermes-agent` project is eligible. The selected release must be pinned by tag and resolved commit, its MIT license recorded, and its installation source inspected before build.

Hermes runs as a non-root Kairós-only service on `kairos-ai`, with a dedicated profile named `kairos`. It is not published to the host, requires a high-entropy bearer token, and accepts calls only from the Django policy layer.

Hermes receives no Docker socket, host root, global filesystem, unrestricted database credentials, or environment dump. Personal durable memory remains in Kairós PostgreSQL and is isolated by user. Native Hermes memory, if enabled, is restricted to neutral institutional material and must pass cross-user leakage tests.

Selected upstream baseline: `v2026.8.19`, Hermes Agent 0.20.5. Commit resolution and runtime benchmark are recorded during the build gate.

