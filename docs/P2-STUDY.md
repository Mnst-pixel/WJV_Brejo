# Persistência canônica e recuperação do browser — P2

## Estado encontrado e alteração

O inventário `legacy/extracted/functional-concepts.json` registra 15 chaves `gaivota_*`; o frontend atual não contém chamadas `localStorage`/`sessionStorage`. Isso não prova migração: algumas funções do protótipo não estavam conectadas a modelos persistentes. Nenhum perfil de navegador ou dado pessoal foi lido para esta implementação.

Foram adicionados `StudyProgress`, `StudyMark`, `StudyActivity`, `StudyPanelState` e `BrowserImportReceipt`, em `core/study_models.py`. Notas, metas, flashcards, favoritos, sessões, preferências, arquivos e tentativas continuam nos modelos já existentes. Os endpoints novos ficam em `core/study_views.py`, com comandos em `core/services/study_state.py`; exigem sessão autenticada, `study.use`, CSRF nas escritas e `Cache-Control:no-store`.

Progresso e marcações apontam para tópico/conteúdo/questão/versão jurídica disponível para estudo. Registros são únicos por usuário e alvo/localizador; progresso limitado a 0–100, versões positivas e enums têm constraints. O backend rejeita campos desconhecidos, inclusive `owner`. Listas e consultas por ID sempre filtram pelo usuário da sessão.

Criação usa `expected_version:0`; atualizações usam a versão recebida do servidor. Duas gravações conflitantes produzem 409 e não sobrescrevem silenciosamente a mais recente. Um lock no usuário serializa criação e escrita mesmo quando ainda não existe uma linha de progresso. Há limite de 5.000 registros de progresso e 5.000 marcações por usuário.

Atividades são eventos imutáveis com `event_key` por usuário e hash do payload. Repetição idêntica retorna o mesmo evento; reutilização com dados diferentes retorna 409. Duração máxima de 24 horas/evento, até 50.000 eventos por conta; timestamps mais de cinco minutos no futuro são recusados. Estatísticas derivam do banco e são autodeclaradas pelo aluno, sem substituir resultado formal de prova.

Último painel e estado Pomodoro são persistidos por usuário. O timer usa instante de atualização do servidor para calcular tempo restante ao reabrir outro dispositivo. Vínculo opcional a `StudySession` exige o mesmo owner; o frontend futuro pode usar essa base sem depender exclusivamente do browser.

## HTTP e integração

Rotas integradas pelo coordenador sob `/api/study/`:

| Endpoint | Métodos | Contrato |
|---|---|---|
| `progress/` | GET/PUT | alvo, percent, position, expected_version |
| `progress/<uuid>/` | GET | owner obrigatório |
| `marks/` | GET/PUT | alvo, locator, kind, annotation, expected_version |
| `activities/` | GET/POST | event_key, kind, occurred_at, duration_seconds |
| `panel/` | GET/PUT | last_panel, pomodoro_status, remaining_seconds, study_session, expected_version |
| `summary/` | GET | contagens e tempo do próprio usuário |
| `browser-imports/` | GET/POST | recibos e preview/confirmação |
| `browser-imports/<uuid>/` | GET | recibo e origem, somente owner |

Listas retornam 50 registros com `next_offset`. Corpos são lidos com limite de 300.000 bytes antes do parsing; payload de origem de importação é limitado a 256 KiB. Não há update/delete genérico de eventos ou recibos.

## Recuperação do legado sem sobrescrita

POST de importação recebe `{source_key,data,confirm:false}` para preview sem escrita. Com `confirm:true`, guarda recibo, hash SHA-256 do JSON canônico, chave original, provenance `authenticated_browser_export`, timestamp e resultado. Cada combinação owner/chave/hash é única. Reenvio retorna o recibo original; o mesmo payload de outro usuário é isolado. Até 200 lotes por conta.

Somente formatos pessoais normalizados e explicitamente reconhecidos são aplicados:

- `gaivota_notes`: lista de `{title,body}` → `StudyNote`.
- `gaivota_metas`: lista de `{title,description?}` → `Goal`.
- `gaivota_flashcards`: lista de `{front,back}` → `Flashcard`.

Até 200 itens/lote. Itens iguais já existentes são reutilizados; os demais são criados com owner da sessão. Nunca há UPDATE de conteúdo pessoal existente, concessão de papel ou publicação jurídica. Formato misto/desconhecido é preservado inteiro como `staged_unverified`, exigindo mapeamento/revisão; não se inventa o formato de um browser não examinado.

| Chave original | Destino canônico / tratamento da importação |
|---|---|
| `gaivota_activities` | `StudyActivity`; formato bruto fica staged |
| `gaivota_flashcards` | `Flashcard` para formato normalizado; demais staged |
| `gaivota_hp_stats` | métricas derivadas do banco; estatística legada staged |
| `gaivota_last_panel` | `StudyPanelState`; bruto staged para revisão |
| `gaivota_legis` | recibo staged; nunca vira corpus publicado automaticamente |
| `gaivota_marcacoes` | `StudyMark`/`Bookmark`; bruto staged |
| `gaivota_marcacoes_meta` | `StudyMark`; bruto staged |
| `gaivota_metas` | `Goal` para formato normalizado; demais staged |
| `gaivota_notes` | `StudyNote` para formato normalizado; demais staged |
| `gaivota_pomo_log` | `StudySession`/`StudyActivity`; bruto staged |
| `gaivota_pomo_time_by_subj` | agregado server-side; bruto staged |
| `gaivota_pomo_times` | `StudyPanelState`/`User.preferences`; bruto staged |
| `gaivota_pomo_today` | agregado server-side; bruto staged |
| `gaivota_soft_theme` | `User.preferences`; bruto staged |
| `gaivota_uploads` | `FileAsset` exige novo upload/quarentena; recibo nunca acessa URL/path legado |

Esses mapeamentos são fundações de backend. UI de importação e mapeadores adicionais continuam trabalho de produto; nenhum material `legacy_unverified` foi promovido a juridicamente vigente. Texto hostil e referências de arquivo/URL no recibo são dados inertes, sem execução ou download.

## Migration, testes e rollback

Migration `0005_study_foundation` gerada e integrada pelo coordenador após `0004_upload_foundation`; não altera tabelas pessoais já existentes. Reversão destrói apenas tabelas novas: antes de reverter, exportar seus dados com autorização e backup validado. Rollback usual deve ser por imagem compatível, preservando tabelas/dados novos.

Verificação A local: 34 testes passaram e 1 teste concorrente ficou condicionado a PostgreSQL isolado. Cobrem cross-user, confirmação/preview, dedupe/replay, stale version, dados maliciosos e excessivos, todos os 15 nomes legados, persistência após trocar cliente, timer server-side, constraints e inexistência de publicação jurídica. A primeira rodada identificou que erro de campos desconhecidos no serializer podia produzir 500; corrigido para erro estruturado 400. Rotas de detalhe negam escrita com 405. A suíte foi repetida integralmente após as correções.

```text
python -m pytest --ds=kairos.test_settings tests/test_study_state.py -q
python -m pytest --ds=kairos.integration_test_settings tests/test_study_state.py -q
python -m ruff check core/study_models.py core/services/study_state.py core/study_views.py tests/test_study_state.py
```

Suíte real PostgreSQL/Redis, revisão B, integração final de rotas, imagem, deploy e evidências são gates do lote global. Não houve alteração de design/frontend, leitura automática do navegador, commit ou deploy independente deste módulo. A entrega global deve registrar commit/imagem exatos e eventuais pendências de produto.

## Revisão B e correções de regressão

A revisão independente reproduziu gravação de atividade após revogação da sessão entre a autorização inicial e o lock. `_lock` agora revalida usuário existente/ativo, versão da sessão e `study.use` usando a linha atual travada; falha resulta em 403 e nenhuma gravação. Também foi reproduzido `offset=²` causando `ValueError`/500: paginação aceita somente dígitos decimais ASCII e retorna 400 para entradas inválidas.

Após as correções, `pytest tests/test_study_state.py -q` passou com **44 passed, 1 skipped** (corrida real depende do PostgreSQL isolado). Dez casos novos cobrem revogação de sessão, desativação, remoção de papel, usuário removido e offsets inválidos. Ruff passou. As correções retornam à revisão B do coordenador antes de release; a revisão local não comprova concorrência PostgreSQL nem deploy.

## Consistência de conclusão das metas

`GoalSerializer` registra `completed_at` com horário do servidor ao atingir 100% e limpa esse campo quando o progresso cai abaixo de 100%. Repetir 100% ou editar apenas o título preserva a data registrada. O campo não pode ser definido manualmente na API. Criação e atualização revalidam a conta sob lock; atualização trava e relê a meta do próprio usuário para que um objeto obsoleto não desfaça progresso ou conclusão recentes. Dados históricos não recebem backfill silencioso.

`test_goal_completion.py` cobre criação já concluída, conclusão/reabertura, repetição sem trocar timestamp, negação de timestamp manual, edição de metadados com instância obsoleta e negação de escrita de outro usuário. A mudança não exige migration.
