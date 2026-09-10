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

## Lotes implementados, ainda não implantados

O último candidato enviado ao ensaio Linux nesta execução é o commit `928cebc`, da branch acima. A produção continua na revisão e imagem registradas no baseline inicial. **Código implementado não equivale a correção já operacional.**

| Alteração e motivo | Arquivos principais | Migration | Evidência local / estado |
| --- | --- | --- | --- |
| RBAC por recurso/ação, revogação atual, identidade de serviço e MFA; impedir elevação de papel e acesso cruzado | `apps/api/core/permissions.py`, `rbac_policy.py`, serviços e testes RBAC | `0003` | Testes de API incluídos na suíte completa; privilégios reais ainda dependem do ensaio PostgreSQL e deploy |
| Tentativas com questões congeladas, estado transacional e idempotência; preservar nota/histórico | modelos e serviços de tentativa, `test_attempt_*` | `0002` | Testes de ownership e finalização passaram localmente |
| Persistência de estudo por usuário e migração do browser sem sobrescrita; revisão humana do legado | `study_models.py`, `content_workflow.py`, serviços, páginas Next.js | `0005`, `0006` | API e frontend testados; concorrência real e E2E ainda pendentes |
| Quotas, quarentena, scanner, parser isolado e download autenticado privado | `upload_models.py`, `services/uploads.py`, `services/parser`, testes de upload | `0004` | Testes locais passaram; pipeline ClamAV/MinIO/parser real reservado ao ensaio isolado |
| Credenciais por serviço, papéis PostgreSQL, ACL Redis e release por commit/imagem | `config/service-secrets.json`, `scripts/release-*`, `database-roles.py`, `redis-acl.py`, Compose | Sem migration adicional | Contratos locais; aplicação no VPS pendente |
| Backup/restore automático verificável, retenção, integridade, adapter off-host e health | `scripts/backup-*`, `verify-restore-isolated.sh`, `health-report.py`, units Kairós | Não | Recuperação histórica real PASS abaixo; nova rotina ainda exige prova com release canônica |
| Dependências vulneráveis e módulos herdados na imagem | `Dockerfile.release`, `requirements.runtime.lock`, inventário/testes do artefato | Não | `b15f7f4`; 54 versões Python candidatas sem alertas OSV consultados; instalação Linux ainda não comprovada |
| MFA administrativo WordPress, inclusive acesso interno | `core/wordpress_auth.py`, Caddy, MU-plugin e testes | Não; nonce efêmero em options WordPress | `f821976`; 42 testes Django; PHP/Caddy/HTTP/MariaDB real pendentes |
| Exceções de rede sem alterar política global ou recursos alheios | comparador e `release_network_policy.py` | Não | `8c0e00c`; 47 testes passaram após correções de ordem, negação e identificação de projeto |

Bugs encontrados durante a verificação independente: regra negada era interpretada como disjunta; ACCEPT/DROP do mesmo bridge podiam trocar de ordem sem reprovação; nomes com prefixo Kairós podiam ocultar container de projeto alheio; a conferência de artefato cobria somente quatro módulos; parent symlink no runner podia redirecionar arquivos de teste. As correções foram implementadas com casos negativos. A validação final de rede ainda precisa resolver o plano anterior ao deploy e os IDs Docker criados posteriormente, sem gerar autorização a partir do snapshot posterior.

## Testes desta continuação

- Suíte API após os últimos lotes: **428 passed, 18 skipped**, Ruff PASS. Os skips são explícitos: imagem, symlink no Windows, concorrência PostgreSQL/Redis e pipeline de upload real. Não foram contados como aprovação.
- Recorte MFA WordPress, inventário completo e HTTP MFA: **59 passed, 2 skipped**.
- Comparador de release/rede/projeção: **47 passed** após correção e nova execução.
- Frontend: typecheck, ESLint e build Next.js passaram. `npm audit --omit=dev`: zero vulnerabilidades informadas. E2E visual/navegação ainda pendente.
- Contratos de secrets/wrapper/paths: **8 passed, 7 skipped** por requisitos Linux/root/symlinks. A suíte operacional completa será executada dentro do ambiente isolado Linux.

Os agentes auxiliares atingiram limite de uso da conta durante a revisão; verificações independentes interrompidas não foram declaradas concluídas. A execução local continuou. Nenhum reset de conta foi consumido.

## Backup e recuperação comprovados nesta execução

Backup: `/srv/kairos/backups/kairos-predeploy-20260910T183825Z-0d5d600abfd7.tar.gz.enc`.

Restore isolado: PASS em `/srv/kairos/backups/kairos-restore-20260910T183839Z-d0e4060ded67.evidence`; evidência local `modernizacao/evidencias/p0p2-recovery-proof.json`. Comparação anterior/posterior: `PREEXISTING_RESOURCES_MODIFIED=0`. Esse ensaio usou a rotina anterior validada; não prova ainda a nova rotina de release/scoped credentials.

Inventário WordPress às 19:39 UTC: core 7.1, PHP 8.3.33, Elementor 4.2.3, Hello Elementor 3.4.9, MU-plugin visual Kairós; nenhum MU-plugin de MFA observado. Evidência: `modernizacao/evidencias/p0p2-wordpress-inventory.json`. Inventário de arquivos não substitui a verificação de plugins ativos ou análise de vulnerabilidades.

## Deploy, rollback e benchmark

Ainda não houve deploy das fundações. Nenhuma migration deste lote foi aplicada ao banco produtivo. As imagens candidatas serão registradas somente depois do build efetivo; a etiqueta de commit não basta sem teste do inventário da imagem.

Primeiro build do candidato `928cebc` falhou antes da criação da imagem: BuildKit interpretou `FROM sha256:<image-id>` como nome de repositório, apesar da imagem local existente. Corrigido o builder para criar uma referência local Kairós cujo ID é conferido exatamente antes do uso. Os testes integrados não chegaram a executar nessa tentativa (`INTEGRATION_EXIT=125`). Comparação no-touch PASS, todas as categorias zero; evidência `modernizacao/evidencias/p0p2-candidate-20260910T210706Z.json`.

Rollback operacional produtivo continua sendo a release anterior com o backup restaurável acima. Para os commits locais, usar revert sem reescrita de histórico. Reversão de dependências ou do gate WordPress pode reabrir riscos conhecidos: manter os endpoints administrativos bloqueados até uma alternativa validada. Não remover volumes nem apagar conteúdo para reverter código.

O benchmark versionado `scripts/benchmark-foundations.py` mede serialmente p50/p95 de rotas públicas via loopback do VPS. Ele não representa carga autenticada, contagem de queries ou teste N+1. Otimizações adicionais dependem de medições.

Baseline de performance às 21:13 UTC, 30 amostras após duas de aquecimento, concorrência 1, API produtiva `078a0937`: live p50/p95 **2,721/4,686 ms**; ready (PostgreSQL/Redis) **3,734/7,564 ms**; `/app` **10,213/19,971 ms**, todas respostas 307 (mede redirecionamento, não renderização autenticada); WordPress `/` **77,462/100,340 ms**, HTTP 200. API usava 198,5 MiB, web 72,41 MiB, PostgreSQL 43,23 MiB, Redis 6,566 MiB, worker 30,9 MiB, MinIO 126 MiB no snapshot posterior. A coleta coincidiu com o ensaio candidato; não serve como comparação de carga controlada. Evidência: `modernizacao/evidencias/p0p2-performance-baseline.json`.

Segundo candidato `e6b45dc`: build PASS, API `sha256:8407f1b0a48ce449623766c7bea707f1bc73fd39466540acc1affeb1c0f1826c`, parser `sha256:0ea06b30d3dea31d90175ebb61528d0585fe63efa5b9af194b8e0796c3a7b302`. Suíte Linux: **414 passed, 32 failed**, sem skips; os seis cenários de upload real passaram. Causas encontradas: lookup JSONB de hash comparado a varchar no PostgreSQL; resolução antecipada de path de testes fora da árvore local; fechamento de streaming response dentro da transação sintética do teste. Corrigidas no código/testes e sujeitas à repetição integral. As etapas nativas de privilégio/ACL/PHP/Caddy ainda não executaram porque a API reprovou antes. Cleanup PASS e no-touch PASS. Evidência `modernizacao/evidencias/p0p2-candidate-20260910T211047Z.json`.

## Dependências externas

SMTP, INLABS, DataJud e storage off-host: `EXTERNAL_BLOCKER` até configuração real. Preparação e testes isolados não equivalem a operação externa demonstrada. Sua ausência não bloqueia as demais frentes.

## Gates ainda não satisfeitos

`P0_COMPLETE=NO`

`P1_COMPLETE=NO`

`P2_COMPLETE=NO`

`READY_FOR_PRODUCT_BUILD=NO`

Impedimentos atuais: concluir a suíte Linux após as correções, validar privilégios/ACL/backup/restore da release canônica, implementar e provar a transição/rollback integral com plano de rede previamente autorizado, completar E2E e revisão independente, publicar a branch e implantar o commit/imagens exatos. Os controles de backend, quotas, persistência e limites já existem na branch, mas ainda não mitigam os serviços antigos em produção. O limite de uso interrompeu parte da revisão independente; não foi tratado como aprovação. SMTP/INLABS/DataJud/off-host ausentes não são os motivos desse NO.
