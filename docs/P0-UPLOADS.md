# Uploads privados e parsing isolado

## Contrato e modelos

O fluxo preserva FileAsset e seus identificadores existentes. `Plan`, `Enrollment` e `UploadPolicy` acrescentam configuração de limites e quota com constraints. `Enrollment.owner` é único, o intervalo temporal deve ser válido e quota de um plano não pode ser menor que o seu limite de arquivo. A migration `0004_upload_foundation` depende da fundação RBAC `0003`.

Sem matrícula específica, vale a política global: arquivo até 25 MiB e quota lógica de 250 MiB por usuário. O máximo efetivo de arquivo é o menor entre settings, política e plano. Matrícula suspensa/expirada/futura ou plano inativo recusa novos uploads. Política singleton pode desativar uploads. Quota lógica conta bytes originais reservados, inclusive quarentena/falhas e exclusão ainda não limpa; não contabiliza cópia transitória e texto derivado como novos uploads. O armazenamento físico precisa acomodar essas cópias, sob limites operacionais próprios.

Alteração de plano ou matrícula é operação administrativa, não campo aceito pelo endpoint de upload. Formulários/RBAC de administração devem usar os controles backend da fundação. Os dados pessoais e arquivos permanecem fora do Git.

## Entrada, ownership e publicação

`BoundedUploadHandler` deve ser o primeiro em `FILE_UPLOAD_HANDLERS`. Interrompe durante a leitura quando o agregado de arquivos ultrapassa o máximo global, antes dos handlers de memória/disco. O edge mantém seu limite de request, incluindo multipart. Após autenticação, o serviço verifica limites específicos, MIME por magic bytes, tamanho real, SHA-256 e reserva quota sob lock da linha do usuário. Duas reservas do mesmo usuário não podem ultrapassar a quota em PostgreSQL.

Nome original é apenas metadata; chave interna usa UUID, proprietário e extensão determinada pelo MIME. O retorno efetivo de `storage.save` é persistido. Registro `receiving` precede a cópia; só a gravação confirmada transita a `quarantined`. Dispatch usa `on_commit`; se o broker falhar, a linha durável continua disponível à recuperação periódica.

O worker confere tamanho, hash e magic novamente, executa ClamAV por streaming e só envia ao parser se o scanner retornar exatamente `OK`. `FOUND` rejeita e remove quarentena. Erro de scanner/parser preserva quarentena, registra falha sem conteúdo e retenta com backoff. Três tentativas no máximo; após isso `processing_failed`, sem liberação automática.

Sucesso grava original e texto privados sob chaves exclusivas do claim, confirma a titularidade do claim sob transação e só então muda para `clean / processed_pending_review`. Esse estado permite ao proprietário baixar o próprio arquivo; **não significa aprovação jurídica nem publicação no corpus**. Parser e scanner jamais publicam conteúdo.

API lista/consulta/exclui somente objetos do proprietário. Download retorna rota da própria API (`/api/files/<id>/content/`), que repete sessão/autoridade atual, ownership e estado limpo/processado. MinIO permanece privado na rede Docker. A resposta é attachment, `private, no-store` e `nosniff`; tamanho diferente do cadastro bloqueia a leitura. Campos `claim_token`, `text_key` e dados internos não devem aparecer no serializer público. `delete_pending` invalida claim; quota só é liberada após limpeza bem-sucedida e transição para `deleted`. Tombstones preservam identidade para que task atrasada não ressuscite o arquivo.

O acesso a arquivos usa limites de requisições separados da IA: por usuário/global a cada minuto, upload 12/120, download de bytes 30/120 e metadados 300/1200. Contadores Redis indisponíveis bloqueiam somente o serviço de arquivos com 503 redigido; excesso retorna 429. S3 usa spool de memória de 2 MiB com rollover para temporário, timeouts de conexão/leitura e transferência limitada. Detalhes e testes de revogação/recursos em `P0-P2-REVIEW-B-ACCESS.md`.

## Worker e recuperação

`core.tasks.scan_and_process_file` delega ao serviço com claim temporário de 300 segundos. Duas entregas simultâneas encontram o mesmo claim; saída de worker cujo claim foi substituído é descartada. A execução confirmada não é processada novamente.

`core.tasks.recover_pending_uploads`, agendada a cada 60 segundos, despacha até 100 registros por rodada e deixa claims/backoff decidirem elegibilidade. Também limpa quarentenas após sucesso, exclusões pendentes e uploads interrompidos há mais de dez minutos. Falhas de limpeza têm log de evento sem chave privada. Casos de morte abrupta entre gravar uma saída S3 exclusiva e registrar essa chave podem deixar objeto órfão: inventário de storage e limpeza administrativa por provenance ainda são necessários para essa janela, sem apagar objetos desconhecidos automaticamente.

## Serviço parser

Contrato fixo: `POST http://parser:8090/v1/parse`, `Authorization: Bearer <PARSER_API_TOKEN>`, Content-Type permitido, Content-Length até 25 MiB e `X-Content-SHA256`. Não recebe URL, comando, caminho, filesystem root ou opções de execução. `GET /healthz` serve somente prontidão. Token precisa ter pelo menos 32 caracteres, exclusivo do worker e parser. Não compartilhar secrets de Django, DB, MinIO, MCP ou provedor IA com esse serviço.

Compose/build:

- Build context raiz do repositório; Dockerfile `services/parser/Dockerfile`; ARG `KAIROS_API_BASE_IMAGE` é a imagem de dependências API já inspecionada, identificada por digest. Não faz pip/apt/pull.
- Imagem contém `server.py`/`child.py`, roda UID/GID 10001, entrypoint Python fixo.
- Rede exclusiva interna `kairos-parser`, somente worker e parser; nenhuma porta publicada, volume de dados, host bind, Docker socket ou rede externa.
- `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`, limites de CPU/RAM/PIDs; `/tmp` tmpfs limitado (64 MiB ou mais, após medir). Sugestão inicial: 0,5 CPU, 640 MiB e 64 PIDs. Não tornar root para contornar falha.
- Healthcheck HTTP local `/healthz`; servidor aceita somente um parse simultâneo e responde 429 aos concorrentes. A thread de health continua disponível durante parsing.

O servidor não carrega Django. Grava arquivo temporário privado e invoca filho com comando fixo, Python `-I`, sem stdin e ambiente limitado a PATH/LANG/HOME. `PR_SET_DUMPABLE=0` protege o ambiente do servidor contra leitura pelo filho via `/proc`. O filho aplica rlimits de CPU, endereço, tamanho de arquivo, descritores e core dump; filtro seccomp nega syscalls de rede, confere arquitetura e bloqueia bypass x32. Falha ao instalar sandbox recusa parsing. Arquiteturas suportadas: x86_64 e aarch64 Linux.

PDF: máximo 300 páginas, senha recusada, extração progressiva e saída total até 1 MiB. DOCX: máximo 2.000 entradas, 50 MiB expandidos e razão 100:1; exige estrutura OOXML, rejeita duplicação, traversal, caminhos Windows, links, criptografia e referências XML perigosas. Imagem: até 10 milhões de pixels, verificação Pillow e OCR Tesseract com comando fixo; timeout 60 segundos. Filho inteiro: timeout 95 segundos, grupo encerrado se excedido. Worker limita também a resposta HTTP recebida e não segue redirects/proxy ambiente.

O sandbox é camada adicional às fronteiras do container. Não executar o parser child diretamente no host com arquivos de produção. Atualizações das bibliotecas/imagem precisam seguir a política de supply chain e testes da plataforma.

## Testes, implantação e rollback

```bash
cd apps/api
pytest tests/test_upload_security.py -q
cd ../..
python -m unittest discover -s services/parser -p test_parser.py -v
```

Os testes de API/serviço usam scanner/parser controlados para comprovar transações, ownership, quota, falhas e liberação. Teste PostgreSQL concorrente exige banco isolado e não roda em SQLite. Teste EICAR/arquivo limpo exige explicitamente `KAIROS_TEST_CLAMAV_HOST=kairos-test-clamav`; nenhum outro hostname é aceito. O teste não injeta assinatura EICAR em armazenamento produtivo.

Testes do parser usam HTTP real em localhost com dados sintéticos; casos Linux executam filho verdadeiro e conferem negação de socket por seccomp. Não considerar o pipeline operacional até esses testes passarem na imagem candidata, incluindo ClamAV real, parser real, S3 privado, quota concorrente e download autenticado do proprietário pela API. Skips Windows são limites explícitos, não aprovação desses gates.

Implantar com migration reproduzível, backup restaurado e API/worker/parser provenientes do release registrado. Rollback de aplicação deve preservar os novos dados e desativar novos uploads se o código antigo não conhecer os estados; não devolver o worker antigo com parsing no processo Django. Tabelas de plano/matrícula não devem ser removidas se já receberam dados. Não restaurar banco antigo apenas para reverter código.
# Administração de limites e matrículas

Planos e limites globais são editados em formulários de MiB, sujeitos a `settings.manage` e MFA no backend. A quota tem teto compatível com bigint e deve comportar o maior arquivo permitido. Uma edição de nome/quota carrega o registro atual sob lock e grava somente campos alterados, preservando suspensões/desativações concorrentes. Escritas de configuração compartilham mutex transacional na permissão semeada `settings.manage`, inclusive criação do singleton e unicidade do código de plano.

Matrícula mantém titularidade permanente; a edição preserva alterações concorrentes de outros campos e criação duplicada é recusada após lock do usuário. Combinações inválidas resultantes de alteração concorrente são recusadas sem erro interno. `tests/test_upload_admin.py` cobre permissões, revogação do ator, formulários inválidos, overflow, singleton, titularidade e preservação de suspensão/desativação.
