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
| Dependências vulneráveis e módulos herdados na imagem | `Dockerfile.release`, `requirements.runtime.lock`, inventário/testes do artefato | Não | Instalação e inventário Linux comprovados; 54 versões Python candidatas sem alertas OSV consultados, sem estender esse resultado a todos os pacotes do sistema operacional |
| MFA administrativo WordPress, inclusive acesso interno | `core/wordpress_auth.py`, Caddy, MU-plugin e testes | Não; nonce efêmero em options WordPress | 42 testes Django, PHP e Caddy PASS; HTTP integrado e plugins/rotas reais continuam pendentes; prova MariaDB descrita abaixo |
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

Ainda não houve deploy das fundações. Nenhuma migration deste lote foi aplicada ao banco produtivo. As imagens candidatas efetivamente construídas e testadas estão registradas abaixo; a etiqueta de commit não substitui o teste do inventário da imagem.

Primeiro build do candidato `928cebc` falhou antes da criação da imagem: BuildKit interpretou `FROM sha256:<image-id>` como nome de repositório, apesar da imagem local existente. Corrigido o builder para criar uma referência local Kairós cujo ID é conferido exatamente antes do uso. Os testes integrados não chegaram a executar nessa tentativa (`INTEGRATION_EXIT=125`). Comparação no-touch PASS, todas as categorias zero; evidência `modernizacao/evidencias/p0p2-candidate-20260910T210706Z.json`.

Rollback operacional produtivo continua sendo a release anterior com o backup restaurável acima. Para os commits locais, usar revert sem reescrita de histórico. Reversão de dependências ou do gate WordPress pode reabrir riscos conhecidos: manter os endpoints administrativos bloqueados até uma alternativa validada. Não remover volumes nem apagar conteúdo para reverter código.

O benchmark versionado `scripts/benchmark-foundations.py` mede serialmente p50/p95 de rotas públicas via loopback do VPS. Ele não representa carga autenticada, contagem de queries ou teste N+1. Otimizações adicionais dependem de medições.

Baseline de performance às 21:13 UTC, 30 amostras após duas de aquecimento, concorrência 1, API produtiva `078a0937`: live p50/p95 **2,721/4,686 ms**; ready (PostgreSQL/Redis) **3,734/7,564 ms**; `/app` **10,213/19,971 ms**, todas respostas 307 (mede redirecionamento, não renderização autenticada); WordPress `/` **77,462/100,340 ms**, HTTP 200. API usava 198,5 MiB, web 72,41 MiB, PostgreSQL 43,23 MiB, Redis 6,566 MiB, worker 30,9 MiB, MinIO 126 MiB no snapshot posterior. A coleta coincidiu com o ensaio candidato; não serve como comparação de carga controlada. Evidência: `modernizacao/evidencias/p0p2-performance-baseline.json`.

Segundo candidato `e6b45dc`: build PASS, API `sha256:8407f1b0a48ce449623766c7bea707f1bc73fd39466540acc1affeb1c0f1826c`, parser `sha256:0ea06b30d3dea31d90175ebb61528d0585fe63efa5b9af194b8e0796c3a7b302`. Suíte Linux: **414 passed, 32 failed**, sem skips; os seis cenários de upload real passaram. Causas encontradas: lookup JSONB de hash comparado a varchar no PostgreSQL; resolução antecipada de path de testes fora da árvore local; fechamento de streaming response dentro da transação sintética do teste. Corrigidas no código/testes e sujeitas à repetição integral. As etapas nativas de privilégio/ACL/PHP/Caddy ainda não executaram porque a API reprovou antes. Cleanup PASS e no-touch PASS. Evidência `modernizacao/evidencias/p0p2-candidate-20260910T211047Z.json`.

Terceiro candidato `7074583`: **445 passed, 2 failed**, sem skips, na API Linux; corrigidos os erros de JSONB e fixture anteriores. As duas expectativas remanescentes ignoravam a chamada de embeddings exclusiva do backend PostgreSQL; os testes agora verificam ambas as rotas permitidas e a autenticação. API `sha256:d87ee762405546745540f4baad4bbc96ca10ea9f5baab5b185abb1236c5a4f99`, parser `sha256:060b97cce3b92e212937f7f98caf79881fea91cdecbb97afcd664e9e09d89034`. Cleanup/no-touch PASS. A suíte nativa passou a ser executada também quando a suíte API reprova, conservando o resultado geral FAIL; isso evita ocultar falhas independentes. Evidência `modernizacao/evidencias/p0p2-candidate-20260910T212117Z.json`.

Quarto candidato `1c05dc9`: **API Linux 447 passed, sem skips**. Nativo: 175 passed, 4 failed, 4 skipped. PHP: `WORDPRESS_GATE_CONTRACT=PASS`. Falhas restantes de fixture: contagem de usuários ignorava service account criada pela migration; executáveis sintéticos de entrypoint estavam em tmpfs sem exec; contrato Caddy retirava a capability exigida pelo binário. Ajustes confinados às fixtures; não relaxam `/tmp` nem capabilities de aplicações em produção. Snapshot real de rede passou a acompanhar a suíte nativa; os três testes que exigem Git permanecem executados separadamente no host, em repositórios temporários próprios. Cleanup/no-touch PASS; evidência `modernizacao/evidencias/p0p2-candidate-20260910T212921Z.json`.

Branch publicada e [PR #2](https://github.com/Mnst-pixel/WJV_Brejo/pull/2) criado como rascunho. `main` permanece em `cb4708d8`. Scan do HEAD `c5bc7d7`: 17 valores de credenciais verificados contra 301 arquivos, nenhuma correspondência. Dois campos de exemplo DataJud foram esvaziados; valor externo, histórico e serviços produtivos não foram alterados.

Quinto candidato `d6d7f93573618887152790cbc14823a19c2600d3`: **BUILD/INTEGRATION/NO-TOUCH PASS**. API Linux: **447 passed**, sem skips. Nativo: **180 passed, 3 skips por ausência de Git na imagem**, cobertos pela execução separada de **13 testes Git no host**, todos PASS. PHP WordPress, Caddy validate, inventário completo do artefato, Gunicorn, static/admin e CSRF smoke passaram. Inclui papéis PostgreSQL reais, ACL Redis, migrations/restore sintéticos, parser/syscalls e uploads reais. API `sha256:f36d1608657e520e0af5be231401d847dea1007ea1e2199e079e0f27806efa5a`; parser `sha256:1cd8b52f6ab2bf4dc436db8196568d07a3b985b6f686ad54f543ace86fc7230f`. Evidência `modernizacao/evidencias/p0p2-candidate-20260910T213904Z.json`; detalhes protegidos em `/opt/kairos/runtime/tests/kairos-test-20260910T213958Z-455589ee7169`.

Sexto candidato `e7a87c526ead8769e84d7996549e004866650056`: **BUILD/INTEGRATION/NO-TOUCH PASS**. API Linux: **449 passed**, sem skips; nativo: **180 passed, 3 skips** cobertos pelos 13 contratos Git no host. PHP, Caddy, inventário, Gunicorn/static/CSRF passaram. API `sha256:09c1bb06e50aa6aee0a544b19ee8cefd03efb0611e0132c92ec7986f7b1a52d9`; parser `sha256:bfc7343b8bbd99ab09f91e75a109cd3978a19d587430f16498982ac143b6997f`. Evidência `modernizacao/evidencias/p0p2-candidate-20260910T215133Z.json`; detalhes `/opt/kairos/runtime/tests/kairos-test-20260910T215215Z-f9776102a3c9`. Recursos preexistentes modificados: zero.

Teste adicional de crescimento de queries: listas de notas/metas com 1 e 25 itens mantiveram **11 queries em ambos os tamanhos, tanto SQLite como PostgreSQL real**. Evidência PostgreSQL `modernizacao/evidencias/p0p2-query-growth-postgres.json`, extraída dos properties JUnit. Não é uma afirmação de ausência de N+1 em todos os endpoints. Próximos gates concretos: [P1-CUTOVER-PENDING.md](P1-CUTOVER-PENDING.md).

Lote `85e5e9c`: adiciona `wordpress/tests/test-admin-gate-mariadb.php` e fixture MariaDB ao runner, sem migration ou mudança de código produtivo. Primeira execução: API 449/nativo 180 PASS, mas contrato MariaDB FAIL por ausência do helper WordPress `is_multisite` na fixture. Acrescentado o helper de configuração single-site; a execução integral será repetida. A falha ocorreu no setup, antes da disputa de nonce, portanto não constitui falha comprovada do gate. Cleanup/no-touch PASS; evidência `modernizacao/evidencias/p0p2-candidate-20260910T215551Z.json`.

Inventário direto e somente leitura do WordPress às 21:59 UTC: Elementor é o único plugin ativo; template/stylesheet `hello-elementor`. Grants da aplicação: sem ALL global, SUPER global ou GRANT OPTION; ALL limitado ao banco WordPress. Há 13 hooks cron registrados, incluindo manutenção nativa, atualização e evento do Elementor. A existência de cron confirma que o bloqueio HTTP de `wp-cron.php` precisa de alternativa operacional validada antes do deploy. Nenhum evento foi executado por essa leitura. Evidência `modernizacao/evidencias/p0p2-wordpress-active.json`.

Ensaios WordPress posteriores: `1b5b63e` passou na disputa concorrente e parou no seed de opções por helper `is_wp_error` ausente; o seed passou a usar SQL preparado real (`485c5a8`). `aeec250` passou API **449**, nativo **184**, mas a limpeza MariaDB reprovou: o shim de hooks não executava o filtro nativo que restaura curingas de `wpdb::prepare`. Corrigido carregando `wp-includes/plugin.php` real (`73ccf7f`), sem alterar o plugin produtivo. Todas essas tentativas terminaram com cleanup/no-touch PASS; ainda exigem repetição integral do gate MariaDB. Evidências `p0p2-candidate-20260910T220032Z.json` e `p0p2-candidate-20260910T220629Z.json`.

Lote `aeec250` acrescentou ensaio opcional de migrations sobre cópia de backup real, com quatro testes de guarda/preservação PASS. Primeiro ensaio criou backup novo `/srv/kairos/backups/kairos-predeploy-20260910T221144Z-cd559fba6789.tar.gz.enc`, conferiu checksum/manifest e restaurou PostgreSQL, mas parou antes das migrations na guarda de endereço: o cast `inet::text` inclui `/32`. A guarda passou a usar `host(inet_server_addr())`, conforme [semântica oficial PostgreSQL 17](https://www.postgresql.org/docs/17/functions-net.html), mantendo a exigência exata de loopback. Isso é correção do verificador, não da aplicação. Cleanup/no-touch PASS; recuperação completa desse backup ainda não demonstrada nessa tentativa. Evidência `modernizacao/evidencias/p0p2-migration-rehearsal.json`; diagnóstico privado ficou no VPS sem exposição de linhas pessoais.

## Último candidato aprovado em testes isolados

Commit **`04abb6eecfd39ba329da02c6997274eabfaaa0c5`**, build e integração PASS:

- API: `sha256:13c8c3a1cc6dfac215e8a42a8ec5a65ffdb6a3e0e045eccef6cb7e887c0e3081`.
- Parser: `sha256:8c3b3df1856b13d93a3a7a25552c5a2eae9238b2882de476e34d5cd3df5fceb5`.
- API Linux/PostgreSQL/Redis: **449 passed**, sem skips. Três warnings de fixtures/JUnit documentados no log, sem falhas.
- Operação/parser Linux: **184 passed, 3 skips** por ausência de Git na imagem; contratos Git executados separadamente no host: **13 PASS**, incluindo os três casos (não somar tudo como testes únicos).
- WordPress PHP e **MariaDB real PASS: 12 processos concorrentes, exatamente 1 nonce aceito**; replay posterior, limpeza em lote, preservação de opções alheias, saturação e erro de banco cobertos.
- Caddy validate, inventário do código na imagem, Gunicorn, static/admin e CSRF smoke PASS.
- Cleanup PASS e `PREEXISTING_RESOURCES_MODIFIED=0` em todas as categorias do comparador.
- Evidência: `modernizacao/evidencias/p0p2-candidate-20260910T221348Z.json`; detalhes protegidos `/opt/kairos/runtime/tests/kairos-test-20260910T221429Z-b5bd0339cc14`.
- Scan do mesmo commit: 17 valores de credenciais versus 306 arquivos, sem correspondências. Ruff da API e dos novos scripts PASS.

Esse commit é um candidato testado, não o commit implantado. Mudanças posteriores exclusivamente documentais não alteram os IDs acima nem autorizam atribuir-lhes outro label OCI. O gate HTTP WordPress completo, a rotina cron, a migração com privilégios segregados e a transição/rollback integral permanecem separados. O teste MariaDB não exige nem realizou alteração de dados WordPress produtivos.

Segundo ensaio de recuperação (`04abb6e`): migrations executaram na cópia, mas a comparação de preservação interrompeu em `core_permission_roles`, a associação deliberadamente substituída pela migration 0003. O verificador havia usado o nome reverso do relacionamento como se fosse o nome físico da tabela. Corrigida a exceção única e acrescentada a conferência contra o modelo `Permission.roles.through`; não foram excluídos registros pessoais das verificações. Backup `/srv/kairos/backups/kairos-predeploy-20260910T221807Z-53dce9d8bd80.tar.gz.enc`, restore `/srv/kairos/backups/kairos-restore-20260910T221820Z-68f26bee74a1.evidence`, cleanup/no-touch PASS. Evidência `modernizacao/evidencias/p0p2-migration-rehearsal-04abb6e.json`.

## Dependências externas

SMTP, INLABS, DataJud e storage off-host: `EXTERNAL_BLOCKER` até configuração real. Preparação e testes isolados não equivalem a operação externa demonstrada. Sua ausência não bloqueia as demais frentes.

## Gates ainda não satisfeitos

`P0_COMPLETE=NO`

`P1_COMPLETE=NO`

`P2_COMPLETE=NO`

`READY_FOR_PRODUCT_BUILD=NO`

Impedimentos atuais: validar privilégios/ACL/backup/restore da release canônica sobre cópia restaurada do estado real; implementar e provar a transição/rollback integral com plano de rede anterior à alteração; completar HTTP WordPress, E2E fundamental e revisão independente; implantar e verificar o commit/imagens exatos. A suíte Linux isolada e a publicação da branch já foram realizadas. Os controles de backend, quotas, persistência e limites existem na branch, mas ainda não mitigam os serviços antigos em produção. O limite de uso interrompeu a revisão independente; não foi tratado como aprovação. SMTP/INLABS/DataJud/off-host ausentes não são os motivos desse NO.
