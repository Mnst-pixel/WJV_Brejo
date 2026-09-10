# P0–P2 — execução iniciada em 10 de setembro de 2026

Status: em implementação. Este registro será completado com evidência nova de cada lote; não herda conclusões das verificações históricas.

## Estado inicial verificado

Baseline VPS: `/opt/kairos/runtime/baselines/p0p2-20260910T175020Z-before` (17:50 UTC). Evidência local protegida: `modernizacao/evidencias/p0p2-baseline.json`.

- HEAD local inicial `9ca945fcefef2471de68cd5baa771670a765390c`, branch `astra/kairos-p0-seguranca`, limpa.
- `origin/main` inicial `f6ac1c3c510a4f442b9101d599e6598fe8428ca0`; PR #1 aberto, rascunho, mergeable, sem reviews GitHub.
- API efetiva `8f341aa4c87e2a6692b557cfafd0204bee7b910c`, imagem `sha256:078a0937a5a89cc374cd43c3848d105587d4ea7c0f82807e7f7352fdff417eee`, saudável, zero reinícios.
- Checkout geral VPS ainda `f6ac1c3`, limpo. Compose base e override `/opt/kairos/runtime/p0/20260909T194305Z/source/infra/compose/p0-api.override.yaml` ativos na API; demais serviços usam o base.
- 18 serviços Kairós registrados, contínuos saudáveis; `mcp-brasil` tem dois reinícios registrados. WordPress, Next.js, Django e admin HTTP 200. PostgreSQL/Redis disponíveis.
- PostgreSQL: 19 migrations, 3 usuários; papel `kairos_app` ainda superuser/createdb/createrole. Essa pendência foi confirmada, não inferida da documentação.
- Disco disponível 52.314.804.224 bytes; RAM disponível 4.418.883.584 bytes. Timers de backup e saúde ativos; health report PASS.
- Backup automático posterior à entrega: `/srv/kairos/backups/kairos-20260910T061956Z.tar.gz.enc`, 66.861.824 bytes, SHA-256 `f714a6d96127269c13e32442eec97234939b753e2f7c882d709f1bcad222f53d` válido. Recuperação desta execução exige novo ensaio isolado.
- Hashes do Compose base, Caddy e virtual host Kairós permanecem iguais aos da entrega anterior.

## Git

PR #1 integrado por merge commit `cb4708d80b8214e931bc94a871e2ee5e130a4dbf`, preservando histórico, após revalidação do estado e suíte local: 44 passed, 4 skips explícitos de imagem/concorrência. Nenhuma dependência produtiva alterada nessa integração.

Branch de continuação: `astra/kairos-p0-p2-fundacoes`, criada desse merge. O VPS ainda não foi atualizado por essa operação Git.

## Sequência de execução e gates

1. Consolidar configuração de release, commits, imagens e entrypoints sem bootstrap implícito; credenciais mínimas por serviço; recuperação automática isolada.
2. RBAC de backend, fronteira IA/MCP, privilégios de banco e containers/edge.
3. Uploads com quota e parser isolado; transações e snapshots de tentativas.
4. Persistência canônica e importação legada com provenance, deduplicação e revisão.
5. Testes integrados, migrations forward/back, E2E fundamental, benchmark, deploy incremental e verificações A/B.

Design visual existente deve ser preservado. Demais projetos no VPS permanecem fora do escopo.

## Dependências externas

SMTP, INLABS, DataJud e storage off-host: `EXTERNAL_BLOCKER` até configuração real. Preparação e testes isolados não equivalem a operação externa demonstrada. Sua ausência não bloqueia as demais frentes.

## Gates ainda não satisfeitos

`P0_COMPLETE=NO`

`P1_COMPLETE=NO`

`P2_COMPLETE=NO`

`READY_FOR_PRODUCT_BUILD=NO`

Impedimentos atuais: configuração de deploy ainda ambígua, secrets excessivos em serviços IA, aplicação com privilégio de superusuário, autorização administrativa incompleta, parser com acesso a credenciais, quotas ausentes, histórico de provas mutável e controles de estudo ainda transitórios/demonstrativos. Cada item exige implementação e execução dos testes antes de alterar esses gates.
