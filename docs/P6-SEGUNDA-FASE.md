# Segunda fase — casos, espelhos e provas escritas

Incremento candidato. A publicação depende dos gates de release; esta documentação não declara implantação. Correção avançada por IA permanece fase posterior.

## Operação editorial

Em **Administração → Segunda fase**, crie a área e o caderno. **Criar caso e espelho** apresenta formulários para título, peça cabível, enunciado, fonte, duração, vigência, fatos, distratores, competência, endereçamento, legitimidade, prazo, preliminares, teses e pedidos. Campos reservados não são enviados à aplicação do aluno.

**Adicionar discursiva** cria enunciado e padrão de resposta. **Adicionar critério** cria referência curta, grupo, resposta avaliada, descrição, pontuação, fundamento, equivalências, dependências, obrigatoriedade e erro impeditivo. Dependências só podem indicar critérios anteriores da mesma resposta; ciclos são rejeitados. As setas, posição numérica ou arraste ordenam itens. Remover marca o item para exclusão do novo rascunho, sem apagar versões anteriores. Se renomear uma referência usada em dependência, o vínculo antigo permanece visível e deve ser corrigido explicitamente; não é removido silenciosamente.

A soma exibida no navegador é prévia. A aprovação calcula a soma com Decimal no servidor e exige critérios para a peça e cada discursiva, além de igualdade com a pontuação total. Nenhum modelo de IA calcula essa soma.

Salvar cria versão imutável em rascunho. O fluxo é rascunho → revisão → aprovado → publicado → arquivado. Autor e pessoa que encaminhou não podem aprovar o próprio pacote. A aprovação cria versão sucessora, preserva origem e registra responsável, data, comentário e hash do caso/espelho completo. O revisor visualiza todo o contexto reservado, critérios, dependências e datas sem receber permissão para editar. Publicação e arquivamento exigem permissão de publicação. O Django Admin genérico não pode alterar `PracticalCase`, evitando sobrescrever o ponteiro publicado por formulário antigo.

**Duplicar para nova revisão** preserva a publicação anterior enquanto a nova versão é revisada. Histórico permite abrir qualquer versão e usá-la como base de um novo rascunho. Legado continua com provenance `legacy_unverified`; uma declaração de vigência só ocorre por revisão humana, nunca por importação automática.

## Operação do aluno

Em **Segunda fase**, escolha um caso e treino de escrita ou simulado formal. O catálogo só mostra pacotes publicados e aprovados; o backend confere o hash antes de expor enunciados e congelar a prova. Peça cabível, padrões de resposta e critérios ficam reservados.

O editor oferece navegação entre peça/discursivas, contador, autosave, tela cheia, recuperação e confirmação final. O texto é preservado literalmente, incluindo espaços e quebras de linha. Limites atuais: 100 mil caracteres por resposta, 500 mil bytes no conjunto, até dez discursivas e cem critérios. Treino não tem prazo final; o formal usa início/duração conferidos no servidor, bloqueia assistência IA/MCP e impede iniciar outro formal/consultar gabaritos de outras tentativas. As duas fases compartilham o bloqueio por conta.

A cópia temporária de envio fica em sessionStorage, validada contra a prova obtida por ownership. PostgreSQL é canônico. Uma falha de conexão preserva texto e pausa retentativas automáticas; **Salvar agora** permite confirmar novamente. Conflito de versão mostra o texto do servidor para comparação e exige escolha. Refresh recupera somente o que chegou ao servidor ou permaneceu na mesma aba; a interface informa quando o navegador impede a cópia temporária.

**Enviar prova → Confirmar envio final** congela todas as respostas, inclusive vazias, e registra hash final e timestamp. O envio repetido é idempotente. Leituras posteriores conferem definição, conjunto exato de campos e hash final. Texto ausente, campo extra ou adulteração bloqueia acesso e exige recuperação operacional; não produz uma nota ou envio silenciosamente incompleto. Histórico permite retomar provas ativas ou ler as já enviadas. Nenhuma nota de IA é fabricada: a tela informa correção pendente.

## Modelo e API

Reutilizados: `PracticalCase`, `PracticalCaseVersion`, `Rubric`, `RubricCriterion`. Novos:

- `SecondPhaseArea`, `SecondPhaseCaseMetadata`, `DiscursiveQuestion`, `RubricCriterionDetails`, `SecondPhaseWorkflow`.
- `WrittenSubmission`, `WrittenResponse`, `WrittenCheckpoint`: ownership, snapshots, versão otimista, confirmação UUID e envio final.
- `WrittenCorrection`, `WrittenCorrectionItem`, `WrittenCorrectionReview`: estrutura versionada para correção e revisão futuras, limites de pontos/confidence e provenance. Ainda sem executor de correção ou interface operacional; não declarar corretor pronto.

Rotas do aluno: `GET /api/phase2/cases/`; `GET/POST /api/phase2/submissions/`; `GET /api/phase2/submissions/{id}/`; `POST .../autosave/`; `POST .../submit/`. Catálogo e histórico têm paginação. O backend deriva identidade da sessão e nunca recebe owner ou permissões do browser.

Os comandos travam usuário antes da submissão. Aprovação ordena os locks dos responsáveis antes do caso, evitando inversão na revisão cruzada. Versões jurídicas, critérios complementares, checkpoints e correções possuem grants candidatos sem UPDATE/DELETE. Reconciliação e prova de privilégios PostgreSQL fazem parte do deploy, não são presumidas a partir do script.

## Migration, validação e rollback

`0011_second_phase_written_exams` cria tabelas, índices e constraints sem converter dados legados nem alterar submissões antigas. Defaults não publicam conteúdo. Aplicar com papel de migrations e reconciliar grants; conferir restore do backup real em destino isolado antes da release.

Testes cobrem autoria/revisão/publicação, soma e dependências, rubrica adulterada, fontes, isolamento, replay, texto longo, checkpoints, deadline, formal entre fases/IA, integridade final e banco rejeitando estado impossível. Testes PostgreSQL adicionais verificam admissão concorrente, autosave concorrente e finalização idempotente. O E2E real cria área/caderno/caso/espelho, revisa/publica com pessoas diferentes, redige, perde intencionalmente confirmação após gravação, recarrega e submete peça e discursiva.

Rollback preferencial: voltar para artefato seguro compatível mantendo as tabelas e registros. Reverse migration removeria provas, critérios e textos; não executar em banco com uso. Se a interface anterior não conhece essas tabelas, os dados devem permanecer preservados para reapresentação, e endpoints afetados devem ficar indisponíveis até a recuperação. Não restaurar backup sobre novos envios sem reconciliação. Produção só muda após backup/restore, imagem exata, no-touch e rollback reproduzível previstos em P1.

Pendências: correção operacional humana/IA, discussão/recurso do aluno, importação de casos legados em lote, links estruturados adicionais de legislação/jurisprudência e métricas de escrita. A criação e preservação da prova não dependem de SMTP ou provedor de IA.
