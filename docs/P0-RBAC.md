# P0 — fundação de autorização por recurso e ação

## Alteração e motivo

A autorização é definida em `apps/api/core/rbac_policy.py`, limitada pela matriz revisada em código e pelos grants persistidos. A matriz não pode ser ampliada editando somente uma linha de Permission no banco. Permissões desconhecidas são negadas inclusive para superusuário. O papel conta-de-servico nunca acumula capacidades de papéis humanos.

Papéis principais: superadministrador, administrador, administrador-de-conteudo, editor, revisor-juridico, professor, suporte, aluno e conta-de-servico. Gestor-de-usuarios, curador e auditor permanecem como papéis compatíveis restritos. A matriz cobre users, roles, content, question, exam, simulation, case, piece, rubric, corpus, ingestion, publication, ai, prompt, tool, audit e settings. Ações possíveis são read/create/edit/delete/review/approve/publish/manage; somente endpoints efetivamente implementados usam esses grants. Ter um grant não cria automaticamente um endpoint.

Aluno recebe estudo e consulta; editor recebe leitura/criação/edição de conteúdo educacional sem aprovação/publicação; professor acrescenta estudo e docência; revisor recebe revisão/aprovação e publicação; administrador de conteúdo pode editar e executar publicação aprovada, mas não aprovar; suporte recebe leitura de cadastro e suporte, sem corpus, prompts, IA ou conteúdo restrito. Administrações abrangentes continuam sujeitas às regras de workflow e ao MFA.

## MFA e credenciais

`request_has_permission` exige mfa_verified verdadeiro e a versão atual da sessão para ações administrativas. `user_requires_mfa` considera papel administrativo além de is_staff/is_superuser. O fluxo de login/enrollment deve chamar esse helper; uma conta de serviço não pode iniciar sessão humana.

A conta de serviço exige `request.auth` produzido por backend confiável com principal_type=service e scopes autorizados. Valores enviados no corpo não concedem acesso. A política humana permite somente service.integrate e mcp.query para essa identidade; gateways de ferramentas devem aplicar adicionalmente autenticação M2M, audiência, allowlist e limites próprios. Este módulo isoladamente não declara operacional a integração M2M.

## Administração e endpoints

`GET /api/admin/roles/` apresenta o catálogo versionado. `GET/PUT /api/admin/users/<uuid>/roles/` consulta/substitui grants com justificativa. A substituição é transacional, bloqueia ator e destinatário, revalida permissões após lock, proíbe alteração própria e conta de serviço como ator. Somente superadministrador pode alterar destinatários ou atribuições privilegiadas (superadministrador, administrador e conta de serviço). Repetição sem mudança é no-op. Mudança revoga sessões por session_version e registra auditoria. Ações requerem CSRF da autenticação de sessão.

O Django admin usa a mesma política. Is_staff ou permissões Django sozinhos não concedem autorização. Grupo Django e edição genérica de Role/Permission/UserRole estão fechados; use o comando de atribuição auditado. Versões jurídicas, auditoria, agentes e operações são somente leitura no admin genérico. Estado, aprovação e ponteiros current_version não são campos editáveis. Conteúdo aprovado/publicado exige workflow de nova versão. Exclusão genérica está desabilitada. Cadastro de usuário exibe somente perfil mínimo; mudança própria, flags, password, MFA, grupos e permissões não podem ser alterados por esse formulário. O endpoint herdado de senha também é negado.

## Arquivos

`core/rbac_policy.py`, `permissions.py`, `rbac_views.py`, `admin.py`, `management/commands/bootstrap_roles.py`, `tests/test_rbac_foundation.py`, esta documentação. O integrador registra as rotas e adapta login/enrollment nos arquivos centrais.

## Migration e implantação

A estrutura existente Role/Permission/UserRole é preservada. `bootstrap_roles` reconcilia a matriz de forma transacional e idempotente, sem mudar atribuições de usuários. Migration de dados deve congelar esta matriz em vez de importar código mutável; o seed deve ocorrer somente após backup e ensaio de migrations. Grants legados fora da matriz não produzem autorização. Revisar e registrar a matriz anterior para rollback; não executar bootstrap histórico que restabeleça capacidades antigas. Mudança de código sem seed deixa novas ações negadas.

## Testes e evidência local

Suíte focada de 2026-09-10: 58 testes passaram em SQLite/LocMem (RBAC novo, autenticação, MFA e versões jurídicas); Ruff e Django system check passaram. Existem avisos conhecidos de staticfiles local ausente; artefato Docker e PostgreSQL/Redis precisam da rodada integrada do lote. Testes cobrem matriz, expiração da sessão, MFA administrativo sem is_staff, aluno com permissões Django indevidas, editor tentando elevar/publicar, suporte consultando corpus, service account ampliando scopes, atribuição privilegiada, autoalteração, auditoria e revogação, repetição idempotente, admin genérico e campos sensíveis.

Não há execução VPS nem commit próprio deste sublote. Revisão B e validação integrada permanecem gates de implantação. Estes testes não substituem concorrência PostgreSQL nem comprovam todas as integrações/recursos da aplicação.

## Rollback

Reverter este módulo para a implementação anterior reabre divergência entre admin e RBAC; preferir correção adiante ou manutenção temporária dos endpoints administrativos. Não apagar auditoria/grants para simular rollback. O rollback operacional deve selecionar revisão/imagem integral conhecida e registrar eventual risco que ela reintroduz.

# Revalidação no salvamento administrativo

Operações de escrita no Django Admin relêem o ator sob lock e revalidam conta ativa, MFA habilitado, prova MFA da sessão e `session_version` antes de consultar a matriz. Edição de usuário bloqueia ator e destinatário em ordem de PK igual à usada na atribuição de papéis. Assim uma requisição iniciada antes da revogação não conserva `is_superuser` ou autoridade obsoletos para concluir a edição. O salvamento continua limitado aos campos de perfil autorizados, sem atualizar flags de segurança vindas do formulário antigo.

Uma atribuição persistida `conta-de-servico` classifica a identidade como máquina mesmo após expirar ou desativar a conta. A expiração remove sua autoridade; não a converte em humano, mesmo com flags administrativas ou papéis humanos acidentais. Login humano continua recusado e, sem grant ativo de máquina, todos os escopos são negados. Testes: `test_admin_revocation.py` cobre ator revogado, MFA removido, sessão revogada, escrita válida e máquina expirada.
