# Questões e treino — incremento P3/P5

O painel **Questões e provas** usa formulários Django e os mesmos papéis, MFA e sessões da administração editorial. O aluno estuda no Next.js. Nenhum registro educacional é gravado no WordPress.

## Operação editorial

1. Cadastre uma prova ou caderno com nome, autoria/organizadora, edição, data, fonte HTTPS e duração.
2. Crie a questão, escolhendo disciplina e tema; escreva enunciado, alternativas consecutivas, gabarito, explicação, fundamento e metadados.
3. Salve o rascunho e envie para revisão com comentário. Um revisor independente confere também gabarito, fonte e vigência.
4. Após aprovação, o responsável pela publicação libera a versão. Autor e pessoa que encaminhou não podem aprovar o próprio pacote.
5. Para corrigir, abra **Criar nova revisão da questão**. A versão publicada e as tentativas já iniciadas permanecem preservadas. Arquivar impede novos estudos daquela publicação.

Origem oficial, autoral ou adaptada é uma declaração editorial; cadastrar uma URL não afirma que ela foi coletada nem autentica automaticamente seu conteúdo. Não importar material antigo diretamente como publicado.

## Estudo e persistência

`GET /api/questions/` admite disciplina, tema, dificuldade, ano, busca e modos todas/inéditas/respondidas/erradas/favoritas/revisão/aleatórias. Não fornece explicação nem gabarito. O modo aleatório reorganiza cada consulta; não constitui uma sessão congelada nem garante exclusividade entre páginas. Simulados usam sua própria lista congelada.

`POST /api/practice/answers/` recebe questão, alternativa, UUID de confirmação e tempo. O servidor cria uma tentativa de treino, congela o pacote, salva e calcula o resultado dentro de transação. Repetição do mesmo envio retorna o resultado existente; reaproveitar a confirmação para outra resposta gera conflito. Erro na operação desfaz também o simulado auxiliar. UUIDs de confirmação são separados por conta.

`GET /api/practice/history/` mostra somente o treino dessa conta. `GET /api/study/accuracy/` agrega fatos calculados após submissão, incluindo disciplina. Respostas antigas sem fato calculado são informadas como não classificadas, sem recalcular silenciosamente notas históricas. As classificações por disciplina seguem a taxonomia da questão; versões e nomes usados na tentativa permanecem no snapshot.

`GET/PUT /api/practice/questions/{questão}/marks/` consulta/salva favorito e marca de revisão, com ownership, idempotência e limite por conta. O endpoint altera somente a marca de revisão da questão inteira; outras anotações permanecem disponíveis.

Durante um simulado formal ativo não é possível iniciar outra tentativa, submeter treinos antigos ou consultar resultados, histórico de treino, estatísticas de acerto e filtro de erros. Repetir a criação idempotente do mesmo formal continua possível. Finalizar o formal libera essas consultas. A autorização consulta o modo congelado da tentativa.

## Integridade e migrations

- `0007_question_editorial`: metadados versionados e workflow ligados a versões de questão/gabarito, aprovador e responsáveis/timestamps, com constraints de estado.
- `0008_objective_answer_facts`: acerto calculado no backend, inicialmente NULL para respostas antigas; índice de questão/acerto.
- Aprovação contém hash do pacote completo. Publicação, serialização ao aluno e captura da tentativa conferem esse hash; mudanças posteriores em alternativas, metadados ou gabarito interrompem o acesso. Prefetch e relações carregadas mantêm o número de queries estável na página.
- Reconciliar `scripts/database-roles.py` depois das migrations: runtime não pode atualizar/apagar alternativas ou metadados. Esse controle só é operacional após aplicação e teste real dos grants; não confundir código com ativação no VPS.

## Homologação e rollback

Antes do deploy: commit limpo, imagem exata, suíte isolada PostgreSQL/serviços, backup consistente e restore do backup com migrations reaplicadas, verificação independente e no-touch. A troca de release segue o coordenador P1, com registro das imagens e configuração.

Rollback preferido é do artefato, mantendo as duas migrations aditivas e todos os registros. Código antigo não oferece o novo workflow e pode ocultar novas publicações, mas não deve apagar versões, aprovações ou respostas. Não executar reverse migration em banco com uso: ela descartaria metadados/fatos. Se necessário recuperar o banco inteiro, usar o restore validado para destino isolado, conferir consistência e só então decidir a troca controlada. Nunca retornar à API histórica vulnerável.

## Limites deste incremento

Ainda faltam interface completa de simulados personalizados, métricas temporais avançadas, integração contextual com consultor, importação em lote de questões e revisão por vigência com alertas. A seleção aleatória não substitui a sessão personalizada. Editor de texto é simples, sem HTML executável. A entrega global P3–P6 permanece incompleta até concluir também a segunda fase e os gates operacionais.
