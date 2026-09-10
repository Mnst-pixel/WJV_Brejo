"""Reviewed permission ceiling. Database grants may narrow, never widen this policy."""
RESOURCES = ("users", "roles", "content", "question", "exam", "simulation", "case", "piece", "rubric", "corpus", "ingestion", "publication", "ai", "prompt", "tool", "audit", "settings")
ACTIONS = ("read", "create", "edit", "delete", "review", "approve", "publish", "manage")
PERMISSIONS = {f"{resource}.{action}": f"{resource}: {action}" for resource in RESOURCES for action in ACTIONS}
PERMISSIONS.update({key: key for key in ("study.use", "ai.consult", "service.integrate", "mcp.query", "legal.review", "legal.publish", "corpus.curate", "corpus.update", "support.manage", "teaching.manage", "ai.use")})
MACHINE_PERMISSIONS = {"service.integrate", "mcp.query"}
STUDY = {"study.use", "ai.consult", "ai.use"}
EDITOR = {f"{resource}.{action}" for resource in ("content", "question", "exam", "case", "piece", "rubric") for action in ("read", "create", "edit")}
REVIEWER = {f"{resource}.{action}" for resource in ("content", "question", "exam", "case", "piece", "rubric", "corpus", "publication") for action in ("read", "review", "approve")}
REVIEWER |= {"legal.review", "legal.publish", "publication.publish", "corpus.curate", "corpus.update", "audit.read"}
ROLES = {
    "superadministrador": set(PERMISSIONS) - MACHINE_PERMISSIONS,
    "administrador": set(PERMISSIONS) - MACHINE_PERMISSIONS,
    "administrador-de-conteudo": EDITOR | {"publication.read", "publication.publish", "corpus.read", "audit.read"},
    "editor": EDITOR,
    "revisor-juridico": REVIEWER,
    "professor": EDITOR | STUDY | {"teaching.manage"},
    "suporte": {"users.read", "support.manage"},
    "aluno": STUDY,
    "conta-de-servico": MACHINE_PERMISSIONS,
    # Compatibility roles remain explicit, with no automatic expansion.
    "gestor-de-usuarios": {"users.read", "users.manage", "support.manage", "audit.read"},
    "curador": {"corpus.read", "corpus.curate", "corpus.update", "legal.review"},
    "auditor": {"audit.read"},
}
ADMIN_PERMISSIONS = set(PERMISSIONS) - STUDY - MACHINE_PERMISSIONS
PRIVILEGED_ROLES = {"superadministrador", "administrador", "conta-de-servico"}
# The generic admin cannot perform review/publication or change policy grants.
MODEL_RESOURCES = {
    "user": "users", "role": "roles", "permission": "roles", "userrole": "roles",
    "subject": "content", "topic": "content", "content": "content", "contentversion": "content",
    "sourceregistry": "corpus", "assetregistry": "corpus", "sourcedocument": "corpus",
    "sourcedocumentversion": "corpus", "coveragerecord": "corpus", "corpusupdate": "ingestion",
    "exam": "exam", "examphase": "exam", "question": "question", "practicalcase": "case",
    "ingestionrun": "ingestion", "agent": "ai", "agentrun": "audit", "auditlog": "audit",
}

