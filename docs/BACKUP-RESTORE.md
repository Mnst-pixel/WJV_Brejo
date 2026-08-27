# Backup and restore

Backups cover PostgreSQL, MariaDB, MinIO objects, WordPress uploads, and non-secret configuration manifests. Secrets are backed up only through an owner-controlled encrypted mechanism.

Local backups are written below `/srv/kairos/backups`, outside live volumes, and are checksummed. This does not protect against total VPS loss; off-host storage is a pending external dependency.

Every accepted backup must be restored into Kairós-only temporary containers and verified for database integrity, administrator/user records, content, and files. Temporary names and volumes use a `kairos_restore_` prefix and are removed only after successful evidence capture.

