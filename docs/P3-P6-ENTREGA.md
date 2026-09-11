# P3–P6 — plataforma educacional

Execução incremental iniciada em 10/09/2026 a partir de `8a36d5fc993a26f621462bc87c2717780639c6b4`, na branch `astra/kairos-p3-p6-produto`.

**Entrega em andamento. PRODUCT_CORE_READY=NO.** A aprovação do trabalho P0–P2 autoriza a próxima implementação; não transforma os gates operacionais pendentes em evidências de produção.

## Baseline imediatamente anterior

Revalidação somente leitura em 10/09/2026 22:42:55 UTC, evidência externa ao Git `modernizacao/evidencias/p3-p6-initial-state.json`:

- HEAD local `8a36d5fc993a26f621462bc87c2717780639c6b4`; `origin/main` atualizado `cb4708d80b8214e931bc94a871e2ee5e130a4dbf`.
- Checkout VPS `/opt/kairos/current`: `f6ac1c3c510a4f442b9101d599e6598fe8428ca0`, limpo.
- API implantada: `8f341aa4c87e2a6692b557cfafd0204bee7b910c`; imagem `sha256:078a0937a5a89cc374cd43c3848d105587d4ea7c0f82807e7f7352fdff417eee`.
- Compose histórico e override `/opt/kairos/runtime/p0/20260909T194305Z/source/infra/compose/p0-api.override.yaml` continuam ativos. Ponteiro canônico de release ausente.
- API, web, PostgreSQL, Redis, MinIO, WordPress, ClamAV e edge saudáveis, zero reinícios; worker em execução sem healthcheck.
- PostgreSQL: 19 migrations, 3 usuários; `kairos_app` ainda superuser/createdb/createrole.
- Disco livre: 50.659.438.592 bytes; memória disponível: 5.409.536 KiB.
- Timers de backup e saúde ativos e habilitados. Backup recente `kairos-predeploy-20260910T222458Z-abe1a93603cc.tar.gz.enc`: 68.903.872 bytes, modo 0600, checksum válido. Restore/migrations isolados desse arquivo estão documentados na entrega P0–P2.
- Nenhum recurso de produção alterado nesta etapa. As pendências de cutover integral, rollback operacional e ativação dos privilégios mínimos permanecem em `P1-CUTOVER-PENDING.md`.

## Decisão administrativa

Solução híbrida: painel editorial próprio, renderizado pelo Django e apoiado nos comandos de negócio existentes; Django Admin permanece para formulários operacionais especializados. Next.js continua responsável pela experiência do aluno e pelo login com MFA. WordPress permanece público/editorial institucional.

Motivo: o admin anterior usa formulários genéricos e não oferece ações editoriais completas. Reutilizar transações, autorização e versões imutáveis reduz duplicação e mantém o fluxo operacional sem terminal, JSON ou identificadores técnicos digitados pelo operador. O primeiro recorte é conteúdo e taxonomia; as demais áreas ainda não são declaradas completas.

## Lote P3.1 — operação editorial

Alterações:

- Navegação, indicadores editoriais reais, busca por título, filtro por disciplina/situação, paginação e estados vazios.
- Criar disciplina/tema/subtema por formulário. Vínculos existentes de temas não podem ser movidos pelo admin especializado.
- Criar rascunho, prévia segura, nova revisão, histórico, comparação com versão anterior e restauração para novo rascunho.
- Enviar para revisão, aprovar por outra pessoa, publicar e arquivar pelos serviços existentes. POST repetido não executa a decisão seguinte.
- Importar acervo antigo por prévia e confirmação, deduplicação e revisão humana. GET de prévia não cria dados.
- MFA obrigatório mesmo sem `is_staff`; autorização real por ação, CSRF e respostas privadas sem cache. Texto escapado, sem executar HTML.
- Fonte, datas e comentários por campos amigáveis; hash gerado no servidor com indicação explícita de que é hash do texto autoral. Não se afirma que o site da fonte foi coletado.
- Paleta Kairós, símbolo existente e Montserrat local sob licença OFL; formulários responsivos e foco visível.

Arquivos: `apps/api/core/editorial_*.py`, `core/templates/editorial/*`, `core/static/editorial/*`, `core/admin.py`, `kairos/urls.py`, `tests/test_editorial_workspace.py`, `tests/browser/*`, `apps/web/components/LoginForm.tsx`.

Migrations: nenhuma neste lote; modelos P0–P2 reutilizados. Novos registros são inseridos somente pelo operador autorizado.

Testes e evidências: 17 testes HTTP do painel passaram; revisão B independente Django executou 76 testes com sucesso, com 3 concorrências PostgreSQL explicitamente pendentes. A revisão B inicial encontrou limites divergentes entre formulário/PostgreSQL e validação do pai fora da transação. Ambos receberam correção e regressões. O E2E real passou com senha/TOTP no Next.js, criação de disciplina/conteúdo, revisão/publicação por três papéis e aluno negado (403); desktop 1440×1000 e mobile 390×844, sem overflow e sem erros inesperados. HTTP428 no desafio MFA é esperado e verificado. Evidências externas: `modernizacao/evidencias/p3-editorial-browser/editorial-browser.json`, `editorial-desktop.png`, `editorial-mobile.png`. Rerun final/imagem em preparação.

Problemas de executor resolvidos: o Chromium esperado pelo Playwright não estava instalado; o Chromium alternativo falhou no spawn; Chrome local com perfil descartável funcionou. O proxy de teste passou a encaminhar WebSocket do Next.js; sem isso não ocorria hidratação. Os controles do login aguardam hidratação e o destino editorial usa URL local fixa, fora do roteador Next.js. Uma tentativa de executar scripts via pnpm iniciou instalação automática local; arquivos auxiliares gerados foram removidos e a verificação usou diretamente os executáveis Node/TypeScript/ESLint, preservando `package-lock.json`. Esses eventos não envolveram produção nem alteração das dependências declaradas.

Validação local adicional: suíte API completa com 448 testes aprovados e 19 skips explícitos de plataforma/integrações/browser; o browser foi executado separadamente e passou duas vezes, com a última execução em 9,90 s. TypeScript, ESLint sem warnings e build Next.js otimizado passaram. Ruff e `git diff --check` passaram. As imagens e os testes PostgreSQL do novo commit ainda precisam ser registrados.

Commit de implementação P3.1: `09be6528bad29317810f2c9b341756b1bb410b5c`. Imagem API validada: `sha256:8beec4844964c458ed39dc16a95ea8d65d04b152068f4634066b20c8ab29e6ed`; parser: `sha256:12fd91b8b3d97d27a7a4ebadf579e90d415d67c7bc06b74a0b4125eb2efdf421`. Não implantadas. Guia leigo: [EDITORIAL.md](EDITORIAL.md).

Validação Linux/PostgreSQL/Redis/ClamAV/MinIO: **466 API PASS**, um skip explícito do E2E opt-in executado separadamente; **184 operações/parser PASS**, três contratos Git sem executável nessa imagem, cobertos pela execução separada de 13 contratos Git. WordPress/MariaDB com 12 processos: uma única reivindicação de nonce aceita; PHP, Caddy, inventário do código e smoke Gunicorn/admin passaram. Execução: `/opt/kairos/runtime/p0/20260910T231702Z-foundations`; evidência detalhada `/opt/kairos/runtime/tests/kairos-test-20260910T231752Z-9b4573ffc37e`; recibo local `modernizacao/evidencias/p0p2-candidate-20260910T231702Z.json`. Comparação de recursos antes/depois: todas as contagens de alterações iguais a zero. Scan do commit: 17 valores de credenciais comparados a 330 arquivos, nenhuma ocorrência; valores não impressos.

A última revisão B identificou uma falha restrita ao proxy do harness local: URLs absolutas poderiam mudar o destino do encaminhamento. O executor agora exige origin-form, Host/Origin locais e origem do upstream fixa, inclusive em WebSocket. Cinco ataques HTTP reais contra servidor-armadilha loopback retornaram 400 com zero encaminhamentos; dois controles HTTP retornaram 200. A revisão B também comprovou WebSocket inválido bloqueado e controle válido 101. O E2E completo com esse executor passou em 9,80 s contra o build Next.js otimizado. Essa correção posterior altera somente testes/documentação; o código runtime da imagem permanece o de `09be652`. Nenhum dado de produção foi usado no navegador.

Rollback: retornar ao artefato anterior remove as novas rotas e formulários, preservando versões, aprovações, taxonomia e provenance nos modelos existentes. Publicação indevida deve ser arquivada pelo comando autorizado; restauração editorial cria revisão e exige nova aprovação. Não reverter dados com DELETE. A troca da release completa depende do coordenador de cutover/rollback P1 e do backup validado.

## Matriz funcional

### Lote P3/P5 — autoria de questões e treino persistente

Alteração: formulários de prova/caderno e questão; pacote versionado com enunciado, alternativas, gabarito, dificuldade, origem, subtema, fundamento, fonte, vigência, anulação e alteração de gabarito. Revisão independente, publicação e arquivamento auditados. A nova revisão preserva publicação anterior e tentativas congeladas. A tela Next.js substitui a questão demonstrativa por filtros reais, resposta calculada no servidor, explicação, favorito, revisão e histórico recuperados da conta.

Motivo: a fundação anterior não oferecia autoria leiga nem treino completo conectado aos dados publicados. O fluxo reutiliza o engine transacional; nenhum backend foi substituído e nenhum conteúdo legado foi publicado automaticamente.

Arquivos: `core/question_{models,workflow,forms,editorial}.py`, `core/practice_views.py`, serializers/views/urls, services/attempts e study_state, formulários/templates editoriais, migrations 0007/0008, `QuestionPractice.tsx`, `ModuleWorkspace.tsx`, CSS, testes de questões/treino/concorrência/navegador e `scripts/database-roles.py`.

Migrations: `0007_question_editorial` e `0008_objective_answer_facts`, aditivas. Não recalculam respostas antigas. Grants candidatos agora impedem UPDATE/DELETE em alternativas e metadados. Ainda exigem execução e verificação em banco real antes de declarar privilégio mínimo operacional.

Bugs encontrados e corrigidos pela revisão: acesso a gabaritos via treino genérico durante formal; oracle de estatística com dois formais simultâneos; alternativa/metadado alterados depois da aprovação; sete queries adicionais por questão; bloqueio FOR UPDATE sobre FK nullable no PostgreSQL; marcações da questão anterior durante GET pendente; retentativa infinita em erro definitivo; histórico assíncrono antigo sobrepondo atualização recente. A conferência visual também corrigiu largura do histórico, selects e link de salto de conteúdo.

Testes: suites HTTP/RBAC/ownership, idempotência, restrição de formal, adulteração por UPDATE e INSERT, crescimento de queries e migrações sem drift. Suíte anterior à última correção específica PostgreSQL: 467 API PASS/19 skips; testes novos de crescimento e concorrência foram acrescentados. Revisão B do módulo: 57 PASS/1 skip PostgreSQL antes da correção OF(self), com nova validação de imagem pendente. E2E real ampliado passou com criação de prova/questão → revisão/publicação → aluno responder → histórico → marcações → refresh; último registro anterior à adição do deadline interno: 15,24 s. Desktop e mobile 390×844, zero overflow, coluna de leitura com largura mínima verificada. Build Next.js, TypeScript e ESLint passaram. Evidências atuais em `modernizacao/evidencias/p3-editorial-browser/`, incluindo `practice-mobile.png` e `practice-desktop.png`.

Benchmark B: 1 questão = 12 queries; 10 questões = 12 queries (antes, 19 e 82). Medição em banco isolado local, não representa latência pública nem benchmark de capacidade de produção.

Fechamento local: suíte completa com **468 PASS/20 skips explícitos** (inclui novo teste PostgreSQL de admissão concorrente, executável na imagem). E2E após deadline interno e última correção PostgreSQL: **PASS em 12,26 s**, sem erros de console, com histórico legível, foco/link de salto e marcas recuperadas. SQL de privilégios: 9 testes PASS; migrations sem drift, Ruff, TypeScript, ESLint e build otimizados PASS. B confirmou retentativa/ownership, eliminação de N+1, descarte de histórico antigo e encerramento normal do browser antes do watchdog externo. A verificação real PostgreSQL do candidato ainda está pendente nesta revisão documental.

Executor: servidor manual Next.js recebeu bloqueio automático sem justificativa adicional. Foi substituído por fixture de teste loopback com porta descartável, API do live_server, readiness limitada, timeout e encerramento em finally; essa alternativa foi aceita e executada. O navegador tem deadline interno anterior ao watchdog externo. Nenhum perfil pessoal ou dado de produção usado.

Commit/imagem/deploy: candidato ainda em fechamento; registrar hashes após validação Linux. Nenhum deploy deste lote. Rollback: voltar ao artefato anterior seguro mantendo schema e registros; não fazer reverse migration destrutiva nem retornar à API vulnerável. Restore e reconciliação de grants fazem parte do gate da release, descritos em [P5-QUESTOES.md](P5-QUESTOES.md).

“Disponível” abaixo significa produção verificada, não somente código local.

| Funcionalidade | Implementada | Testada | Disponível ao aluno | Disponível ao admin | Pendência | Evidência |
|---|---|---|---|---|---|---|
| Administração editorial sem JSON | Parcial | HTTP/RBAC e E2E real | Não | Não | Completar áreas e publicar release | `test_editorial_workspace.py`, `editorial-browser.json` |
| Disciplina → tema → subtema | Criar/listar | Validação, limites e corrida de pai | Não | Não | Associação editorial completa e deploy | Testes de taxonomia |
| Rascunho → revisão → aprovação → publicação | Sim, serviços reutilizados | Serviço, HTTP e E2E real | Não | Não | Deploy | `test_content_workflow.py`, `editorial-browser.json` |
| Histórico/restauração de conteúdo | Sim, restaura para rascunho | HTTP e preservação da publicação | Não | Não | Comparação detalhada, agendamento e deploy | Teste de workflow completo |
| Legado não verificado | Prévia/importação/revisão | Serviço existente; UI a ampliar | Não | Não | Mesclar/rejeitar/classificar em lote | `content_workflow.py` |
| Editor visual e anexos relacionados | Não | Não | Não | Não | WYSIWYG, múltiplos anexos e metadados pedagógicos | Pendente |
| Usuários/planos e painel de operação completo | Fundação backend | P0–P2 | Não verificado | Não verificado | Jornadas leigas completas | Entrega P0–P2 |
| Dashboard, metas, notas, arquivos, Pomodoro | Fundação existente | P0–P2 | Release antiga apenas | Não | Jornada e próximo passo pedagógico | Entrega P0–P2 |
| Questões e treino | Autoria/revisão/publicação, filtros, resposta, marcas e histórico | API/RBAC e E2E real; imagem PG pendente | Não | Não | Sessões personalizadas completas e deploy | `test_question_editorial.py`, `test_practice.py`, `editorial-browser.json` |
| Simulado 1ª fase, autosave e nota | Engine inicial | Consistência P0–P2 | Não verificado | Não | Configuração e E2E completo | `test_attempt_consistency.py` |
| Analytics pedagógicos | Parcial | Consultas básicas | Não verificado | Não | Metas quantitativas, tendências e recomendações determinísticas | Pendente P4/P5 |
| Casos/peças/espelhos de 2ª fase | Modelos iniciais | Insuficiente | Não | Não | Modelo complementar e editor visual de critérios | Pendente P6 |
| Prova 2ª fase, autosave e submissão | Não completa | Não | Não | Não | Editor, recuperação, envio imutável e histórico | Pendente P6 |

## Execução do navegador

Harness opt-in `tests/browser/test_editorial_browser.py`: Django test database descartável, Next.js iniciado/encerrado pela própria fixture, proxy somente loopback e usuários sintéticos. A senha e o TOTP sintéticos passam por stdin e nunca são gravados em evidências. Definir `KAIROS_BROWSER_TESTS=1`, `KAIROS_NODE_BIN`, `KAIROS_PLAYWRIGHT_MODULE`, `KAIROS_CHROMIUM_EXECUTABLE` e diretório externo de evidências `KAIROS_BROWSER_EVIDENCE_DIR`. Preparar build Next.js local e executar pytest com `--ds=kairos.test_settings`. Nunca apontar esse harness para produção.

Fallback de automação: Browser plugin not available; Playwright regular instalado no runtime. O Chrome local usa perfil descartável, sem perfil pessoal. Alvos: login Next.js/senha/TOTP → formulários Django → publicação por três papéis; bloqueio de aluno; desktop 1440×1000 e mobile 390×844.

## Próximos lotes e gate

Concluir o painel editorial com evidências A/B, ampliar autoria de questões e provas usando as versões existentes, implementar a jornada de treino/simulado, e completar casos/espelhos/submissões da segunda fase. Cada lote recebe testes e documentação antes da homologação e da implantação. A modernização completa ainda exige resolver as pendências operacionais herdadas e executar os quatro E2E exigidos pelo usuário.

`PRODUCT_CORE_READY=NO`
