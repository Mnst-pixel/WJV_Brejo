# Transição integral: gates ainda não implementados ou aprovados

Este documento registra o trabalho técnico que falta. Não é um procedimento executável de deploy nem autorização derivada de um snapshot posterior. A imagem d6d7f93 passou nos testes isolados; isso não resolve sozinho a divergência entre o checkout produtivo e o override histórico.

## Plano de rede anterior à alteração

Progresso incremental: [P1-TRANSITION-PLAN.md](P1-TRANSITION-PLAN.md) e [P1-TRANSITION-IO.md](P1-TRANSITION-IO.md) registram modelo, coleta real, freeze protegido, vínculo ao snapshot e registros de início/conclusão. O ciclo sem mudanças passou no VPS, com lock e comparador integral. Ainda faltam a integração do coordenador, nova comparação completa imediatamente antes da primeira mutação, backup/restore, manutenção, filas, migrations/grants, troca de release e rollback. As bibliotecas sozinhas não fecham os gates abaixo.

O comparador v2 confere hashes exatos de projeções, inclusive IDs de containers/endpoints. IDs novos só existem depois da criação. Um coordenador não pode preencher o hash esperado usando o estado final e chamar isso de autorização prévia.

A evolução deve congelar um plano semântico antes do primeiro passo mutável: commit, hash do baseline, nomes/projetos/serviços, imagens/revisions esperadas, redes exclusivas, driver/internal/subnets/gateways/options, memberships e bindings. Cada identidade precisa de uma política explícita de retenção, substituição ou criação; remoções também precisam de nome e ID anterior exatos. Recursos alheios permanecem integralmente fixos.

Para endpoints, admitir endereço exato ou alocação dinâmica explicitamente limitada à subnet própria já aprovada. As cinco redes existentes foram capturadas com IPAM automático; não recriar redes em uso apenas para impor IP estático ao comparador. A rede nova do parser precisa ser interna e não sobrepor nenhuma subnet existente.

Um receipt protegido, criado uma única vez, pode preencher somente IDs Docker/bridge e IPs dinâmicos dentro dessas restrições. Deve vincular o hash do plano, origem local do Docker e identidades inspecionadas. Não pode acrescentar serviços, endpoints, imagens, bindings ou autoridade. O comparador deve confrontar plano, receipt e snapshot posterior e aplicar os mesmos testes de ordem/barreiras/negações do v2. Repetir A/B com tentativas de receipt adulterado, projeto alheio com nome Kairós, IP fora de faixa, conflito e regras globais.

## Coordenador de release e rollback

Preparar artefatos e configuração antes de abrir uma janela de escrita: checkout Git limpo, imagens verificadas, descriptor, credenciais segregadas, ACL Redis e plano SQL com hashes. Nenhum arquivo preparado deve ativar-se por presença; o pointer ativo só muda na etapa documentada. Capturar a revisão geral antiga, a revisão real da API e o override efetivo como conjunto de rollback.

O coordenador deve compartilhar `.operation.lock` com backup e reconciliação. Antes de migrations/rotacionar serviços, produzir backup novo com restore isolado e capturar baseline fresco. Validar uma janela de manutenção que impeça novas escritas, verificar/drainar filas antigas sem perder tarefas e preservar jobs/uploads pendentes. Provar a passagem broker antigo → ACL/prefixos novos.

Reconciliar os papéis PostgreSQL antes e depois de migrations explícitas. O migrator é dono do schema; o runtime não tem DDL/superuser. Não usar produção para ensaiar migrations. Em 2026-09-10, `2a14c31` passou nas 5 migrations forward sobre backup real restaurado, com 86 registros originais/64 tabelas preservados e repetição idempotente. Esse ensaio usou o proprietário temporário da restauração; ainda faltam a combinação com os papéis segregados e a compatibilidade/rollback da release anterior.

Aplicar somente serviços Kairós listados, retirar containers históricos IA/MCP e bootstraps preservando volumes e evidência. Não usar `down`, `prune` ou `--remove-orphans` genéricos. Nunca reativar a API vulnerável pelo Compose antigo. Capturar IDs/imagens reais e verificar health, DB/cache/broker, worker, parser, storage, edge e nonce/MFA WordPress antes de liberar escritas.

O rollback precisa restaurar um conjunto coerente de Git/imagens/Compose/scoped env/ACL e dados. Restauração do backup não pode descartar silenciosamente novas escritas posteriores; definir e testar o ponto de liberação de tráfego. Uma falha após liberação exige preservar e reconciliar essas escritas. Não marcar P1 concluído com um plano de rollback somente textual.

## Provas restantes

- E2E fundamental preservando o visual, em homologação isolada: autenticação/MFA, retomada, notas/metas/Pomodoro e upload privado.
- Backend produtivo sem superuser; scopes mínimos efetivamente entregues a cada container; inventário MinIO e validação de configurações reais. WordPress foi inventariado: apenas Elementor ativo, Hello Elementor, grants limitados ao próprio banco; esse resultado não substitui revisão de rotas/plugins ou correções de vulnerabilidades.
- HTTP WordPress direto e via edge e rotas/cron afetados. Replay concorrente já passou em MariaDB isolado com a classe `wpdb` e hooks nativos: 12 processos, exatamente 1 nonce aceito, além de limpeza/saturação/falha de banco. Esse resultado não substitui o HTTP completo.
- Escopo exato de proxies confiáveis: validar gateways realmente usados pelo Nginx antes de estreitar `private_ranges`; testar origem/HTTPS/IP e limites sem atingir outros virtual hosts.
- Nova rotina de backup/restore com scoped credentials, retenção, alertas, timers e health instalados. Off-host ausente permanece EXTERNAL_BLOCKER.
- Benchmark autenticado, páginas reais, queries e carga controlada; o baseline loopback público não cobre todos esses fluxos.
- Nova verificação independente após as últimas correções. O limite de uso interrompeu os agentes de revisão; não considerar sua ausência como aprovação.
