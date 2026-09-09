# P0 — homologação de concorrência

`scripts/test-api-isolated.sh` executa a API candidata sobre a imagem Python efetivamente usada pelo Kairós, com PostgreSQL/Redis novos e dados sintéticos. A fonte exportada do Git é montada somente para leitura. Não executa entrypoint de bootstrap, não utiliza credenciais produtivas, não publica portas, não faz pull nem acessa rede externa. Não representa deploy da imagem candidata.

Preparar um diretório exclusivo `/opt/kairos/runtime/p0/<run>/source` com export Git e checksum confirmado. Em `<run>/wheels`, colocar wheels públicas de `pytest==8.4.2`, `pytest-django==4.11.1` e suas dependências, previamente baixadas e conferidas; diretórios 0755 e arquivos 0644 para leitura pelo usuário 10001 do container. Nunca colocar uploads, dumps ou secrets nesses diretórios.

```bash
bash scripts/test-api-isolated.sh \
  /opt/kairos/runtime/p0/RUN/source/apps/api \
  /opt/kairos/runtime/p0/RUN/wheels
```

Exige ao menos 2,2 GiB de RAM disponível, imagens já existentes e snapshot no-touch antes/depois. Containers limitados a 1 CPU/1 GiB, banco em tmpfs, rede interna exclusiva, senha aleatória descartável. O cleanup confere labels e remove somente os recursos registrados; o arquivo de ambiente temporário também é removido. Logs e JUnit sintéticos ficam no diretório protegido de evidências; verificar `test_exit=0`, `cleanup_failed=0` e o comparador antes de considerar o gate aprovado.

Os settings `kairos.integration_test_settings` aceitam somente `kairos-test-postgres`/`kairos-test-redis`, usuário/banco `kairos_test` e credenciais `KAIROS_TEST_*`. O pytest cria o banco descartável `kairos_test_transactions`; Redis DB 15 é descartável e limpo entre testes. Não executar esses settings numa rede produtiva. Storage/e-mail permanecem em memória e Celery local.

Três testes adicionais usam transações, threads, barreira de início e conexões distintas: duas confirmações de cadastro MFA produzem um único vencedor; o mesmo OTP não abre duas sessões simultâneas; oito tentativas inválidas compartilham o limite de cinco configurado no teste. Em SQLite/LocMem, esses três testes são ignorados explicitamente, porque esse ambiente não demonstra concorrência dos serviços reais.

O ensaio do backup de 2026-09-09 06:28:29 UTC já concluiu recuperação dos dados arquivados e cleanup, com os 14 gates no-touch aprovados. Uma segunda falha transitória anterior não teve diagnóstico preservado; não é considerada explicada pelo sucesso posterior. O verificador agora conserva diagnóstico privado em falhas e aguarda PostgreSQL por TCP para evitar prontidão prematura do servidor temporário de inicialização. Executar novamente o conjunto final após qualquer correção, conforme AGENTS.md.

Ainda necessários antes da produção: backup novo e consistente, registro da configuração/imagem anterior, build da imagem candidata, smoke/E2E do login e operação administrativa, plano de troca e rollback sem bootstrap. Não declarar modernização concluída com a aprovação deste ensaio.
