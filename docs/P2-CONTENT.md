# P2 — workflow editorial, publicação e importação do legado

## Alteração e motivo

A versão jurídica permanece imutável. `ContentWorkflow` armazena responsabilidade e datas do fluxo `draft → review → approved → published → archived`. Editor pode criar e submeter; revisor jurídico aprova; responsável com `publication.publish` publica. A autorização usa a matriz por recurso/ação e MFA da sessão. Conta de serviço não executa comando editorial humano. O serviço trava o usuário e o conteúdo, verifica revogação de acesso e executa a transição em uma transação.

A aprovação gera **uma nova ContentVersion**, com `approved_by`, `approval_date`, situação jurídica explicitamente declarada e `supersedes` apontando para a versão revisada. A versão anterior permanece arquivada e inalterada; a API retorna o novo ID que deve ser usado na publicação. Autor e responsável pela submissão não podem aprovar, mesmo quando também forem administradores. `PublicationApproval` vincula o revisor, a justificativa e o SHA-256 do texto, dos metadados e da fonte à versão exata. Publicação revalida essa evidência.

`ContentVersion.published_at` representa a data informada da publicação na fonte. `ContentWorkflow.published_at` representa a liberação efetiva no Kairós. Não é necessário reescrever a versão jurídica para publicar ou arquivar. Uma nova revisão mantém a versão já publicada operacional até que a substituta seja aprovada e publicada.

O admin genérico mantém status, ponteiro de versão e decisões somente leitura. Os novos modelos de workflow não são registrados como formulários CRUD. Os comandos explícitos são a interface backend para o próximo painel; esta fase não altera o design visual.

## API

| Operação | Endpoint | Permissão |
|---|---|---|
| Listar/criar conteúdo | `GET/POST /api/admin/content/` | `content.read` / `content.create` |
| Histórico/criar revisão | `GET/POST /api/admin/content/{content_id}/versions/` | `content.read` / `content.edit` |
| Transição explícita | `POST /api/admin/content-versions/{version_id}/transition/` | Conforme estado |
| Prévia de legado | `POST /api/admin/legacy-content/preview/` | `content.create` |
| Consultar/confirmar lote | `GET/POST /api/admin/legacy-content/{batch_id}/confirm/` | `content.create` e ownership |

Criação recebe disciplina, slug, tipo e uma revisão com título, corpo, fonte HTTPS/URL, hash e datas opcionais. A situação jurídica não é atribuível pelo formulário de revisão. Transição recebe estado, justificativa e, somente na aprovação, a situação jurídica verificada. Payloads com campos desconhecidos são rejeitados. Listas administrativas ficam limitadas a 100 registros nesta fundação; paginação e editor visual pertencem ao painel futuro.

## Legado

Somente os datasets versionados `questions` (`questions.json`, 101 itens) e `oab` (`oab-data.json`, 95 itens) podem ser selecionados. A request não aceita caminho, URL, script ou conteúdo executável. O diretório vem da configuração controlada `KAIROS_LEGACY_DATA_DIR`; em desenvolvimento, usa `legacy/extracted` do checkout. O deploy deve disponibilizar esse acervo de modo somente leitura. Ausência do acervo retorna 503 e não impede outras funcionalidades.

Preview valida o arquivo, registra hash, disciplina, responsável e quantidade, mas não cria conteúdo. Confirmação exige hash exato e o mesmo usuário. Mudança do arquivo invalida a confirmação. Lote confirmado é idempotente. Itens são deduplicados por seu hash canônico, inclusive quando apenas a formatação do arquivo muda; recibo guarda hash do arquivo original, hash do item, localizador, responsável e data.

Cada item vira `Content` do tipo `legacy_question` ou `legacy_summary`, com dados estruturados, `legacy_unverified` e uma tarefa em revisão. Nenhum `Exam`, `Question` ou simulado é inventado a partir da extração. Dados estruturados mantêm alternativas, gabarito legado e explicação como material **não verificado**. A referência `legacy://` não pode ser aprovada: um editor precisa criar uma revisão com fonte HTTPS verificável; um revisor distinto avalia e declara a situação. O pipeline nunca publica automaticamente e não declara atualização jurídica pelo simples fato de importar.

O formato e tamanho do dataset têm limites: 2 MiB, 500 itens, oito alternativas e 100 mil caracteres por corpo. Não há parsing de HTML executável nem execução do conteúdo recuperado. O próximo painel deve renderizar texto de modo escapado/editor sanitizado.

## Leitura e consistência

`published_content()` é o gate compartilhado da API do aluno e dos comandos de progresso/marcação. Status isolado não basta: precisa de versão aprovada, workflow publicado, responsável, timestamps, aprovação vinculada e situação diferente de `legacy_unverified`. Questões exigem versão aprovada, data de aprovação e publicação; versões documentais usadas em progresso também exigem aprovação e publicação.

No corpus jurídico, `transition_document_version` usa `corpus.approve`, `corpus.review`, `publication.publish` e `corpus.update`. Indexação e publicação revalidam hash da versão exata aprovada. O dono do upload não aprova seu próprio documento. Falha de atualização não pode transformar uma versão publicada em `failed`, preservando a base anterior operacional.

## Arquivos e migration

- `core/content_models.py`, `content_workflow.py`, `content_views.py`.
- `core/models.py`: estado `Content.Status.APPROVED` e integração dos novos modelos.
- `core/views.py`: filtros de leitura de conteúdo e questões.
- `core/services/documents.py`: autorização e integridade da aprovação jurídica.
- `core/services/study_state.py`: somente alinhamento de `_target` ao gate publicado.
- `core/migrations/0006_content_workflow.py`: tabelas de workflow/recibos e constraints; depende de `0005_study_foundation`.
- `tests/test_content_workflow.py`.

A migration não promove nem publica registros existentes. Registros sem evidência suficiente continuam fora da leitura pública; um novo ciclo editorial cria versões verificadas. Rollback de aplicação deve manter as tabelas e versões para preservar histórico. Reverter a migration após uso elimina recibos/workflows e exige backup consistente e decisão operacional; não é rollback rotineiro.

## Evidência A local

Com `PYTHONUTF8=1` e configuração isolada de testes: `pytest tests/test_content_workflow.py tests/test_legal_versions.py tests/test_rbac_foundation.py tests/test_study_state.py -q` resultou **82 passed, 1 skipped** (concorrência PostgreSQL, delegada à homologação isolada). Ruff dos arquivos alterados passou; `makemigrations --check --dry-run --settings=kairos.test_settings` não encontrou mudanças.

Cobertura: criação por API, MFA, permissões negativas aluno/suporte/serviço, autoaprovação negada, adulteração da versão/aprovação, sucessão imutável, preservação da versão operacional, arquivamento, status falso sem publicação/progresso, preview/confirm ownership, hash obsoleto, 101 questões importadas sem publicação, repetição e reformatação sem duplicatas, path arbitrário negado, corpus alterado depois da aprovação rejeitado, falha de crawler preservando publicação.

Commit, imagem, deploy, revisão B e resultado PostgreSQL devem ser preenchidos na entrega central P0–P2 após execução pelo responsável de release. Não há evidência de deploy produzida por este sublote local.

## Revisão adversarial adicional e consolidação dos gates

Um objeto `Content` carregado como rascunho no admin podia ficar obsoleto enquanto outro request publicava sua nova versão. O guard anterior verificava o objeto antigo e o `save()` completo podia restaurar status e ponteiro ultrapassados. `PolicyAdmin.save_model` agora trava e relê o Content, rejeita alteração de metadados quando o estado atual exige workflow e salva somente campos efetivamente editados quando ainda permitido. Dois testes cobrem publicação concorrente à edição antiga e preservação de ponteiro de novo rascunho.

O gate `published_content()` verifica também ContentType da aprovação e datas de aprovação/liberação não futuras. `published_document_versions()` é compartilhado por recuperação RAG/indexação e alvos de estudo: exige recibo `PublicationApproval` correspondente ao documento, revisor, hash da fonte e decisão, além dos estados e timestamps. Uma coleção de flags isoladas não substitui essa decisão humana. A integridade completa do texto/estrutura continua verificada no comando de publicação pelo hash da versão aprovada.

A autorização editorial relê o usuário travado e usa sua autoridade atual; usuário removido resulta em negação controlada. ID documental inexistente retorna 404. Nenhuma nova migration foi necessária para essas correções.

Rodada final local: **70 passed, 3 skipped** para `test_goal_completion`, `test_content_workflow`, `test_retrieval`, `test_legal_versions` e `test_rbac_foundation`. Os três testes condicionais exercitam criação concorrente de revisões, dupla publicação e importação simultânea por editores distintos; dependem de PostgreSQL isolado e não são declarados executados localmente. Ruff e verificação de migrations passaram. Revisão deste trecho pelo próprio implementador é uma revisão adversarial adicional, não substitui uma revisão B independente.
