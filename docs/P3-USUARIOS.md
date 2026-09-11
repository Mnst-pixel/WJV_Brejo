# Administração de usuários

Módulo candidato: `/admin/editorial/usuarios/`. Requer papel autorizado e MFA; `is_staff` não concede acesso. Suporte pode consultar cadastro, estado, papéis e indicador MFA, sem dados privados de estudo ou decisões administrativas.

## Operação por formulário

1. **Criar usuário**: nome, nome de acesso, e-mail e motivo. A conta nasce como aluno, sem senha utilizável. O operador não recebe senha, token ou segredo MFA.
2. **Editar cadastro**: nome/e-mail com justificativa. A alteração revoga sessões anteriores.
3. **Administrar papéis**: caixas de seleção com nomes legíveis. Administrador comum não modifica contas/papéis privilegiados; somente superadministrador. Ninguém altera o próprio acesso pelo painel. Conta de serviço não acumula papéis humanos.
4. **Administrar acesso**: revogar sessões, suspender/bloquear ou reativar. Suspensão e bloqueio são um único estado de acesso inativo, sem expiração automática. Reativação é explícita.
5. **Enviar instruções para definir senha**: o destinatário define senha pessoal pelo fluxo de recuperação. SMTP ausente retorna estado indisponível; falha de provedor é informada sem expor detalhes. Criar o cadastro não envia mensagem automaticamente.

O painel mostra MFA ativado/não ativado, papéis e suas validades, sessões registradas e até 20 eventos administrativos quando o operador possui `audit.read`. Nunca mostra senha/hash, chave MFA, token de recuperação, preferências ou texto de estudo privado. A área de assinaturas/planos será integrada em lote próprio sobre a fundação existente.

## Concorrência e autorização

Todos os comandos revalidam autoridade após bloquear as contas em ordem determinística. Contas privilegiadas continuam protegidas mesmo inativas ou com concessão expirada. Edição, estado e papéis usam versão otimista; o formulário antigo recebe 409 e exige reabrir o cadastro. Revogação altera a versão da sessão e marca sessões rastreadas como revogadas.

Contas com privilégio legado de superusuário aparecem como Superadministrador, inclusive na busca por papel. Ao salvar uma decisão explícita sobre seus papéis, um superadministrador autorizado substitui o privilégio legado pelos papéis selecionados, revoga sessões e registra a conversão. Selecionar apenas Aluno remove efetivamente o acesso administrativo; manter Superadministrador preserva a autoridade pela matriz canônica. Não há conversão automática de contas nem alteração do próprio acesso.

Contrato atualizado: `GET /api/admin/users/<id>/roles/` retorna `version`; PUT passa a **exigir `expected_version`** e retorna a versão resultante. Clientes dos candidatos antigos precisam ler a versão antes de enviar. A API pública de recuperação mantém resposta genérica 202 mesmo se SMTP falhar; a confirmação bloqueia a conta durante validação do token e troca da senha, impedindo duas confirmações concorrentes. Conta inativa ou identificador inválido não pode concluir recuperação.

Recuperação pública e entrega administrativa compartilham limite de um envio por destinatário a cada 60 segundos e até 15 solicitações por IP em 15 minutos. Cache usa identificadores HMAC, sem endereços legíveis. Falha do cache impede entrega; a resposta pública permanece genérica. Em produção o cache compartilhado Redis deve estar saudável para esse controle operar entre workers. SMTP continua síncrono e depende de timeout operacional configurado.

## Banco, deploy e rollback

Migration **0014_unique_recovery_email** aplica unicidade de e-mail sem distinguir maiúsculas/minúsculas, exceto valores vazios. Verifica colisões antes de aplicar o índice e aborta sem alterar dados se houver duplicatas. Não escolhe proprietário nem mescla contas automaticamente. O pré-deploy deve contar colisões sem imprimir endereços e resolver eventuais conflitos por revisão autorizada. Atualização do próprio perfil também valida unicidade; a constraint é a proteção final contra concorrência.

Preservar índice e cadastros ao retornar a artefato seguro compatível. Não reintroduzir troca de papel sem versão nem confirmação de token concorrente. Backup/restore, migração e privilégios reais continuam gates anteriores à ativação. SMTP é dependência externa apenas para entrega de acesso; cadastro, consulta, suspensão, revogação e RBAC funcionam independentemente.

## Testes

`test_account_workspace.py`: criação sem segredo, papéis não autorizados, suporte, campos protegidos, sessões, conta privilegiada inativa/expirada, versão desatualizada, SMTP mock/ausente/falho, unicidade, recuperação e replay.

`test_account_concurrency.py`: confirmação concorrente com o mesmo token em PostgreSQL isolado; somente uma troca de senha pode ser aceita. E2E de navegador ampliado com criar → editar → trocar papel → suspender → reativar → revogar → estado SMTP. Nenhuma mensagem real enviada nos testes.

Resultados, revisão B, commit e imagem em `P3-P6-ENTREGA.md`; este documento não declara produção operacional.
