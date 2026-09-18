# Metas de estudo ligadas à conta

Módulo candidato, sem deploy. PostgreSQL continua como fonte canônica; metas antigas conservam título, descrição, prazo, porcentagem manual, conclusão e timestamps. A tela de metas preserva a linguagem visual Kairós e permite criar, editar, consultar, arquivar e reativar objetivos por formulário, com disciplina pelo nome.

## Regras de medição

| Tipo | Fonte e contagem |
| --- | --- |
| Questões | Respostas não vazias de tentativas concluídas, por titular, data de envio e classificação atual da disciplina. Cada resposta conta; repetir uma questão em outra tentativa é nova atividade. |
| Minutos registrados | Soma de `StudyActivity.duration_seconds` dividida por60, pelo titular/data do evento. Tempo informado na conta não comprova tempo efetivamente estudado. |
| Simulados | Tentativas objetivas concluídas, excluindo treino avulso `practice:*`, mais submissões formais enviadas da2ªfase. Treinos escritos ficam fora. |
| Revisões | Recibos de revisão de flashcards do próprio titular, pela data de avaliação. Não implica certificação de domínio jurídico. |
| Manual | Porcentagem informada pelo aluno, com timestamp de conclusão do servidor quando chega a100%. Reabrir remove essa conclusão; editar metadados não altera o instante anterior. |

Metas quantitativas têm quantidade1–100.000, início e prazo inclusivos no fuso configurado no Django, período de até366dias, prioridade alta/normal/baixa e disciplina opcional somente para questões. Eventos posteriores ao instante da consulta ficam fora. O tipo da meta não pode ser trocado depois da criação. Editar quantidade/período recalcula a medição; arquivar preserva a meta e todos os fatos de estudo.

`progress`, `achieved`, `measured_value` e `measured_at` são calculados a partir dos fatos canônicos. GET não persiste uma porcentagem derivada nem cria um falso instante de conclusão. Para metas quantitativas, `completed_at` permanece nulo e a interface identifica o instante de consulta. O middleware preexistente pode renovar a sessão durante GET. Metas atingidas e arquivadas deixam de ocupar o próximo passo do dashboard; retomada de prova mantém precedência e o bloqueio de resultados durante prova formal permanece.

## Consistência e recuperação

Criação aceita UUID por titular e hash do pedido; replay idêntico retorna a meta atual. PATCH exige a versão observada; conflito retorna409 sem sobrepor alterações. Locks seguem usuário→meta, com revalidação de sessão/permissão e conta esperada. Não existe DELETE. O navegador mantém somente rascunho temporário limitado e separado por conta em `sessionStorage`; a identidade e a estrutura do cache são validadas antes de uso.

Após falha de conexão ou refresh, conferir salvamento consulta a meta por identificador ou recibo de criação. Não duplica uma criação confirmada. Valores são normalizados como no pedido (inclusive `01`→1) antes da comparação. Conflito apresenta título, descrição, tipo, quantidade, início, prazo, disciplina, prioridade, progresso e estado da versão salva; manter o plano abre edição para um salvamento explícito. Listas têm filtros, paginação, erros visíveis e proteção contra resposta assíncrona antiga.

## Arquivos, migration e rollback

- `core/models.py`, `personal_goals.py`, `serializers.py`, `views.py`, `learning_views.py`.
- `0017_quantitative_goals`: campos aditivos, FK protegida de disciplina, constraints de tipo/faixa/formato e unicidade da chave por titular. Legado recebe tipo manual e versão1, sem recalcular fatos anteriores.
- `GoalsWorkspace.tsx`, `goals.css`, integração em `ModuleWorkspace.tsx`.
- Testes `test_quantitative_goals.py`, `test_goal_completion.py`, `test_goal_concurrency.py`, `test_foundation_migrations.py`, `test_query_growth.py`, `test_learning.py` e `tests/browser/goals.cjs`.

Antes do deploy: backup recente com restore isolado, migration com papel próprio, grants reconciliados, imagem/API/web/descriptor coerentes e smoke. A reversão de0017 remove metadados novos: só demonstrada em dados sintéticos, não executar depois de novas escritas sem preservação e reconciliação. Rollback operacional deve manter o schema aditivo e usar código compatível que preserve as metas quantitativas; o frontend antigo não entende esse contrato. Nenhuma dessas etapas de produção foi executada para este módulo.

## Evidências

A focada inicial:41PASS/2corridas PostgreSQL pendentes do ambiente Linux. B backend independente:83PASS/3skipsPG, Ruff e migrations sem drift; probes próprios de fronteira diária no fuso São Paulo, outro titular, replay após edição, sessão revogada e listagem1/10metas com11/11queries. Ciclo de migration preserva a meta manual histórica.

E2E Chromium inicial56,20sPASS com os quatro fluxos de produto anteriores, medição de revisão já confirmada, perda POST/PATCH, refresh, rascunho não enviado, conflito entre abas, comparação, arquivo/reativação e390/768/1440sem overflow. Revisão B encontrou paginação antiga após erro, comparação numérica de rascunho, cache incompleto e campos ausentes na comparação. Corrigidos; essa execução inicial não substitui a repetição A/B final. Evidências ficam em `modernizacao/evidencias/p3-editorial-browser/` (inclui `goals-mobile.png`).

Agenda semanal detalhada, planejamento de carga por disciplina e recomendações avançadas permanecem evoluções; a medição e o próximo passo básico funcionam sem IA. `PRODUCT_CORE_READY=NO`.

Verificação final local: **611API PASS/34skips explícitos**,155,87s; Ruff/migrations sem drift, build Next.js/TypeScript/ESLint PASS. B UI repetida: **21probes e27API PASS**, Chromium11labels/foco/escape e390/768/1440sem overflow. E2E funcional repetido55,76sPASS; o teste de teclado agora aguarda a conclusão da conferência assíncrona antes de focar o botão. A primeira repetição falhou por tentar focar o botão enquanto ainda estava desabilitado; não houve falha da API. E2E final completo54,95sPASS com captura no topo, sem foco de navegação sobreposto.

## Retomada em18/09/2026

Commit do módulo: `9a457cc171d9f0d27d37bd5477bbc1557b27a028`. A execução Linux iniciada em11/09 terminou com **644API PASS/1skip**, inclusive as corridas PostgreSQL de metas, mas **2falhas/266PASS/18skips operacionais**. Portanto a imagem não foi aprovada. Ambas as falhas eram `NotNullViolation` de `core_goal.creation_payload_hash`: os INSERTs SQL dos testes de DML e de constraint após restore ainda usavam o schema antigo. Migration e API não apresentaram falha nesse ensaio.

Correção: fixtures SQL agora informam tipo manual, prioridade, versão e hash vazio; o teste após restore exige especificamente `goal_progress_lte_100`, evitando aceitar outro erro como evidência. O probe isolado com `kairos_runtime` também passa a verificar metas pela API real (medição, replay, titularidade e conflito) e reverte todas as linhas sintéticas ao terminar. Nenhuma concessão de privilégio ou constraint foi relaxada. Verificação Linux completa deve ser repetida para aprovar o novo commit.

Baseline18/09/2026 03:15:50UTC: checkout/API/Compose históricos preservados, containers saudáveis/sem restart, worker sem healthcheck,19migrations/3usuários. Backup automático17/09 06:34:22UTC,69.301.296bytes/root0600/checksumPASS; restore deste arquivo ainda não testado. Pointer canônico ausente. Recibo `p3-resume-baseline-20260918.json`; diagnóstico sem secrets em `goals-integration-failure-cause-20260918.json`. Sem deploy.

### Imagens e verificação Linux final

Candidato **10089ff4dae296caf35526bb2c8b51d458cff748**, archiveSHA256`2439ee31d6f146ce804b5fa207c464df01899dd17e630fe37212796de2009c20`:

- API: `sha256:079925865fdc4bb6c1b938314630f165965b791c6e69f8d1e1080a70cebc8d94`.
- Parser: `sha256:330a4e95f54631812a38e9ad15ed1f8e41449081db9a4a380588ffe9af95d1a0`.
- Web: `sha256:4122cac86122271b298bad86d57f5e1598b8867838ab041d8a8db888db524c53`.

**644API PASS/1skip(browser opt-in)** em226,29s; **268operações PASS/18skips** em42,45s e **13contratos Git PASS** separados. Os18skips correspondem a15contratosNodeausentenoPythoncontainer e3Git exercitados separadamente. PostgreSQL real validou races, migração, privilégios, backup/restore sintético e API de metas sob `kairos_runtime` sem superusuário. B da correção:27testesmetas/17operacionais/10probes, com limitações locais explícitas, sem achado pendente.

Next.js do mesmo commit passou em build/smoke Linux: health/login/CSS200, página privada307 para login quando API indisponível, sem X-Powered-By; processo UID10001, read-only, rede none. Cleanup e comparador estrito v2 sem exceções passaram, assim como a comparação estrita adicional da imagem API. Evidências `p0p2-candidate-20260918T031838Z.json`, `strict-goals-evidence-20260918.json`, `goals-web-image-20260918.json`.

Wrappers de homologação versionados em `scripts/releases/verify-product-{image,web,recovery}-10089ff.sh`. B encontrou import/exec de helpers sem vínculo integral ao archive e uso de comparador antigo no restore: agora extraem os helpers de uma cópia nova do archive verificado e usam v2 sem exceções. A12probes e B30probes de hash, path, tipos, modos e colisões passaram (metadadosLinux simuladoslocalmente); execução real de web comprova o primeiro wrapper. Restore integral de backup produtivo desta revisão permanece pendente do ensaio seguinte. Essas imagens não foram implantadas.
