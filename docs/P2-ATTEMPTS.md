# P2 — tentativas, versões e pontuação persistida

## Alteração e motivo

Uma tentativa passou a ter uma definição congelada: modo, duração, prova, título, questões, enunciados, versões, alternativas, gabarito definitivo aprovado e anulações na captura. A captura tem origem, timestamp e SHA-256 canônico. Mudanças posteriores em ponteiros de versões ou textos de alternativas não alteram a experiência nem a pontuação histórica daquela tentativa.

`create_attempt` bloqueia o dono e o simulado numa transação; `Idempotency-Key` é única por dono. Repetição da mesma criação retorna a tentativa já existente; reutilização da chave em outro simulado retorna conflito. Sem chave, a criação inicia outra tentativa, comportamento anterior preservado. A API somente inicia questões publicadas com aprovação e sem status legacy_unverified. Um simulado vazio continua aceito no contrato fundacional anterior, mas seu resultado fica marcado requires_review e não representa prova validada.

Depois da primeira tentativa, modo, prova, questões e duração do simulado são imutáveis pela API; o título pode ser corrigido. A validação e gravação usam lock do simulado, compartilhado com a criação da tentativa. Questões devem ser UUIDs distintos, existentes, da mesma prova, até 200 itens; duração entre 1 e 1440 minutos.

## Autosave e submissão

Payload de autosave é validado por serializer tipado, com limites de itens/texto/tempo e sem questões duplicadas. A tentativa exige dono, estado ativo e expected_version atual. Alternativas são verificadas contra a captura, não a versão atual da questão. Um erro desfaz o checkpoint inteiro. Checkpoint registra todas as respostas atuais, inclusive as que não vieram no último payload. Tempo é monotônico e não ultrapassa a duração; no modo formal, o prazo também é calculado pelo relógio do servidor desde started_at. Após o prazo ainda é possível submeter as respostas já salvas.

Submissão usa lock, calcula o resultado deterministicamente e grava result_snapshot junto com estado/timestamp/versão numa transação. Repetir submit em tentativa submitted/graded retorna o mesmo estado sem alterar pontuação ou versão. Resultado é lido diretamente do snapshot persistido, sem consultas por questão ou recomputação de gabarito. Questão sem gabarito aprovado na captura permanece unscored; nenhum valor é inventado para torná-la corrigida. O snapshot bruto nunca aparece na serialização da tentativa: questions inclui enunciado e alternativas, mas não gabarito/rationale. Resultado continua bloqueado enquanto ativa.

PATCH/PUT/DELETE genéricos retornam 405. O serializer também recusa updates: uma instância antiga não pode reabrir a tentativa finalizada por outra requisição nem apagar seu resultado. Use os comandos próprios. Gabaritos aprovados ainda não publicados não entram na captura; anulações futuras não afetam a nota atual.

## Migration e dados antigos

`core/0002_attempt_foundation.py` depende de 0001, acrescenta quatro campos (frozen_definition, snapshot_origin, result_snapshot, idempotency_key), índice owner/status/started_at e constraints de modo/duração/estado/versões/checkpoint/idempotência. Todos os registros preexistentes recebem snapshot_origin=legacy_unverified sem reconstrução usando fontes atuais. Tentativa antiga ativa sem captura exige iniciar uma nova; os dados e respostas permanecem consultáveis. Histórico fechado sem snapshot retorna historical_result_unavailable/requires_review, sem simular a antiga pontuação.

Criação ORM fora do serviço recebe pending; primeira ação pode capturar como deferred e exige revisão do resultado. Isso mantém compatibilidade de fixtures/importações controladas sem alegar captura no início. Endpoints normais sempre usam create_attempt e origem creation.

Constraints inválidas em dados anteriores fazem a migration falhar atomicamente; não há correção silenciosa de registros. Verificar dados antes e testar forward/back em PostgreSQL isolado. Rollback de schema removeria snapshots novos: só reverter migration após guardar backup consistente ou exportação protegida dos dados criados nesta revisão. Preferir rollback de código compatível com schema aditivo e preservar histórico.

## Arquivos e integração

Somente classes Simulation/Attempt/AttemptAnswer/AttemptCheckpoint em models.py, SimulationSerializer/AttemptSerializer em serializers.py, services/attempts.py, migration 0002, tests/test_attempt_consistency.py e esta documentação.

O integrador mantém perform_create com serializer.save(owner=request.user): o serializer já chama create_attempt. A view autosave passa valores brutos do request ao serviço, sem int()/list() prévio. Nenhum redesenho visual. Novos campos de resposta são aditivos.

## Testes e resultado

Testes focados cobrem estabilidade após troca de versão e gabarito, alternativas congeladas, idempotência de criação/submit, isolamento A/B, gabarito não exposto, edição estrutural recusada, atualização com instância antiga, rollback de payload parcialmente válido, duplicatas, input inválido, relógio do servidor, legado, constraints e rejeição de questões sem aprovação. Rodada local após correções: 38 testes passaram, incluindo ensaio das migrations para frente e para trás com dados sintéticos. PostgreSQL e imagem final continuam gates de implantação; SQLite não comprova concorrência real.
