# Planos, matrículas e limites de arquivos

O painel `/admin/editorial/assinaturas/` usa os modelos existentes de plano, matrícula e política de upload. Administradores com `settings.manage` e MFA podem operar por formulários. Não requer identificador técnico, JSON ou terminal. Cobrança, pagamentos e restrição de conteúdos por assinatura ainda não são implementados por esse módulo; a matrícula controla os limites e a disponibilidade de novos uploads.

## Operação

- Criar/editar plano: nome, disponibilidade, tamanho por arquivo, espaço por pessoa e motivo. O identificador interno é automático e permanente.
- Escolher pessoa na área Usuários → Administrar plano: selecionar plano, estado e datas de validade. A titularidade não pode mudar. Datas são apresentadas no fuso da aplicação, indicado no formulário.
- Suspender/expirar matrícula: novos uploads ficam bloqueados; login, textos de estudo e arquivos existentes permanecem preservados. Reativação e validade são decisões explícitas.
- Limites gerais: habilitar uploads, máximo por arquivo e espaço para pessoas sem matrícula. O teto global por arquivo também limita os planos; o teto de segurança da aplicação não pode ser ultrapassado pelo painel.
- Reduzir quota abaixo do uso não exclui arquivos; bloqueia novos envios que excedam o limite. A tela mostra apenas o tamanho ocupado, sem nomes ou conteúdo de arquivos privados.

Plano desativado impede novos uploads das pessoas vinculadas. Matrícula com início futuro, data final vencida, estado suspenso/expirado ou plano inativo não concede quota alternativa. Pessoas sem matrícula usam a política geral existente. O estado exibido considera as datas e a situação do plano; não presume pagamento recebido.

## Consistência e autorização

Decisões incluem recibo assinado oculto vinculado ao operador, tipo, alvo e estado atual, válido por uma hora. Alteração concorrente, expiração, troca de alvo ou repetição após gravação exige recarga, com HTTP 409. Criação usa identidade persistente no formulário para impedir duplicação após reenvio. Os locks seguem contas em ordem determinística, mutex de configurações, plano e matrícula. Autoridade é revalidada dentro da transação; matrícula própria, conta privilegiada sem superadministrador e conta de serviço são recusadas.

Links antigos do Django Admin encaminham GET para os formulários canônicos; POST antigo e chamadas diretas ao gravador antigo são recusados. Isso elimina o caminho alternativo que permitia alterar matrículas de contas protegidas sem o novo contrato. A UI oculta ações indisponíveis, mas a autorização definitiva permanece no backend.

Todas as mudanças registram responsável, timestamp, campos e motivo na auditoria. Não há exclusão nem alteração de secrets. Limites são avaliados na admissão de cada upload; alterações de configuração não cancelam retroativamente admissões já efetuadas.

## Verificação e operação

Sem migration: reutiliza `Plan`, `Enrollment` e `UploadPolicy`. Testes de serviço/HTTP verificam MFA, papéis, decisões antigas, replay, titularidade, limites, datas, preservação e bloqueio do formulário legado. Três concorrências PostgreSQL cobrem plano, matrícula e singleton. E2E inclui criar plano → vincular pessoa → suspender → buscar → alterar limites, com layout 390×844.

Deploy exige a mesma release segura e os gates operacionais P1. Rollback preserva dados/quotas/matrículas; não retornar ao formulário legado que contorna a proteção de titular. Resultados, commit e imagem estão na entrega P3–P6; este guia não declara produção operacional.
