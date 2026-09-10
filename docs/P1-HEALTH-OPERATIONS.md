# Saúde operacional da release ativa

`scripts/health-report.py` é a implementação canônica; `health-report.sh` apenas a executa com Python 3 do host. Sem dependências adicionais, leitura de `.env`, execução de Compose, fallback de checkout histórico ou consulta a containers de outros projetos. A ferramenta não instala nem inicia serviços.

## Fontes e critérios

- `/opt/kairos/runtime/active-release` é **arquivo regular root:0600**, contendo caminho absoluto de um descriptor diretamente em `/opt/kairos/runtime/releases/`. O descriptor, `manifest.json` e `release.env` precisam corresponder ao contrato da release. Não é symlink/diretório. Ponteiro ausente ou inválido resulta em FAIL, nunca fallback.
- Compara Git HEAD, checkout limpo, hashes de Compose/Caddy/matriz de credenciais, imagens imutáveis e revisão OCI das imagens próprias. Verifica os nomes/projeto/labels dos 13 serviços normais. `migrate` é manutenção, deve estar ausente após o `run --rm`. Inventário inesperado, duplicado, falta de serviço ou imagem divergente bloqueia o gate.
- Docker retorna apenas projeções de identidade, estado, imagem, health, OOM/restarts e **nomes** de variáveis. Variáveis sensíveis fora da matriz de credenciais/ambiente explícito do serviço geram FAIL. Isso detecta distribuição indevida por nome; não substitui a revisão dos valores/privilégios feita no provisionamento.
- Executa probes fixos somente por ID de container com identidade/imagem/escopo/health aprovados: PostgreSQL, Redis, MinIO, MariaDB e resposta Celery dirigida ao hostname do próprio worker. Nenhum comando arbitrário é recebido como argumento. Redis usa `REDISCLI_AUTH` dentro do próprio container, sem senha no argv. Não há master env no processo host.
- HTTPS público do host Kairós fixo: `/healthz`, `/api/health/ready`, `/app/api/health` e `/`. Valida TLS, exige HTTP 200 e não segue redirects. Readiness da API exige explicitamente PostgreSQL e Redis `true`. Lê no máximo 64 KiB + 1 de cada resposta; não grava corpo/cookie/header. HTML pode exceder o prefixo lido sem reprovar a disponibilidade.
- Containers precisam estar `running/healthy`, sem OOM e com menos de três reinícios acumulados. O limite é conservador e exige investigação; não reinicia nada automaticamente.
- Capacidade: pelo menos 512 MiB de memória disponível e mais de 15% de disco livre. São sinais de saúde, não substituem o headroom maior exigido para backup/restore.

## Backup verificável

Lê `status.json` e `catalog.json` root:0600 em `/opt/kairos/runtime/backup`. Exige último resultado local PASS, no-touch PASS, catálogo gerenciado pela rotina, idade máxima de 36 horas, arquivo criptografado não vazio e checksum lateral apontando exatamente para o arquivo/hash catalogado. A evidência referenciada deve estar no diretório de backups Kairós e conter PASS de PostgreSQL/MariaDB/MinIO, saída zero e limpeza concluída.

Durante backup em execução por até cinco horas, mantém como referência o último conjunto anteriormente restaurado, ainda dentro das 36 horas. Não considera o conjunto em produção como já recuperável. Primeira execução sem conjunto catalogado anterior continua FAIL até validar o restore. Uma rotina travada, último resultado FAIL ou evidência incompleta reprovam o gate.

O campo `integrity=catalog_and_checksum_reference` é deliberado: o health a cada cinco minutos **não recalcula o hash de todo o arquivo**. O hash completo é verificado pela rotina antes/depois do restore; `full_checksum_at` informa essa data. Para corrupção posterior do conteúdo, execute novamente a verificação isolada/integridade da rotina. Ausência de storage externo aparece como `offhost_EXTERNAL_BLOCKER`, sem reprovar a saúde local. Off-host configurado que falhou permanece falha operacional.

## Timers, relatórios e logs

Verifica apenas `kairos-backup.timer`, `kairos-health.timer` e respectivas services. Timers devem estar loaded/active/enabled e possuir próximo disparo. Services podem estar inativas após sucesso. A service de health atualmente em execução não perpetua um resultado anterior falho. Consulta somente metadados do journal dessas duas services, com contagem limitada a 1.000 eventos de prioridade 0..3 nas últimas 24 h; exclui MESSAGE e qualquer texto de logs. A contagem histórica é informativa, enquanto estado atual das units participa do gate.

O instalador da release deve preparar `/srv/kairos/observability` como diretório root:0750 e instalar as units/timers versionadas. Todos os ancestrais precisam ser root-owned, sem escrita de grupo/outros e sem symlinks. A ferramenta usa lock próprio `.health.lock`, sem competir com o lock exclusivo de backup/deploy; ela somente observa essas operações. `kairos-health.service` mantém ProtectSystem/ProtectHome/PrivateTmp e acesso de escrita apenas ao diretório de observabilidade, UMask 0077 e timeout de cinco minutos.

Publica atomicamente arquivos individuais root:0600:

- `health-<UTC>-<hash12>.json` e `.status`, com schema/managed_by/timestamp/status/checks e resumo com SHA-256;
- `latest.json` e `latest.status`. Se o leitor observar o intervalo entre as duas substituições, deve conferir o hash/arquivo histórico indicado em `.status` e repetir a leitura. Não existe promessa de transação atômica entre dois arquivos distintos;
- stdout/stderr contém apenas status, quantidade de alertas e caminho fixo. Falha retorna exit 1 e fica registrada no estado da unit. Lock já ocupado retorna SKIPPED sem substituir o relatório em execução.

Retenção de 30 dias somente para pares de arquivos com prefixo/formato exatos, `managed_by=kairos-health-v1`, timestamp antigo, hash do JSON coerente com nome e sidecar, ownership/permissões verificadas. Não remove logs arbitrários, relatórios históricos antigos ou arquivos de terceiros. Um relatório antigo cujo par esteja incompleto é preservado para análise.

## Entry points históricos

`backup.sh` e `verify-restore.sh` agora retornam **64** com deprecação explícita. Não abrem lock, não leem secrets e não executam Docker. Isso impede a antiga verificação que criava bancos dentro das instâncias em produção e evita executar novamente a rotina dentro de outro lock.

Backup automático/manual usa `kairos-backup.service` → `backup-routine.py`. Restore avulso usa `verify-restore-isolated.sh` com arquivo criptografado **exato** e arquivo de passphrase root:0600, conforme BACKUP-RESTORE.md. Não existe `--latest` implícito. Rollback dessa mudança não deve reativar os scripts históricos inseguros; corrija o novo health ou pause somente seu timer, mantendo backup/restauração canônicos.

## Validação e limites da entrega

Suíte local: `python -m unittest discover -s scripts/tests -p test_health_report.py -v`; lint: `python -m ruff check scripts/health-report.py scripts/tests/test_health_report.py`; sintaxe dos wrappers com `bash -n`.

Testes cobrem manifesto/HEAD/config/env divergentes, ausência de fallback, ownership Docker, imagens e scopes, OOM/restarts, referência/restauração/idade de backups, rotina travada, timers, journal sem conteúdo, HTTP redirect/readiness, redaction de exceções, publicação e retenção. O teste de permissões/symlink/flock requer Linux root e usa apenas fixture temporária própria em `/root`.

Este lote não executou health no VPS nem instalou units. Antes de declarar P1 operacional: executar teste Linux sem skip, revisar B, instalar units no deploy aprovado, observar uma execução real com todos os probes, um backup/restauração automático, FAIL induzido em fixture isolada e posterior recuperação. Confirmar compatibilidade dos templates Docker/nomes de env herdados das imagens; qualquer escopo inesperado exige diagnóstico explícito, sem ampliação global de allowlist. A revisão de logs de aplicação não é substituída por estas projeções operacionais.
