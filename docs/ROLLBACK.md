# Rollback

Rollback operates only on Kairós resources. It never stops, reloads, renames, moves, edits, or restores an unrelated host resource.

1. Capture current Kairós diagnostics and the no-touch state.
2. Stop only the affected Kairós service or Compose project.
3. Restore the last tagged Kairós image/configuration and run backward-compatible migrations or the documented Kairós-only restore.
4. Re-run health, persistence, authorization, and no-touch tests.
5. Invalidate and rerun both final verifications from the beginning.

If rollback would require changing host Nginx, firewall, Docker daemon, or an unrelated project, stop and request explicit owner direction.

