from django.core.management.base import BaseCommand

from core.models import Permission, Role


PERMISSIONS = {
    "users.manage": "Gerenciar usuários",
    "roles.manage": "Gerenciar papéis e permissões",
    "content.edit": "Editar conteúdo educacional",
    "legal.review": "Revisar conteúdo jurídico",
    "legal.publish": "Publicar versões aprovadas",
    "teaching.manage": "Gerenciar atividades docentes",
    "corpus.curate": "Curar o corpus",
    "corpus.update": "Executar atualização manual do corpus",
    "support.manage": "Prestar suporte",
    "audit.read": "Ler auditoria",
    "study.use": "Usar módulos de estudo",
    "ai.use": "Usar assistência de IA",
    "service.integrate": "Executar integrações de serviço",
}

ROLES = {
    "superadministrador": list(PERMISSIONS),
    "administrador": [p for p in PERMISSIONS if p != "service.integrate"],
    "gestor-de-usuarios": ["users.manage", "support.manage", "audit.read"],
    "editor": ["content.edit"],
    "revisor-juridico": ["legal.review", "legal.publish", "corpus.curate", "audit.read"],
    "professor": ["content.edit", "teaching.manage", "study.use", "ai.use"],
    "curador": ["corpus.curate", "corpus.update", "legal.review"],
    "suporte": ["support.manage"],
    "auditor": ["audit.read"],
    "aluno": ["study.use", "ai.use"],
    "conta-de-servico": ["service.integrate"],
}


class Command(BaseCommand):
    help = "Idempotently creates Kairós roles and permissions."

    def handle(self, *args, **options):
        permission_objects = {}
        for codename, description in PERMISSIONS.items():
            permission_objects[codename], _ = Permission.objects.update_or_create(codename=codename, defaults={"description": description})
        for slug, codenames in ROLES.items():
            role, _ = Role.objects.update_or_create(slug=slug, defaults={"name": slug.replace("-", " ").title(), "is_system": True})
            role.kairos_permissions.set([permission_objects[codename] for codename in codenames])
        self.stdout.write("RBAC_BOOTSTRAP=PASS")
