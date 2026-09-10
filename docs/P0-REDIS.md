# P0 — cache e broker segregados

## Falha corrigida

A projeção anterior entregava a mesma senha Redis a API, worker e beat. O RedisCache padrão do Django desserializava pickle. Uma credencial de worker permitia escrever um objeto executável no cache lido pela API, atravessando a separação de secrets. Reprodução local utilizou somente uma função sintética sem acesso a rede, filesystem ou credenciais.

`core/cache_serialization.py` aceita somente JSON com marcador `j:` ou inteiros decimais signed-64 para preservar `INCR` atômico. Rejeita pickle, objetos Python, JSON inválido/duplicado, NaN/infinito, profundidade acima de 16 e valores acima de 64 KiB. O novo prefixo `kairos:cache:v2` impede leitura de valores pickle históricos; não exige FLUSHDB e não apaga o broker antigo.

## Contrato de credenciais

| Processo | Usuário | Credencial do recovery | Escopo |
|---|---|---|---|
| API/cache | kairos_cache | KAIROS_REDIS_CACHE_PASSWORD | kairos:cache:v2:* |
| API/broker | kairos_api_broker | KAIROS_REDIS_API_BROKER_PASSWORD | kairos:broker:v1:* |
| Worker/broker | kairos_worker_broker | KAIROS_REDIS_WORKER_BROKER_PASSWORD | kairos:broker:v1:* |
| Beat/broker | kairos_beat_broker | KAIROS_REDIS_BEAT_BROKER_PASSWORD | kairos:broker:v1:* |
| Redis/operação protegida | default | REDIS_PASSWORD | administração |

As quatro novas senhas são independentes `token_hex(48)`. O administrador Redis nunca entra no ambiente API/worker/beat. Ambiente API: `REDIS_CACHE_USER`, `REDIS_CACHE_PASSWORD`, `REDIS_BROKER_USER`, `REDIS_BROKER_PASSWORD`; worker/beat recebem apenas o par broker próprio. Host/port permanecem explícitos em Compose. Senhas precisam de percent-encoding ao montar URLs.

Settings: cache `KEY_PREFIX=kairos:cache:v2` e `OPTIONS.serializer=core.cache_serialization.StrictJSONSerializer`; Celery `CELERY_BROKER_TRANSPORT_OPTIONS.global_keyprefix=kairos:broker:v1:`. Se houver backend de resultado, aplicar também `CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS.global_keyprefix` ao mesmo namespace ou desativar resultados não consumidos. Redis DB numérico isoladamente não constitui ACL.

## Artefato e ativação

`scripts/redis-acl.py plan --recovery /opt/kairos/secrets/<release>/recovery.env` retorna metadados e hash. `render` exige `--expected-plan-hash` e `--destination /opt/kairos/secrets/<release>/redis.acl`; recusa sobrescrever arquivo e grava modo 0600. Recovery exige root, arquivo regular modo 0600 e namespace protegido. Nenhum comando imprime valores nem passa senhas em argv. O ACL gerado contém somente hashes SHA256 e regras fixas.

Root deve disponibilizar uma cópia do ACL legível exclusivamente ao UID efetivo do Redis, através de montagem read-only, e iniciar Redis com `--aclfile` apontando para essa cópia. Não montar recovery no container. Nunca tornar recovery legível ao UID Redis. ACL não é persistido por AOF: o arquivo precisa acompanhar o release e seu backup de configurações. Substituição deve usar novo artefato protegido, sem edição in-place de bind ativo. O script renderiza; não modifica Redis automaticamente.

Cache não recebe comandos administrativos ou scripting. Broker admite somente comandos de transporte Redis/Kombu e pubsub no prefixo permitido, incluindo SCRIPT LOAD/EVALSHA para os locks do transporte. Redis >=7 é requisito; executar teste real que tenta GET fora da ACL de dentro de Lua antes de aceitar a imagem. Referência: [ACL Redis](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/) e [API Lua Redis](https://redis.io/docs/latest/develop/interact/programmability/lua-api/).

## Transição e rollback

Pausar beat, impedir novas tarefas, drenar worker e registrar filas antigas antes de trocar o prefixo broker. Tarefas no namespace anterior não são automaticamente migradas. Não apagar filas para simular sucesso. Caso existam tarefas, concluir o processamento antigo isolado ou migrar somente mensagens JSON validadas sob controle operacional. Retomar produtores somente depois de validar ACL/cache/worker/beat juntos.

Trocar prefixo cache invalida limites e marcadores transitórios; durante a manutenção, aguardar ao menos 120 segundos antes de reabrir login/delegações para esgotar janelas curtas MFA/MCP antigas. Sessões são persistidas no banco e não dependem desse cache. Evitar retornar a serializer pickle: rollback seguro preserva JSON e ACL ou mantém o serviço fechado até correção.

## Verificação

Unit: `pytest tests/test_cache_serialization.py --ds=kairos.test_settings` no API; `python -m unittest discover -s scripts/tests -p test_redis_acl.py` na raiz. Testes isolados exigem `KAIROS_TEST_REDIS_ACL=1`, host explícito localhost/127.0.0.1 ou prefixo `kairos-test-`, e porta explícita. Redis deve ser descartável, iniciado pela equipe de deploy com ACL produzido por `credentials()` do teste; a suíte não cria usuários em servidor desconhecido.

Os testes reais verificam que worker/beat/API-broker não leem ou apagam nonce do cache, não reiniciam limites, não acessam CONFIG/ACL/FLUSHDB, não publicam em canal de cache e não atravessam ACL via Lua. Verificam também escrita broker permitida, incremento atômico cache e consumo único do nonce. Compatibilidade Celery end-to-end e leitura do arquivo ACL pelo UID do container são gates de integração Linux; não são comprovadas por testes unitários.

A cópia canônica root0600 `redis.acl` entra no backup. A cópia operacional `runtime/redis.acl`, pertencente ao UID Redis, deve ser regenerada dessa cópia no restore; não contém estado adicional e não requer credenciais novas.
