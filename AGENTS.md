# Kairós agent rules

These rules are mandatory for every human or automated contributor.

1. Never stop, restart, reload, reconfigure, delete, attach to, or reuse a resource that does not begin with the Kairós namespace. Existing host resources are read-only.
2. Use `COMPOSE_PROJECT_NAME=kairos`. Kairós containers, images, networks, volumes, directories, and backup artifacts must be independently identifiable.
3. Never commit credentials, tokens, cookies, private keys, database dumps, private uploads, generated secrets, or live environment files. Use protected environment files or Docker secrets with mode `0600`.
4. Never publish AI-generated or AI-modified legal content automatically. The required transition is `human_review -> approved -> indexed -> published`, with an accountable human approval record.
5. Legal content is immutable by version. Changes create a successor row and preserve source, hash, retrieval time, temporal validity, and the historical exam context.
6. Every schema change requires a migration, a rollback note, and automated checks. Never edit production data to simulate a migration.
7. Every functional change requires focused tests, lint/type checks where applicable, and documentation of operational impact.
8. Backups are incomplete until a restore is tested in a Kairós-only temporary environment.
9. Keep commits small and reviewable. Do not mix unrelated changes or generated noise.
10. Before and after deploy, run the no-touch comparator. A Kairós deploy is acceptable only when pre-existing resource identities and critical configuration hashes are unchanged.
11. Verification A is implementation-owned. Verification B must be independent and assume the system is wrong. Any correction invalidates both and requires complete reruns.
12. Do not claim `KAIRÓS_OPERATIONAL=YES` until every acceptance gate is evidenced and no critical/high finding remains.

