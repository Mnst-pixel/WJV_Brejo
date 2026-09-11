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

Validação final da imagem deste lote: commit **`f391a46866ba6a3aead07f7cba0cdae7f59579c1`**, enviado ao GitHub; fonte SHA256 `df0696564ba90d74c716c29d4eb1712bb3fef80be3d46acb98bbf74686e4f57d`; API **`sha256:a696192f7996211d5d45fe2a5b06447b387d6c1f13a0e9a75f9361e47a26f6bb`**; parser `sha256:3051e33384d6dfc9fcb42971ecd9611050e024bc1ad64169c1f2ffc17286f7eb`. **487 API PASS/1 skip browser opt-in**, 136,24 s, incluindo admissão concorrente de formal no PostgreSQL. **184 operações/parser PASS/3 skips Git**, cobertos separadamente por 13 contratos Git. MariaDB/WordPress: 12 concorrentes, um único nonce aceito; Caddy/PHP/Gunicorn e inventário PASS. Evidência `/opt/kairos/runtime/tests/kairos-test-20260911T000148Z-19baa0c6833a`; recibo local `modernizacao/evidencias/p0p2-candidate-20260911T000059Z.json`. Build, integração e no-touch terminaram com exit 0, todas as contagens de alteração de recursos preexistentes iguais a zero. **Imagem não implantada.** Essas evidências não incluem o incremento posterior de interface de simulados ainda em desenvolvimento.

### Lote P5 — preparação e realização de simulados

Alteração/motivo: a tela demonstrativa de simulados foi substituída por preparação de caderno publicado, filtros de disciplinas/dificuldade, quantidade, duração, randomização congelada, navegação, respostas/marcas com autosave, retomada, confirmação final e resultado calculado no servidor. O histórico é paginado. Configuração e respostas pertencem à conta; UUID de preparação e versão otimista permitem repetir envios incertos sem duplicação. A cópia temporária do navegador serve apenas para recuperar alterações ainda não confirmadas.

Arquivos: `core/simulation_views.py`, models/serializers/views/urls, services/attempts e ai_policy, mcp_boundary, practice_views, migrations 0009/0010, `SimulationWorkspace.tsx`, `student-api.ts`, browser-api, ModuleWorkspace/CSS e testes de simulado/MCP/navegador. Guia operacional: [P5-SIMULADOS.md](P5-SIMULADOS.md).

Migrations: `0009_simulation_preparation` e `0010_attempt_review_marks`, aditivas, sem recálculo histórico. Rollback mantém colunas e dados ao trocar para artefato seguro compatível. Restore/migrations e ativação de privilégios continuam gates anteriores à produção; não fazer reverse migration destrutiva nem retornar à API vulnerável.

Bugs encontrados/corrigidos: consulta IA sem contexto de tentativa contornava bloqueio formal; IDs de recurso inválidos causavam 500; token MCP anterior à prova precisava revalidar estado; autosave parcial não convergia ao limpar respostas; histórico truncado na primeira página; preparação incerta perdia UUID após refresh; tempo formal aceito do cliente podia ser inflado. Formal agora registra tempo do servidor também nos checkpoints; treino mantém seu contrato monotônico. Na infraestrutura de E2E, o banco SQLite em memória compartilhava conexão entre requisições paralelas; o harness passou a arquivo temporário WAL, sem tocar banco real.

Testes: API completa, revisão B independente, build/TypeScript/ESLint/Ruff e migrations sem drift. O navegador confirmou autoria/revisão/publicação/treino e simulado, interrompendo respostas HTTP após gravação real da preparação e do autosave; refresh recuperou a mesma tentativa e as marcas, seguido de submissão e nota. Mobile 390×844 e desktop, sem overflow/erros inesperados; `simulation-result-mobile.png` conferida visualmente. A primeira execução deste fechamento passou em 16,92 s; após correção do tempo formal, as verificações A/B estão sendo repetidas. Não atribuir ao novo lote a imagem anterior `f391a46`.

Fechamento A após correção do tempo: **480 API PASS/20 skips explícitos**, 79,97 s; **E2E PASS em 19,30 s**. Build Next.js/TypeScript, ESLint, Ruff e migrations sem drift passaram novamente. B backend repetiu **140 PASS/2 skips PostgreSQL/Redis** e reproduziu independemente tempo formal não inflável, checkpoints, replay, treino monotônico e prazo expirado. B frontend/harness executou controles de preparação, isolamento, paginação, snapshot, concorrência de edição/autosave, 409, falha, cancelamento e encerramento da fixture; rerun final após correção backend em fechamento.

Verificação B final frontend/harness após correção: **42 testes backend**, **11 controles TypeScript** e **4 cenários de encerramento** passaram, sem defeito reproduzível remanescente nesse recorte.

Commit **`61964bbcaed9172e53bab0cf8059b6bf7937e45d`**, enviado ao GitHub. Fonte SHA256 `eb6f9bea965a2f0d9cf2ee350fb8db05d4a1b998da12c0c90034abdfda291abd`; API **`sha256:216552910f258c55b6f611f913d3bcba6ddca49095d42992de7fd763548c40b5`**; parser `sha256:c1f0e095982d9b54d0ea363411a6911ac0c39944f4f3a0d60673ea033423695f`. Execução Linux: **499 API PASS/1 skip browser opt-in**, 142,15 s; **184 operações/parser PASS/3 skips Git**, 13 contratos Git executados separadamente com sucesso. WordPress/MariaDB: 12 concorrentes, um nonce aceito; Caddy/PHP/Gunicorn/inventário PASS. Evidência `/opt/kairos/runtime/tests/kairos-test-20260911T003909Z-4dfcb1534db6`, recibo `modernizacao/evidencias/p0p2-candidate-20260911T003824Z.json`. Build/integração/no-touch exit 0, todas as alterações de recursos preexistentes iguais a zero. Scan de 17 valores de credenciais contra 351 arquivos: nenhuma ocorrência. **Imagem não implantada.** O incremento posterior de segunda fase não está coberto por essa imagem.

Pendências: composição entre múltiplos cadernos e quotas por disciplina, resultado visual por tema/tempo, tendências/comparação histórica e paginação do catálogo além de 500 cadernos. A segunda fase e as jornadas administrativas restantes continuam pendentes.

### Lote P6 — casos, espelhos e prova escrita

Alteração/motivo: extensão dos modelos existentes de caso/rubrica, com área, metadados temporais, discursivas, critérios individuais, dependências e equivalências. Painel Django oferece criação de área/caderno/caso/espelho, adição/ordenação de itens, prévia reservada integral e decisões editoriais independentes. Next.js substitui a tela demonstrativa por catálogo publicado, editor longo, contador, navegação, autosave, recuperação, tela cheia, histórico e submissão imutável. Estruturas de correção/revisão preparam a fase seguinte; nenhum corretor é declarado operacional.

Arquivos: `core/second_phase_{models,workflow,forms,editorial,views}.py`, `services/written_submissions.py`, migration `0011_second_phase_written_exams`, modelos/admin/rotas, guards de formal, templates e JS editorial, `WrittenExamWorkspace.tsx`, ModuleWorkspace/CSS, testes API/concorrência/navegador e SQL de privilégios. Guia: [P6-SEGUNDA-FASE.md](P6-SEGUNDA-FASE.md).

Bugs encontrados/corrigidos: envio aceitava conjunto de respostas incompleto/adulterado; formulário genérico podia restaurar ponteiro de caso antigo; editor conseguia arquivar publicação; locks de responsáveis precisavam ordem consistente; rubricas e novas tabelas precisavam grants imutáveis; caderno duplicado produzia 500; revisão omitia contexto reservado e dependências; setas não alteravam ordem real e renomear referência apagava dependência silenciosamente. Corrigidos com bloqueios backend, projeção completa para revisão, erros de formulário e preservação explícita de referência órfã.

Migration 0011 é aditiva, sem publicação/conversão de conteúdo legado. Rollback mantém tabelas, textos, checkpoints e recibos; não reverter schema destrutivamente. Deploy exige restore/migrations reais e reconciliação dos grants antes de ativar as rotas.

Testes parciais já obtidos: **500 API PASS/23 skips**, **E2E das quatro jornadas PASS em 23,92 s**, incluindo gravação de texto longo seguida de perda intencional da resposta HTTP, refresh e envio da peça/discursiva. Revisão B backend após correções de formulário: **102 PASS/2 skips**, SQL **9 PASS/7 skips**; catálogo **14 queries para 1 e 10 casos**. Build/TypeScript/ESLint/Ruff e migrations sem drift passaram. Após os últimos ajustes de ordenação/dependências/foco, as verificações completas estão sendo repetidas. PostgreSQL inclui três novos cenários concorrentes, ainda pendentes da imagem exata.

Fechamento A: **500 API PASS/23 skips**, 87,42 s; **E2E completo PASS em 23,78 s**, incluindo setas de ordenação. Build/TypeScript, ESLint, Ruff, migrations sem drift e 9 testes SQL passaram. Screenshot mobile final conferida visualmente, sem overflow e com foco/restauração do scroll. B frontend: **20 testes backend, 10 controles TypeScript, 6 controles Chromium e 4 cenários da fixture PASS**, incluindo dependência órfã preservada e rejeitada pelo Django.

B backend final após hash ampliado: **102 PASS/2 skips**, três concorrências P6 explicitamente pendentes no executor local; SQL 9 PASS/7 skips. Provas independentes confirmaram bloqueio ao alterar número da versão, identidade ou versão da rubrica.

Commit **`80349c6372cd5b086e6760bec0ad46223b1c3006`**, enviado ao GitHub. Fonte SHA256 `359c2946f6b92eb2fbdc976093f8d70a91ce58cb7019920d80e59bee351ed0f3`; API **`sha256:b16ee2cd825c9f6028d16046ceb68ce29bea9c57076874361e8a0697223395ae`**; parser `sha256:250b9c362406b5f55a3d4e967dbba0a715692884f9a89be7103f10ca6d86ce12`. Linux/PostgreSQL: **522 API PASS/1 skip browser opt-in**, 161,28 s, incluindo as três concorrências de prova escrita. Operações/parser **184 PASS/3 skips Git**, cobertos separadamente por 13 contratos Git. WordPress/MariaDB: 12 concorrentes, um nonce aceito; Caddy/PHP/Gunicorn/inventário PASS. Evidência `/opt/kairos/runtime/tests/kairos-test-20260911T011517Z-45c38c9eda55`; recibo `modernizacao/evidencias/p0p2-candidate-20260911T011431Z.json`. Build/integração/no-touch exit 0; zero alterações de recursos preexistentes. Scan de 17 valores contra 367 arquivos: nenhuma ocorrência.

**Imagem não implantada.** Screenshot final `modernizacao/evidencias/p3-editorial-browser/phase2-submitted-mobile.png`; recibo do navegador no mesmo diretório. Pendências: restore/migrations/privilégios reais e release; correção humana/IA operacional é fase posterior. A imagem não inclui o incremento posterior de jornada de leitura/analytics.

### Lote P4 — leitura versionada e dashboard real

Alteração/motivo: tela de estudo conectada ao catálogo revisado, busca, fonte/data, percentual por publicação e histórico de versões lidas. Dashboard troca números demonstrativos por respostas/acertos diários, disciplinas, atividades, provas enviadas e próximo passo determinístico sem IA. Links de revisão/prática aplicam os filtros na abertura das questões. Notas e biblioteca completas permanecem recortes posteriores.

Arquivos: `core/learning_views.py`, content_workflow/serializers/views/urls, study_models/services/study_state/study_views, migrations 0012/0013, `ReadingWorkspace.tsx`, Dashboard/QuestionPractice/ModuleWorkspace/CSS, testes learning/navegador, reconciliação SQL e [P4-ESTUDO.md](P4-ESTUDO.md).

Migrations: **0012_reading_version_progress** e **0013_reading_history**, aditivas. Não presumem versão para progresso antigo. Snapshot preserva o último percentual confirmado de cada publicação anterior. Runtime candidato sem UPDATE/DELETE na tabela histórica. Aprovações com formato anterior de hash exigem nova revisão humana; não há revalidação automática ou alteração silenciosa dos recibos.

Bugs corrigidos: recomendação contornava o hash; campos jurídicos expostos estavam fora do digest; gravação de progresso não associava revisão; resumo podia concorrer com início formal; falha de GET após PUT bem-sucedido ocultava o problema de recarga. A tela agora conserva o contexto e exige reconciliação antes de nova gravação. Um seletor E2E identificou nome acessível ambíguo nos selects, corrigido sem mudar a aparência. Título de jornada duplicado no mobile removido.

Verificação A: **511 API PASS/23 skips explícitos**, 91,05 s; focados repetidos **74 PASS/4 skips PostgreSQL**, migrations sem drift e Ruff PASS. Build Next.js/TypeScript/ESLint PASS. E2E completo ampliado **PASS em 28,71 s** após correção de recuperação, desktop e 390×844, sem overflow/erros inesperados. Último rerun após ajuste de título/recibo em fechamento. Screenshots `reading-mobile.png` e `learning-dashboard-mobile.png` conferidas visualmente no diretório externo `modernizacao/evidencias/p3-editorial-browser/`.

B independente backend: **97 PASS/4 skips PostgreSQL**, incluindo probes dos hashes adulterados, ownership, formal congelado e revogação entre request/lock. MigrationExecutor isolado 0011→0013→0011→0013 preservou legado84%/posição12 com versão NULL. B frontend confirmou PUT200+GET falho, gravação incerta, requisições fora de ordem, paginação/origem, abort de período antigo e filtros de URL. Fechamento B em andamento.

Benchmark pontual local aquecido HTTP/SQLite sintético: catálogo com 1 conteúdo, **12 queries/7,32 ms**; 10 conteúdos, **12 queries/11,98 ms**; dashboard com 10 conteúdos, **35 queries/17,80 ms**. Não é p50/p95 público nem teste de capacidade. Nenhum cache foi adicionado.

Fechamento local: rerun final do E2E **PASS em 25,72 s**, com novo recibo `readingWorkflow`. B frontend final: **55 testes backend PASS/1 skip PostgreSQL**, **9 controles TypeScript PASS**, Chromium isolado com React/CSS real, payload malicioso escapado, URL javascript recusada e foco/labels/390×844 sem overflow. Nenhum achado reproduzível remanescente no recorte. SQL de privilégios: 9 PASS.

Commit **`ee6b1cf30f12181e9da885b139bfbed8aedd21e3`**, enviado ao GitHub. Fonte SHA256 `1f93ae8e5e79a1d9e11d40938a671f6b11bde7f7b65000adae9ab5f20ae631df`; API **`sha256:1470197c0fc5334eae17c657d2d841d3e28962c49e019e4ca09002c8ec1ca409`**; parser `sha256:16756fb2d0ec1b93189a1f3eee65a9820ff9fff00149559cb0b2add15de50ae8`. Execução Linux isolada: **533 API PASS/1 skip browser opt-in**, 163,85 s; **184 operações/parser PASS/3 skips Git**, 20,50 s, mais 13 contratos Git separados PASS. PostgreSQL, Redis, MinIO e ClamAV reais no ambiente temporário. MariaDB/WordPress:12 concorrentes/1 nonce aceito; PHP/Caddy/Gunicorn/inventário PASS. Execução `/opt/kairos/runtime/p0/20260911T014251Z-foundations`; evidência `/opt/kairos/runtime/tests/kairos-test-20260911T014338Z-7dd7fe469044`; recibo `modernizacao/evidencias/p0p2-candidate-20260911T014251Z.json`. Build/integração/no-touch exit0 e todas as alterações em recursos preexistentes iguais a zero.

**Não implantado.** Rollback preserva schema, leituras e recibos; não remover tabelas após uso e não reintroduzir hash menos abrangente. Release exige baseline, backup/restore, migrations/grants reais e coordenador P1. Próxima etapa: administração completa e recursos de estudo restantes. Esta imagem não cobre alterações posteriores de gestão de usuários.

### Lote P3 — administração de usuários e recuperação de acesso

Alteração/motivo: área de usuários com busca, filtros, cadastro sem senha, edição, papéis por caixas de seleção, suspensão/reativação, revogação e entrega de acesso. MFA, RBAC e versão otimista são revalidados no backend; suporte consulta somente cadastro autorizado. Contas com superusuário legado são identificadas e uma decisão explícita converte o privilégio para os papéis selecionados, sem autoelevação ou manutenção silenciosa do flag.

Arquivos: `core/account_{commands,forms,editorial}.py`, recovery_policy, rbac_views, models/serializers/views, rotas/templates/CSS editorial, migration 0014 e testes de contas/concorrência/navegador. Guia: [P3-USUARIOS.md](P3-USUARIOS.md).

Bugs corrigidos: decisões de papel sem versão; recuperação concorrente com o mesmo token; falha SMTP distinguindo conta existente por HTTP 500; ausência de limite compartilhado de recuperação; e-mail ambíguo por diferença de caixa; flag legado mantendo autoridade após seleção de Aluno. SMTP ausente/falho permanece um estado explícito, sem mensagem real enviada ou segredo exposto.

Migration **0014_unique_recovery_email** verifica colisões sem imprimir endereços e aplica índice parcial insensível a caixa. Não mescla nem exclui cadastros. Rollback conserva índice, contas e auditoria; artefato anterior deve preservar versão obrigatória e bloqueio de recuperação concorrente.

Verificação A final: **531 API PASS/25 skips explícitos**, 98,72 s; **E2E completo PASS em 31,22 s**, incluindo as jornadas educacionais anteriores e criar → editar → papéis → suspender → reativar → revogar → SMTP indisponível. Ruff PASS e migrations sem drift. Next.js não foi alterado neste lote. Screenshot `accounts-mobile.png` e recibo `accountsWorkflow` no diretório externo de evidências do navegador.

B backend final: **57 PASS/3 skips**, com probes independentes de conversão do superusuário legado, preservação do papel canônico, proteção de administrador comum e autoconcessão. B UI final: **20 PASS/2 skips PostgreSQL**, navegação por teclado, banner, filtro e 390 px sem overflow; nenhum achado reproduzível remanescente. Migração isolada reversa/reaplicada preservou dados e colisões abortaram sem expor informações pessoais. Testes PostgreSQL/Redis e imagem exata serão registrados após execução Linux. **Não implantado.** Planos e painel operacional completo são os próximos recortes.

Commit de usuários **`13835b89f6dafc8f2cd2fa971d7ea5dbfec7f079`**, enviado ao GitHub. Fonte SHA256 `2c56dfe71ad035b7c99aefb840b819ae8a18e72f259f5d7f84af606b84a58d75`; API **`sha256:033f3b55bd4a8707ff1fdea30aef0d4d141856035368176a715a55a21db9c62f`**; parser `sha256:112450a0d52fad8dcd433ddfc77e92326949a3ae3c32c77729ba27fec083beb1`. Linux isolado: **555 API PASS/1 skip browser opt-in**, 174,06 s; **184 operações/parser PASS/3 skips Git**, 21,56 s, mais 13 contratos Git PASS. Confirmação concorrente de recuperação em PostgreSQL e cooldown entre workers Redis passaram. WordPress/MariaDB:12 concorrentes/1 nonce aceito; PHP/Caddy/Gunicorn/inventário PASS. Execução `/opt/kairos/runtime/p0/20260911T021823Z-foundations`; evidência `/opt/kairos/runtime/tests/kairos-test-20260911T021910Z-91b122bbe3c1`; recibo `modernizacao/evidencias/p0p2-candidate-20260911T021823Z.json`. Build/integração/no-touch exit0 e zero mudanças em recursos preexistentes. **Imagem não implantada e não cobre o lote posterior de planos/matrículas.**

### Lote P3 — planos, matrículas e limites de arquivos

Alteração/motivo: formulários de planos, vínculo por pessoa, estado/validade e limites globais sobre os modelos existentes. Identificadores internos são automáticos; recibo assinado e transação impedem edição desatualizada e criação duplicada. A matrícula controla uploads, sem declarar cobrança ou pagamentos operacionais. Arquivos privados permanecem preservados e a UI mostra somente o espaço ocupado.

Arquivos: `core/subscription_workspace.py`, templates de assinaturas/formulários, links de usuário/navegação, rotas, upload_admin, testes de assinaturas/concorrência/admin/navegador e [P3-ASSINATURAS.md](P3-ASSINATURAS.md). **Sem migration.** Rollback conserva dados e bloqueio do gravador legado.

Bugs encontrados/corrigidos na revisão B: formulário genérico antigo permitia matrícula de conta privilegiada/serviço; links de ações indisponíveis apareciam para o próprio administrador; redirecionamento legado com PK inválida retornava 500. GET antigo agora encaminha ao painel canônico, POST/save_model antigo são recusados e identificador inválido retorna 404. Interface oculta ações que o backend não autoriza.

A final após todas as correções: **543 API PASS/28 skips explícitos**, 102,04 s; **E2E completo PASS em 32,24 s**, incluindo plano → matrícula → suspensão → busca → limites globais e todas as jornadas educacionais anteriores. Ruff PASS; migrations sem drift. Screenshot `subscriptions-mobile.png` conferida a 390 px, sem overflow. Os testes antigos de gravação genérica foram substituídos por testes do novo contrato e regressões que impedem reabrir o caminho legado.

B backend final: **53 PASS/5 skips**, 15,21 s; probes de todas as três rotas antigas, tokens por ator/tipo/alvo/expiração e gravação direta recusada. As três concorrências PostgreSQL usam atores distintos com recibos próprios para testar o mutex da configuração, além do lock do titular. B UI e imagem Linux final em fechamento. **Não implantado.** Próximo recorte: editor visual e demais jornadas administrativas/de estudo.

B UI final repetida: **25 PASS**, 12 casos de identificador inválido/inexistente com 404 nas três rotas legadas, controles CSRF/campos forjados/titularidade/links/escape e quatro telas Chromium a 390 px passaram. Nenhum novo defeito reproduzível. Imagem Linux exata ainda será registrada.

Commit **`17679fd51037a21f60c8372d849b066a075b4412`**, enviado ao GitHub. Fonte SHA256 `02285fcfeec5fedcee2df0ceffe32304ecf4715d5c7f1aa822d3dcd7bf774875`; API **`sha256:65af8846ba2e47fe13693f6e6ebbf69896be127da02f41c7505027a0aa951102`**; parser `sha256:b771a4908bdb7caaf6ebc510a340bc7d86094223ca7349759637fead8dac69e3`. Linux isolado: **570 API PASS/1 skip browser opt-in**, 176,37 s, incluindo as três concorrências de decisões com administradores distintos. Operações/parser **184 PASS/3 skips Git**, 22,05 s, mais 13 contratos Git PASS. WordPress/MariaDB:12 concorrentes/1 nonce aceito; PHP/Caddy/Gunicorn/inventário PASS. Execução `/opt/kairos/runtime/p0/20260911T023750Z-foundations`; evidência `/opt/kairos/runtime/tests/kairos-test-20260911T023836Z-24a4899ef22e`; recibo `modernizacao/evidencias/p0p2-candidate-20260911T023750Z.json`. Build/integração/no-touch exit0, zero alterações de recursos preexistentes. **Não implantado; não cobre o editor visual desenvolvido posteriormente.**

Git: PR de produto em rascunho [#3](https://github.com/Mnst-pixel/WJV_Brejo/pull/3), empilhado sobre a branch P0–P2. Não houve merge nem reescrita de histórico.

### Lote P3 — editor visual e leitura formatada

Alteração/motivo: editor visual com negrito, itálico, limpeza de destaque, parágrafo/títulos/citação/listas e desfazer formatação. Texto simples permanece canônico; uma AST limitada preserva a apresentação na revisão e na leitura Next.js. Não há dependência externa nova nem migration. O operador não vê HTML/JSON; revisão humana e hash da versão continuam obrigatórios.

Arquivos: rich_text, serviço content_workflow, editorial_forms/views, templatetag, templates/CSS/JS editorial, `RichText.tsx`, ReadingWorkspace/CSS, testes de AST/serviço/API e helper permanente `tests/browser/rich_editor.cjs`. Guia: [P3-EDITOR-VISUAL.md](P3-EDITOR-VISUAL.md).

Bugs corrigidos: CRLF de formulário rejeitava texto válido; limpeza mantinha marca herdada; seleção entre itens fundia listas; seleção de texto na raiz perdia o contexto dos parágrafos vizinhos; colagem substitutiva no limite era recusada; API contornava a validação do formulário. Validação agora é central, na criação e antes de aprovar/publicar; estruturas antigas inválidas são preservadas e exigem nova revisão. Nenhum HTML foi executado nos probes.

Build Next.js/TypeScript/ESLint PASS; Ruff PASS e migrations sem drift. E2E final **PASS em 32,48 s**, incluindo cinco regressões permanentes de edição em contexto sem rede e fluxo real de autoria → destaque → revisão → publicação → leitura formatada. Screenshot real `rich-editor-mobile.png` conferida, fonte/cores preservadas e sem overflow em 390×844. Fixture de teste corrigida para fornecer autor obrigatório; a suíte API completa está sendo repetida.

B backend final: **67 PASS/3 skips PostgreSQL**, 15,40 s; API inválida/divergente 400 sem conteúdo residual, LF/CRLF/CR equivalentes, bloqueio após adulteração e nenhuma revalidação silenciosa. B frontend final: **37 testes Django PASS**, Chromium/React renderer, helper permanente e cleanup após falha sintética passaram; nenhum achado remanescente no recorte. Imagem exata será registrada após Linux. **Não implantado.** Rollback conserva corpo, AST e recibos, sem reabrir aprovação de estruturas inválidas. Anexos e demais recursos pedagógicos continuam pendentes.

Fechamento A do editor após todas as correções: **563 API PASS/28 skips explícitos**, 91,46 s. E2E final e reviews B acima correspondem ao mesmo código; teste de fixture corrigido passou também na suíte completa. Nenhuma migration pendente; build/lint/type/inspeção visual passaram. A imagem será construída a partir do commit exato.

“Disponível” abaixo significa produção verificada, não somente código local.

### Lote P4 — biblioteca e notas privadas

Alteração/motivo: biblioteca usa o catálogo publicado e permite anotações pessoais com disciplina/tema e vínculo à versão lida. Criação idempotente por titular/UUID; edição com versão esperada; envelope temporário separado por conta e conferência após falha/reload. A versão histórica da leitura permanece associada à nota. Exclusão está bloqueada para preservar recibos e impedir ressurreição de pedidos antigos. Guia e rollback: [P4-ANOTACOES.md](P4-ANOTACOES.md).

Arquivos: StudyNote/model/serializer/viewset, personal_notes, migration **0015_personal_note_creation**, LibraryWorkspace/NotesWorkspace/notes.css, ReadingWorkspace, testes personal_notes/personal_note_concurrency/foundation_migrations e E2E editorial. Migração aditiva; dados antigos preservados, sem inventar vínculo jurídico. Rollback mantém schema e recibos, com DELETE protegido.

Bugs encontrados/corrigidos: exclusão antiga ignorava versão e destruía recibo; falha inicial bloqueava editor sem retry; navegação dentro da biblioteca não reagia à query; página antiga podia invalidar busca nova; CSS legado espremia títulos e aplicava cor inadequada na navegação. Testes e inspeção visual repetidos após as correções.

A final: **570 API PASS/30 skips explícitos**, 104,66 s; **E2E completo PASS em 37,41 s**, com criação de nota pela leitura → POST confirmado no servidor com resposta perdida → reload/conferência → PATCH com resposta perdida → recuperação de rascunho não enviado → edição → abertura canônica sem duplicatas. Os fluxos anteriores de administração, questões e ambas as fases permaneceram verdes. Build Next/TypeScript/ESLint/Ruff PASS; migrations sem drift. Screenshot `personal-notes-mobile.png` conferida em 390×844, largura de título acima de 240 px, sem overflow. Lista 1/11 notas: **11/11 queries** em probe B; não é benchmark público.

B UI final: **10 controles frontend PASS**, 7 testes backend PASS, Chromium/foco/labels/escape/contraste/mobile PASS. B backend anterior: **76 PASS/6 skips de concorrência PostgreSQL** e ensaio independente de migration forward/reverse/forward preservando notas antigas; repetição final incluindo o teste permanente ampliado em fechamento. Duas corridas PostgreSQL de criação/edição aguardam a imagem Linux. **Não implantado.** Exclusão, histórico completo de edições, flashcards e demais jornadas ainda não compõem este recorte.

B backend final repetido: **77 PASS/6 skips PostgreSQL**, 28,08 s, incluindo teste permanente de migration histórica. Sem achados pendentes no recorte. Baseline produtivo revalidado em **2026-09-11 03:28:58 UTC**: checkout `f6ac1c3`, API real `8f341aa`, mesma imagem/Compose histórico, health 200/containers saudáveis, worker sem healthcheck, timers ativos/habilitados, cerca de 50 GB livres e último backup local com checksum válido. O papel runtime ainda possui superuser e o pointer canônico continua ausente: gates P1 herdados permanecem abertos. Evidência `modernizacao/evidencias/p3-runtime-state-20260911-notes.json`; nenhuma mudança produtiva foi feita.

Imagem exata das notas: commit **`4368891a18bff5a827a112f4e353a068857ba676`**, fonte `10b3d1e3899ab49f86b5aba5d145dc5445d757b1e5b0c583649025c3c7e9775c`; API **`sha256:bc00888093c14b775f039f07aeb131b66f36295d5e6440ed71ad887313af8e88`**; parser `sha256:0455da9822f236715db87a1f50ff64a90d1b7c80c4a627a743cedebf837cf27b`. **599 API PASS/1 browser opt-in skip** em 187,21 s, incluindo ambas as corridas de notas e migration histórica no PostgreSQL. **184 operações PASS/3 skips Git** em 22,50 s, mais 13 contratos Git PASS; WordPress/MariaDB12→1 nonce, PHP/Caddy/Gunicorn/inventário PASS. Execução `/opt/kairos/runtime/p0/20260911T032932Z-foundations`; evidência `/opt/kairos/runtime/tests/kairos-test-20260911T033020Z-c6473bc3e9ec`; recibo `modernizacao/evidencias/p0p2-candidate-20260911T032932Z.json`. Build/integração/no-touch exit0; nenhum recurso preexistente modificado. Não implantado; não inclui o coordenador de transição em desenvolvimento.

Imagem do editor visual: commit `227609e2f5ebd1302c363141bfc939d3444f0d9d`; fonte SHA256 `ec0032f3e8183b2dea01342861501eccd5cfcb89e9ed90e8615d6b2b968502cd`; API `sha256:d3d33af5200f1c99c6cbcde810667d864b737788e0da39d78e23c42d79f93df3`; parser `sha256:991b375d2bbb3d414ea1c0d33a54f8ddfb6d9448b5742857255c2953a0e529c3`. Linux isolado: **590 API PASS/1 skip browser opt-in**, 181,41 s; **184 operações PASS/3 skips Git**, 21,44 s, mais 13 contratos Git PASS. WordPress/MariaDB: 12 concorrentes, 1 nonce aceito. PHP/Caddy/Gunicorn/inventário PASS. Execução `/opt/kairos/runtime/p0/20260911T030131Z-foundations`; evidência `/opt/kairos/runtime/tests/kairos-test-20260911T030218Z-a899fbdbfb64`; recibo `modernizacao/evidencias/p0p2-candidate-20260911T030131Z.json`. Build/integração/no-touch exit0; zero recursos preexistentes alterados. **Não implantado; esta imagem não contém as anotações em desenvolvimento.**

| Funcionalidade | Implementada | Testada | Disponível ao aluno | Disponível ao admin | Pendência | Evidência |
|---|---|---|---|---|---|---|
| Administração editorial sem JSON | Parcial | HTTP/RBAC e E2E real | Não | Não | Completar áreas e publicar release | `test_editorial_workspace.py`, `editorial-browser.json` |
| Disciplina → tema → subtema | Criar/listar | Validação, limites e corrida de pai | Não | Não | Associação editorial completa e deploy | Testes de taxonomia |
| Rascunho → revisão → aprovação → publicação | Sim, serviços reutilizados | Serviço, HTTP e E2E real | Não | Não | Deploy | `test_content_workflow.py`, `editorial-browser.json` |
| Histórico/restauração de conteúdo | Sim, restaura para rascunho | HTTP e preservação da publicação | Não | Não | Comparação detalhada, agendamento e deploy | Teste de workflow completo |
| Legado não verificado | Prévia/importação/revisão | Serviço existente; UI a ampliar | Não | Não | Mesclar/rejeitar/classificar em lote | `content_workflow.py` |
| Editor visual | AST, controles de formatação e leitura revisada | API/B/E2E real e imagem Linux | Não | Não | Release; editor de tabelas e anexos não incluído | `test_rich_text.py`, `rich_editor.cjs`, `P3-EDITOR-VISUAL.md` |
| Anexos relacionados e metadados pedagógicos | Parcial | Fundação de uploads | Não | Não | Múltiplos anexos e relações editoriais completas | Pendente |
| Usuários e acesso | Formulários, papéis, suspensão, revogação e MFA | API, B independente, E2E e imagem Linux | Não | Não | Release; SMTP externo para entrega de acesso | `test_account_workspace.py`, `P3-USUARIOS.md` |
| Planos, matrículas e limites | Formulários e decisões transacionais | API, B independente, E2E e imagem Linux | Não | Não | Release; cobrança não implementada | `test_subscription_workspace.py`, `P3-ASSINATURAS.md` |
| Painel de operação completo | Parcial | Recortes P0–P3 | Não | Não | Saúde/ingestão/jobs/armazenamento em visão integrada | Entrega P0–P2 e matriz atual |
| Leitura, progresso e dashboard | Publicação versionada, histórico e próximo passo determinístico | API, B independente, E2E e imagem Linux | Não | Autoria em candidato | Release, notas e marcações na leitura | `test_learning.py`, `P4-ESTUDO.md`, screenshots |
| Metas, notas, arquivos, Pomodoro | Fundação existente | P0–P2 | Release antiga apenas | Não | Metas quantitativas e jornadas de notas/flashcards | Entrega P0–P2 |
| Biblioteca e anotações privadas | Catálogo, criação, edição, busca, referência histórica e recuperação | API/B/E2E real e imagem PostgreSQL | Não | Não se aplica ao texto privado | Release, flashcards e demais recursos da biblioteca | `P4-ANOTACOES.md`, `test_personal_notes.py`, screenshot mobile |
| Questões e treino | Autoria/revisão/publicação, filtros, resposta, marcas e histórico | API/RBAC, E2E real e imagem PostgreSQL | Não | Não | Sessões personalizadas completas e deploy | `f391a46`, `test_question_editorial.py`, `test_practice.py`, `editorial-browser.json` |
| Simulado 1ª fase, autosave e nota | Caderno, filtros, timer, marcas, recuperação, envio e resultado | API, E2E com perda de resposta e imagem Linux | Não | Autoria de caderno em candidato | Combinação de cadernos, analytics ampliado e deploy | `test_simulation_builder.py`, `editorial-browser.json` |
| Analytics pedagógicos | Diário, disciplina/tema na API, acurácia, sequência e recomendações | API/ownership/formal e E2E dashboard | Não | Não | Comparação de provas, tempo médio e metas quantitativas | `test_learning.py`, `P4-ESTUDO.md` |
| Casos/peças/espelhos de 2ª fase | Modelos, formulários, critérios, ordenação, workflow e prévia integral | API/RBAC, E2E e imagem Linux | Não | Não | Grants, release e correção operacional futura | `test_second_phase.py`, `P6-SEGUNDA-FASE.md` |
| Prova 2ª fase, autosave e submissão | Catálogo, peça/discursivas, recuperação, envio e histórico | API/E2E com perda de confirmação e concorrência PostgreSQL | Não | Não | Release; corretor avançado na fase seguinte | `editorial-browser.json`, `test_second_phase_concurrency.py` |

## Execução do navegador

Harness opt-in `tests/browser/test_editorial_browser.py`: Django test database descartável, Next.js iniciado/encerrado pela própria fixture, proxy somente loopback e usuários sintéticos. A senha e o TOTP sintéticos passam por stdin e nunca são gravados em evidências. Definir `KAIROS_BROWSER_TESTS=1`, `KAIROS_NODE_BIN`, `KAIROS_PLAYWRIGHT_MODULE`, `KAIROS_CHROMIUM_EXECUTABLE` e diretório externo de evidências `KAIROS_BROWSER_EVIDENCE_DIR`. Preparar build Next.js local e executar pytest com `--ds=kairos.test_settings`. Nunca apontar esse harness para produção.

Fallback de automação: Browser plugin not available; Playwright regular instalado no runtime. O Chrome local usa perfil descartável, sem perfil pessoal. Alvos: login Next.js/senha/TOTP → formulários Django → publicação por três papéis; bloqueio de aluno; desktop 1440×1000 e mobile 390×844.

## Próximos lotes e gate

Operação para a release de produto: biblioteca pura `release_transition_plan.py` predeclara recursos/identidades/imagens/rede e limita o recibo posterior. A: 66 testes do conjunto PASS/1 skip; B: 28 testes existentes e 15 controles adversariais PASS. Guia [P1-TRANSITION-PLAN.md](P1-TRANSITION-PLAN.md). Sem migration/imagem/deploy; coleta real, freeze e coordenador continuam pendentes, portanto este recorte não declara P1 concluído.

Evolução operacional seguinte: `release_transition_io.py` adiciona coleta do socket local sem Env/Cmd, snapshot com inventário fechado e registros exclusivos 0600 (`FROZEN`, `STARTED`, `RECEIPT`). Corrigidos: arquivo opcional fora do manifesto; ancestral gravável; consulta desnecessária à imagem estrangeira já ausente; endereço vazio de container parado; IPv6 em attachment inativo; label OCI legada vazia. Não houve migration ou mudança de imagem produtiva. Rollback mantém evidências e retira somente as bibliotecas ainda não ativadas pelo deploy.

A final do conjunto: **72 PASS/11 skips locais**, 2,12 s; Ruff PASS. Linux isolado, uid10001, sem rede, filesystem somente leitura e tmpfs: **26 PASS/zero skips**, 0,122 s, incluindo exclusividade concorrente, modos, links, drift, manifesto, recibos e política de rede. Fonte baseada em `5f6a2d8` com quatro arquivos de trabalho capturados por hash antes do envio, SHA256 `63154b2fa1f9231a1af7a34adeb7247970cb34a3afb627680b230bec67b008cc`. Execução `/opt/kairos/runtime/tests/kairos-transition-io-20260911T035657Z`; recibo local `modernizacao/evidencias/transition-io-20260911T035657Z.json`; no-touch **zero alterações** de recursos preexistentes. Não é uma nova imagem do produto.

Coleta real passou em 03:50:41 UTC: 72 containers/18 Kairós/27 redes; estado `45f03e149abff6665a3e0b4dc87062d069f9bcea128a45d9283a0739984c3ede`. Ensaio **NOOP_ONLY PASS** em 03:58:48 UTC, sob `.operation.lock`: `/opt/kairos/runtime/transitions/kairos-noop-20260911T035811Z`; seis arquivos 0600, plano `6be86600eb1048640127048e707581b0ead48e5d6329bfc978f67b42aed0a56e`, manifesto `775d657a320ebfa12ea476fa313a6c3a5d0ebb01245e716a01760c4d71a9c0c8`. Comparador integral aprovado; nenhuma troca de serviço foi executada. Evidência `modernizacao/evidencias/transition-noop-real-20260911.json`. B final do código após as correções em fechamento. Guia [P1-TRANSITION-IO.md](P1-TRANSITION-IO.md). Ainda faltam coordenador mutável, manutenção/drenagem, migrations/grants, restore e rollback ensaiados.

B final repetido: **34 testes PASS/10 skips POSIX locais** e **53 controles independentes PASS**, sem achado reproduzível remanescente. Hashes de modelo/IO conferem com a execução Linux A final. O receipt sem mudanças não fecha P1 e não transforma as funcionalidades candidatas em funcionalidades disponíveis em produção.

Usuários, planos, editor visual, leitura e notas já compõem o candidato testado. Concluir as demais áreas do painel, metas quantitativas, flashcards e ampliações de simulados/analytics da matriz. Os quatro E2E exigidos foram executados no candidato; a disponibilidade em produção ainda depende da ativação operacional e da release coerente. Cada lote recebe evidências A/B, documentação e homologação antes da implantação.

### Grants, migrations e recuperação do candidato de produto

Alteração: reconciliação compatível com tabelas futuras; bloqueio editorial apenas no workflow mutável; Docker local fixo inclusive com timeout; ensaio de migrations/API com papéis segregados e recibo JSON único. Arquivos, bugs e rollback estão em [P1-SCOPED-RESTORE.md](P1-SCOPED-RESTORE.md). **Nenhuma migration nova**. Commits `8f351f7` e `c12e53a`; imagens exatas e fonte vinculadas ao segundo commit nesse guia.

A final: **599 API +217 operações +13 contratos Git PASS** em Linux; browser opt-in foi executado separadamente, **39,12 s PASS**, com código de aplicação inalterado na correção final do recibo. B: **18 contratos +36 workflow PASS**, skips ambientais explícitos, cinco probes adicionais PASS. Restore integral de backup novo **PASS**: 14 migrations como migrator, 64 tabelas/86 registros originais preservados, repetição idempotente, API editorial/notas como runtime sem superuser, ownership/replay/conflito PASS. PostgreSQL, MariaDB, MinIO, arquivos e cleanup aprovados. No-touch suplementar v2 PASS sem exceções de rede, firewall, listeners ou configuração.

Evidência: backup `kairos-predeploy-20260911T043307Z-8ce27bbc4683.tar.gz.enc`; restore `kairos-restore-20260911T043321Z-df1fcf2d739c.evidence`; recibos locais `p0p2-candidate-20260911T042557Z.json`, `p3-scoped-migration-rehearsal-final-20260911.json` e `strict-scoped-evidence.json`. **Não implantado.** O ensaio de grants está concluído; permanecem ativação, manutenção/drenagem, rollback integral e smoke público.

Imagem Next.js correspondente: **`sha256:651bf1767d3a6d90924e212bf7579dadd8196e53a2e7c20c42f6a02d7cef6824`**, commit **c12e53a**. Build e smoke Linux isolado PASS: health/login/CSS200, área privada307 para login sem API, uid10001/read-only/rede none; cleanup/no-touch v2 sem exceções PASS. Recibo `product-web-build-c12e53a.json`; detalhes de fonte, base e revisão B no guia de restore. O conjunto API/parser/web é atribuível ao mesmo commit, mas a produção conserva a release histórica até o cutover ensaiado.

Preparação inativa da release **PASS** em 2026-09-11 04:59:44 UTC: checkout Git c12e53a limpo, 14 imagens pinadas, 12 arquivos de ambiente segregados, descriptor protegido e Compose config PASS. No-touch v2 PASS sem exceções; credenciais e containers produtivos continuam anteriores. Nenhuma migration. Script exato, hashes, A/B, limites de mounts, rollback e evidência em [P1-PREPARED-RELEASE.md](P1-PREPARED-RELEASE.md).

Mounts e ACL **PASS em 05:24:51 UTC**: Redis real com credenciais preparadas (isolamento cache/broker e negações administrativas), Caddy UID1000 e plugin WordPress UID33. Três containers isolados removidos; no-touch v2 PASS. Plano SQL preparado, não aplicado. A final 29 PASS/5 skips; B 52 PASS/5 skips e 46 probes PASS; ensaio Linux real integral PASS. Corrigidos quatro problemas do executor (JSON Docker, separadores Redis, cache Python e diferença de capability Caddy), com recibos FAIL preservados e novas verificações após cada correção. Executor `2df7c91`; aplicação/imagens c12e53a. Recibo `product-mount-verification-v4.json`; detalhes no guia acima. Ainda faltam manutenção/drenagem, rollback integral e ativação com smoke público.

Observação do worker legado e ensaio isolado de manutenção: **PASS**, sem implantação. Em 05:47:38 UTC não havia tarefas ativas/reservadas/agendadas ou mensagens pendentes, sem alegar drenagem com tráfego aberto. Em 05:50:14 UTC, Caddy real passou em 36 contratos HTTP antes e depois do restart do componente temporário; cleanup/no-touch v2 PASS. A63 testes/Ruff PASS; B63 testes e15 probes do ensaio PASS; probe de filas B46 testes e38 probes PASS. Commits `9516c31` e `e5a9c30`; nenhuma migration. Evidências, bugs corrigidos, limitações e rollback em [P1-MAINTENANCE-DRAIN.md](P1-MAINTENANCE-DRAIN.md). Transição integral e disponibilidade pública ainda pendentes.

`PRODUCT_CORE_READY=NO`
