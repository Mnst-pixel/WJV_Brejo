# Simulados de primeira fase

Incremento candidato, ainda sem implantação em produção. A interface Next.js usa o engine transacional Django e as questões revisadas/publicadas; WordPress não participa das tentativas.

## Operação do aluno

1. Em **Simulados**, escolha prova/caderno, nome, quantidade, duração, disciplinas opcionais, dificuldade e ordem aleatória.
2. Inicie um simulado formal ou treino. O formal bloqueia assistência e outros resultados até ser finalizado. O treino permite tempo livre.
3. Responda e marque questões para revisão. A navegação indica respostas e marcas; aguarde **Todas as respostas confirmadas no servidor**.
4. Se houver falha, use **Salvar agora**. Ao recarregar, a conta recupera a tentativa; respostas ainda não confirmadas possuem cópia temporária na mesma aba. Em conflito, escolha explicitamente a versão do servidor ou a versão local. O prazo encerrado impede reenviar respostas atrasadas.
5. **Finalizar simulado** apresenta confirmação explícita. O envio torna as respostas imutáveis e mostra acertos, desempenho por disciplina e explicações. O histórico permite retomar ou consultar resultados.

A cópia em sessionStorage é recuperação de envio pendente, não fonte canônica. O servidor valida ownership antes de utilizá-la. Não é promessa de recuperação em outro dispositivo de respostas que nunca chegaram ao servidor. Se o navegador bloquear armazenamento, a interface informa a limitação. Preparações incertas preservam o UUID por conta; **Confirmar preparação anterior** recupera o mesmo envio após refresh, sem sortear/criar novamente.

## Contratos

- `GET /api/simulation-catalog/`: cadernos de primeira fase com questões publicadas; limite atual de 500 cadernos.
- `POST /api/simulation-start/`: valida configuração, bloqueia a linha do proprietário, seleciona questões e cria simulado/tentativa atomicamente. O hash da configuração fica congelado. Mesma confirmação/configuração retorna a tentativa; configuração diferente retorna conflito.
- `GET /api/attempts/?purpose=simulation`: histórico paginado da conta, sem tentativas auxiliares do treino rápido.
- `POST /api/attempts/{id}/autosave/`: versão otimista, respostas e marcações; interface envia snapshot completo, incluindo vazios. Checkpoints preservam marcas.
- `POST /api/attempts/{id}/submit/`: envio idempotente, nota determinística com gabarito congelado e tempo formal conferido pelo relógio do servidor.
- `GET /api/attempts/{id}/results/`: ownership e bloqueio enquanto houver formal ativo. Respostas vazias não contam como questões já respondidas nas métricas/filtros de treino.

Consultor e gateway MCP conferem formal ativo pela identidade, independentemente do contexto enviado. A conferência ocorre também na chamada de token delegado emitido antes do início da prova. UUID inválido e recurso inexistente retornam erros controlados, sem erro 500 nem consulta transversal.

## Migrations, testes e rollback

`0009_simulation_preparation` adiciona `Simulation.selection_config`; `0010_attempt_review_marks` adiciona booleano `AttemptAnswer.marked_for_review`, padrão falso. São aditivas e não recalculam notas históricas. `makemigrations --check` deve permanecer sem drift.

Testes de serviço/API cobrem seleção, capacidade, filtros, snapshot, replay, configuração divergente, ownership, marcações, submissão imutável, tempo formal, AI sem contexto e MCP previamente emitido. O E2E usa contas sintéticas, Next otimizado e Django descartável: interrompe a resposta HTTP **depois** de o servidor gravar tanto a preparação quanto o autosave, recarrega e verifica recuperação e nota. SQLite em arquivo WAL é exclusivo desse harness; concorrência PostgreSQL é verificada separadamente na imagem Linux.

Antes de produção: revisão independente, imagem do commit exato, testes reais PostgreSQL/serviços, backup e restore com reaplicação das migrations, reconciliação de privilégios e cutover/rollback P1. Voltar apenas para artefato seguro compatível, mantendo schema e dados. Não executar reverse migrations destrutivas em banco com uso: elas removem configuração e marcas. Não retornar à API histórica vulnerável nem restaurar backup por cima de novos envios sem reconciliação.

## Pendências explícitas

A seleção personalizada atual usa um único caderno, com filtros de disciplinas; combinação de vários cadernos e quotas por disciplina ainda não estão implementadas. Resultado mostra disciplina; comparações temporais, detalhamento visual por tema e tempo ainda precisam ser ampliados. O catálogo precisa paginação além de 500 cadernos. Simulado de segunda fase possui incremento próprio. Correção avançada por IA permanece fase posterior. Evidências e estado da release em [P3-P6-ENTREGA.md](P3-P6-ENTREGA.md).
