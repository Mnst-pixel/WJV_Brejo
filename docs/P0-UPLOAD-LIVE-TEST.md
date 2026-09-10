# Pipeline real de upload em fixtures isoladas

`apps/api/tests/test_upload_pipeline_live.py` é opt-in via `KAIROS_TEST_LIVE_UPLOAD=1`. Não altera aplicação, migrations ou serviços produtivos. O executor é responsável por criar/remover uma rede Docker interna exclusiva, com imagens imutáveis já disponíveis e aliases de teste. A suíte não faz deploy, não abre portas do host e não aceita endpoints livres.

Contrato das fixtures:

- PostgreSQL: `kairos-test-postgres`, usuário `kairos_test`, banco sintético `kairos_test`/`kairos_test_transactions`, settings de integração PostgreSQL;
- MinIO: `http://kairos-test-minio:9000`, root user sintético `kairos_test`, bucket `documents` privado;
- ClamAV: `kairos-test-clamav:3310`, assinaturas disponíveis e serviço pronto antes do pytest;
- Parser real: alias `parser:8090` somente na rede de teste, executando o mesmo server/child confinado da imagem candidata;
- `KAIROS_TEST_POSTGRES_PASSWORD`: segredo sintético aleatório de 64 caracteres hexadecimais; usado também como senha da fixture MinIO;
- `PARSER_API_TOKEN`: o mesmo segredo sintético da fixture, exclusivo desse ambiente efêmero. Não copiar credencial produtiva.

O teste configura S3Storage real com os limites de spool/timeout/transferência da aplicação. Cria o bucket privado apenas se necessário; cada fixture usa prefixo aleatório `live-pipeline/<uuid>/`. No teardown, remove exclusivamente objetos desse prefixo, validando cada chave. Não exclui bucket ou objetos fora do próprio prefixo. Os containers/volumes/rede continuam sendo responsabilidade do executor isolado.

Há seis casos executáveis: TXT, DOCX e PDF pequenos gerados localmente com texto sintético; ClamAV limpo + EICAR direto; quota por proprietário; ZIP bomb DOCX. Scanner, parser HTTP, magic bytes e S3 não são mockados. Apenas enqueue é desativado para processar a task explicitamente no mesmo processo de teste; broker/Celery real possui teste separado.

Cada formato limpo percorre endpoint multipart → quarentena real → ClamAV → parser real → storage privado → API de download. Confere hash/MIME, texto extraído, limpeza de quarentena, idempotência, bytes completos do download, attachment/no-store, outro usuário 404, API anônima 403, leitura S3 sem assinatura 403, sessão revogada 401 e exclusão com remoção dos objetos. Quota de A não bloqueia B; exclusão concluída permite nova reserva. Nenhum desses estados representa publicação jurídica.

EICAR é enviado diretamente à fixture ClamAV, sem depender da classificação MIME antecipada e sem gravar um arquivo de teste antivírus no storage. O ZIP bomb contém texto altamente compressível limitado a 5 MiB: exige rejeição pelo parser HTTP real e bloqueio de download após processamento; se a própria heurística do ClamAV o rejeitar antes, o teste ainda comprova fail-closed e testa o parser separadamente.

Execução pelo runner de integração, após readiness das fixtures:

```sh
python -m pytest tests/test_upload_pipeline_live.py -q
```

Validação local: seis SKIP esperados sem opt-in, Ruff PASS, geradores DOCX/PDF com texto recuperável e ZIP com razão de expansão acima de 100 PASS. Libmagic não está disponível no runtime Windows local; identificação de MIME e pipeline completos exigem a rodada Linux real. Sem opt-in, os seis casos devem aparecer como SKIP e isso **não comprova** o pipeline. O teste falha se o opt-in estiver ativo e faltar qualquer fixture/credencial sintética. A criação de PDF/DOCX reutiliza PyMuPDF e python-docx já presentes na API. Não instala dependências novas. Logs do executor não devem imprimir env/credenciais; a suíte não imprime esses valores.
