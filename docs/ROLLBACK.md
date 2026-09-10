# Rollback

Rollback operates only on Kairós resources. It never stops, reloads, renames, moves, edits, or restores an unrelated host resource.

The P0/P1/P2 foundation candidate has not been deployed. Its local commits can be reverted without rewriting history; no production migration needs reversal for these commits yet. The live revision, exact historical override and latest proven restore are listed in [P0-P2-ENTREGA.md](P0-P2-ENTREGA.md).

The canonical transition must preserve the prior checkout, image IDs, effective Compose/override, service environments, Redis credentials/ACL and database backup as one recovery set. A rollback must not combine an old API with a new schema/privilege set without demonstrated compatibility. Rotation invalidates application sessions; the retained MFA encryption key must remain compatible. Source/image rollback alone does not undo data changes. Keep administrative endpoints closed if reverting a security control would otherwise reopen a known high-risk path. A tested whole-release rollback procedure is still required before activating the candidate.

1. Capture current Kairós diagnostics and the no-touch state.
2. Stop only the affected Kairós service or Compose project.
3. Restore the last tagged Kairós image/configuration and run backward-compatible migrations or the documented Kairós-only restore.
4. Re-run health, persistence, authorization, and no-touch tests.
5. Invalidate and rerun both final verifications from the beginning.

If rollback would require changing host Nginx, firewall, Docker daemon, or an unrelated project, stop and request explicit owner direction.
