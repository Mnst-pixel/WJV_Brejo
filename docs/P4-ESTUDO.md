# P4 — leitura e recomendações

Incremento candidato, ainda não implantado. PostgreSQL é a fonte do progresso; o navegador não mantém uma cópia canônica.

## Operação do aluno

Em **Estudar**, buscar um título, abrir a publicação, conferir fonte/data/revisão humana e salvar o percentual lido. **Conferir progresso** recupera o registro da conta. Uma nova publicação começa com percentual efetivo zero e informa a leitura anterior. Ao registrar progresso da nova versão, o último estado da anterior passa ao histórico preservado. Registros antigos sem versão continuam existentes, mas não comprovam leitura da publicação atual.

O dashboard mostra respostas e acertos diários, disciplinas, minutos registrados, sequência dentro do período selecionado, leituras concluídas e provas enviadas. Períodos: 7, 30 e 90 dias. Os números vêm de respostas finalizadas, atividades registradas e submissões da própria conta; não são estimativas de tempo com a página aberta. Respostas antigas sem fato de correção persistido não entram na acurácia.

Próximo passo sem IA: retomar prova em andamento; meta com prazo vencido/hoje; disciplina com pelo menos cinco respostas e acurácia inferior a 70%; publicação ainda não concluída; treino livre. Durante simulado formal, métricas e recomendações de revisão ficam indisponíveis e a retomada prioriza a prova formal. Não há ranking.

## Contratos e segurança

- `GET /api/study/reading/<content_id>/`: publicação revisada, progresso próprio e até 20 registros anteriores.
- `GET /api/contents/?subject=<uuid>&topics=<uuid>&q=<texto>`: catálogo paginado, apenas publicações; relações carregadas em lote.
- `PUT /api/study/progress/`: versão editorial explícita para nova leitura, versão otimista do registro; divergência retorna 409 e exige reconciliação. Lock da conta e do conteúdo serializa gravação/publicação. Ownership não é aceito do cliente.
- `GET /api/study/dashboard/?days=7|30|90`: agregações próprias e recomendação determinística. A transação mantém o lock da conta durante o resumo, serializando a admissão de prova formal.

O hash de aprovação agora cobre identidade, versão, campos jurídicos expostos, datas e responsável. Leitura, recomendação e gravação de progresso verificam o recibo. Aprovações feitas por candidatos anteriores, com hash menos abrangente, **não são reassinadas automaticamente**: se existirem no ambiente a migrar, o operador deve criar revisão sucessora, revisar e publicar novamente. Manter versões e recibos anteriores. Os candidatos editoriais anteriores não foram implantados; verificar os dados reais antes de liberar a release.

## Migrações e rollback

`0012_reading_version_progress` adiciona FK nullable e constraint de tipo ao progresso, sem associar registros históricos por suposição. `0013_reading_history` cria snapshots próprios por versão anterior. A reconciliação SQL inclui a nova tabela na lista sem UPDATE/DELETE para runtime.

Rollback prefere artefato seguro compatível mantendo schema, progresso, snapshots e recibos. Reverse migrations removem dados e não são rollback operacional aceitável após uso. Não restaurar hash antigo para contornar revisão; manter o módulo indisponível ou usar correção compatível. Revalidar grants e ensaiar restore/migrations isolados antes de produção.

## Validação e limites

Testes de leitura nova/antiga, conflito, ownership, hash adulterado, publicação oculta, filtros, métricas próprias, prazos e formal em `tests/test_learning.py`. E2E real ampliado com leitura → progresso → refresh → questões da disciplina e dashboard. Verificações finais A/B, imagem e evidências serão registradas em `P3-P6-ENTREGA.md`.

Este lote não entrega ainda notas dentro da leitura, destaque de trechos, flashcards, biblioteca completa ou metas quantitativas. A relação entre esses recursos será implementada sobre os modelos persistentes existentes. Dados de treinamento local são sintéticos e nunca publicados em produção.
