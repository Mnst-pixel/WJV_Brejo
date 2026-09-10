# Backup e recuperação — rotina P0/P1

Estado de implantação: esta é a rotina candidata. O ensaio real de 18:39 UTC em 2026-09-10 validou o backup e restore da rotina anterior; ainda não comprova o coordenador novo com credenciais segregadas. Consultar [P0-P2-ENTREGA.md](P0-P2-ENTREGA.md) antes de instalar units ou afirmar que a produção usa este fluxo.

## Contrato operacional

O restore pode executar um ensaio adicional de migrations quando recebe `KAIROS_RESTORE_API_IMAGE=sha256:<ID completo>` e `KAIROS_RESTORE_API_REVISION=<commit completo>`. Ambos são obrigatórios nesse modo e o label OCI deve coincidir. `restore-migration-probe.py` executa dentro da imagem candidata, UID 10001, filesystem read-only, sem capabilities, compartilhando somente o namespace de rede `none` do PostgreSQL temporário. Recebe apenas senha aleatória de teste; não recebe o ambiente original, dumps, storage ou broker produtivos. Rejeita qualquer conexão que não seja `kairos_restore` em loopback.

O ensaio compara hashes em memória das colunas e linhas originais antes/depois, verifica constraints/índices, aplica migrations e repete a execução para conferir idempotência. A tabela exata de associação `core_role_kairos_permissions` é excluída da preservação porque a migration 0003 substitui deliberadamente essa matriz; sua política tem testes separados. O relatório expõe somente contagens e estado, com limite de 200 mil linhas por captura e timeouts. Falha interrompe o ensaio e conserva diagnóstico protegido; todos os recursos temporários ainda passam pelo cleanup. Isso não testa credenciais segregadas, compatibilidade reversa ou rollback integral, nem substitui A/B/no-touch. Sem as duas variáveis, o restore mantém seu escopo anterior. A execução sobre backup real precisa constar em `P0-P2-ENTREGA.md` antes de ser considerada comprovada.

`scripts/backup-routine.py` coordena os scripts já validados `backup-predeploy.sh` e `verify-restore-isolated.sh`. O serviço `kairos-backup.service` passa a executar o coordenador; seu timer diário existente permanece às 03:17 em America/Sao_Paulo, com atraso aleatório de até 20 minutos e recuperação de execução perdida. Não existe segundo timer de restore: **cada backup diário novo é restaurado em recursos temporários exclusivos antes de entrar no catálogo**.

O verificador antigo `verify-restore.sh` cria bancos/bucket nos serviços produtivos e fica fora da rotina. Não o executar. O backup histórico `backup.sh` também fica fora da rotina: sua retenção genérica alcançava backups predeploy e seu cliente MinIO recebia o ambiente completo. Os arquivos históricos permanecem no Git para rastreabilidade; não são fonte de execução.

A sequência é lock → capacidade → baseline → backup novo → checksum → restore desse arquivo exato → checksum novamente → baseline/no-touch → catálogo → cópia off-host opcional → retenção → status/alerta. Não usa `--latest`, não importa backups históricos para a retenção e não restaura produção.

O lock não bloqueante `/opt/kairos/runtime/.operation.lock` é compartilhado também pelo deploy histórico `deploy-api-p0.py`, aberto com O_NOFOLLOW e conferência de arquivo regular. Deve ser compartilhado pelo novo deploy e por qualquer operação automatizada que dispute essa janela. O script predeploy conserva seu lock próprio; chamadas manuais diretamente aos scripts antigos não obedecem automaticamente ao lock novo. O operador deve usar o coordenador ou adquirir o lock comum. Concorrência recusada retorna erro no journal, sem sobrescrever o status do job já em andamento.

## Configuração e execução

Python 3 padrão do host é suficiente. Não há pip, instalação, pull ou dependência nova. Pré-requisitos dos scripts filhos permanecem em [P0-BACKUP.md](P0-BACKUP.md) e [P0-RESTORE.md](P0-RESTORE.md). Checkout `/opt/kairos/current` deve estar limpo e representar a configuração atual. Segredos permanecem em `/opt/kairos/secrets/.env`, root:root 0600.

```bash
sudo /usr/bin/python3 /opt/kairos/current/scripts/backup-routine.py
systemctl status kairos-backup.service kairos-backup.timer
journalctl -u kairos-backup.service --since today
```

O arquivo opcional `--config /opt/kairos/secrets/backup-routine.json`, também root:root 0600, permite ajustar caminhos operacionais, `retention_days` (14), `minimum_valid_backups` (3; mínimo aceito 2), `command_timeout_seconds` (7200 por etapa), `minimum_free_disk_bytes` (10 GiB) e `minimum_available_memory_bytes` (1 GiB). Caminhos precisam ser absolutos e canônicos, sem `..`, e resolver dentro de `/opt/kairos` (operação/configuração) ou `/srv/kairos` (backups); redirects de namespace e caminhos fora desse escopo são recusados antes de mkdir/chmod/lock/retenção. Chaves desconhecidas são recusadas. A execução com runner sintético é exclusiva dos testes e não é configurável pelo CLI. Configuração é recurso operacional de root, não entrada de usuário/API.

Os diretórios pai `/opt/kairos/runtime` e `/opt/kairos/runtime/baselines` devem existir e ser protegidos. A rotina verifica capacidade antes da captura. Esse piso é headroom conservador, não quota nem previsão do tamanho do próximo backup. O restore conserva seu limite de extração e verificação de disco; ao crescerem os dados, revisar os limites e capacidade antes de ampliar. Dumps e arquivos são consistentes nas condições detalhadas no P0: não constituem snapshot global entre os dois bancos e storage.

O coordenador cria temporariamente uma cópia da passphrase em seu diretório privado, modo 0600, e passa somente o caminho ao restore. Apaga-a em `finally`. Não faz `source` do ambiente nem coloca valor de secret em argumentos ou relatórios. Um encerramento forçado pelo kernel/host pode deixar esse arquivo; a recuperação deve inspecionar exclusivamente o diretório daquele run.

## Evidência, health e falhas

Arquivos sob `/opt/kairos/runtime/backup`, diretório 0700, documentos 0600:

- `status.json`: último run, `local`, `offhost`, `no_touch`, `result`, timestamps Unix, nome/hash do backup e caminho da evidência do restore.
- `alert.json`: alerta local persistente e estados sem valores privados. Falha retorna exit code 1 e deixa o serviço systemd em failed; ausência de destino externo produz alerta `EXTERNAL_BLOCKER`, com resultado local preservado e exit code 0.
- `catalog.json`: somente os arquivos criados por esta rotina e efetivamente restaurados, com SHA-256, prova de restore e timestamp.
- `<runid>/result.json`: resultado por execução; logs de comandos protegidos, nunca copiados integralmente ao Git ou à UI.

Consumidor health deve considerar `status.json` ausente ou `finished_at` mais antigo que a janela diária como `STALE`, além de considerar `result=FAIL`, `local!=PASS` ou `no_touch!=PASS` degradados. Não interpretar `offhost=EXTERNAL_BLOCKER` como falha do backup local. A UI deve mostrar apenas a projeção de estado e idade; não expor nomes de arquivos privados/logs. Erros de startup/lock/capacidade aparecem no journal e não apagam a última prova válida. `alert.json` é sinal local consultável; envio SMTP/webhook não é alegado quando ausente.

Cada comando tem timeout, diagnóstico em arquivo privado e encerramento do grupo de processos com TERM, janela de 60 segundos para limpeza e KILL como último recurso. A unidade usa `UMask=0077`, `PrivateTmp`, `NoNewPrivileges`, timeout total de 5 horas e encerramento do grupo. Interrupção abrupta pode exigir limpar recursos `kairos-restore-<runid>` após conferir ownership/labels conforme P0-RESTORE.

## Retenção e rollback operacional

Retenção local considera exclusivamente registros `managed_by=kairos-backup-routine-v1` com restore PASS. Mantém no mínimo os três arquivos mais recentes e todos os registros com menos de 14 dias. Antes de excluir um par antigo, confere novamente os checksums dos conjuntos protegidos e do par candidato. Jamais enumera `kairos-*.enc` para exclusão, apaga backups predeploy históricos ou aplica retenção após backup/restore/no-touch falhos.

O catálogo é gravado antes da retenção e atualizado atomicamente depois. Se houver interrupção entre excluir o arquivo e atualizar o catálogo, a próxima execução conclui somente a remoção do checksum daquele registro conhecido; conjuntos protegidos são revalidados antes. Evidências e logs antigos não têm remoção automática nesta primeira versão; acompanhar seu crescimento. Metadados do catálogo não são uma assinatura; proteção root e checksums continuam essenciais.

Rollback desta mudança: preservar os arquivos de dados e suspender somente `kairos-backup.timer`/serviço se a rotina falhar; restaurar a unidade versionada anterior somente após remover sua chamada ao verificador histórico. Nunca reativar deliberadamente o restore nos bancos produtivos. O procedimento manual seguro continua sendo predeploy + restore isolado sob lock/no-touch. A mudança não altera schemas nem dados produtivos; não exige migration.

## Destino off-host preparado

Sem destino fornecido: `EXTERNAL_BLOCKER`. A rotina local continua. Não há credenciais inventadas ou chamadas de rede antes da configuração.

Criar futuramente `/opt/kairos/secrets/backup-offhost.json`, root:root 0600, usando este esquema com valores reais somente fora do Git:

```json
{
  "endpoint": "",
  "bucket": "",
  "access_key": "",
  "secret_key": "",
  "region": "us-east-1",
  "prefix": "kairos/backups/",
  "retention_days": 90
}
```

`backup-offhost.py` usa HTTPS com validação TLS, SigV4, streaming, timeout de socket 60 segundos, limite de 4 GiB por PUT e nenhum redirect. Restringe objetos a prefixo `kairos/`. Envia arquivo **já criptografado**, exige SHA-256 no PUT, verifica tamanho/hash via HEAD e envia sidecar checksum. Chaves nunca aparecem na linha de comando; respostas de erro do provedor não são impressas. Upload falho não invalida o restore local, mas causa alerta e resultado global de falha.

O provedor deve implementar validação `x-amz-checksum-sha256`; isso precisa ser confirmado em teste isolado ao configurar o destino. O cabeçalho é o mecanismo documentado na [API S3 para integridade de uploads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html). Não se presume compatibilidade só porque o fornecedor se anuncia S3-compatible.

**Retenção remota:** `retention_days` é registrada como metadata; a política efetiva deve ser uma regra lifecycle do bucket restrita ao prefixo Kairós. O adapter não possui permissão administrativa nem altera lifecycle de bucket compartilhado. Saída informa `BUCKET_LIFECYCLE_REQUIRED`; metadata sozinha não expira objetos. Ao fornecer o destino, configurar/validar sua política de retenção e acesso mínimo PutObject/GetObject apenas no prefixo. Não conceder administração global nem secrets de aplicações. Recuperação fora do VPS continua `NOT_VERIFIED` até download e restore em ambiente externo isolado. Sucesso PUT/HEAD não significa recuperação completa off-host.

## Testes e aceitação

```bash
python3 -m unittest discover -s scripts/tests -p 'test_backup_*.py' -v
```

Suíte nova exercita arquivo exato, falha de backup/restore, no-touch reprovado, checksum corrompido, passphrase temporária/duplicada, catálogo, retenção/minimum, histórico preservado, interrupção entre par/catálogo, destino ausente ou falho, config inválida, PUT/HEAD/checksum e redirect. Teste real de flock/ownership requer Linux root; Windows não oferece esses mecanismos e registra skip explícito. Os testes utilizam arquivos sintéticos e transporte/comandos falsos; não contatam VPS, Docker, bucket ou dados de produção.

Antes de declarar rotina operacional: executar a suíte sem skips em Linux, revisão B independente, validar a unidade systemd, capturar baseline atual, executar um ciclo real completo com os scripts/imagens do release e confirmar no-touch, timers, artefato/checksum/prova/status e ausência de temporários. Só então considerar o timer novo validado. Testes locais não substituem essa evidência.

## Correções decorrentes da revisão B

A revisão independente encontrou dois problemas: configuração aceitava caminhos absolutos fora do namespace e o deploy histórico utilizava lock diferente. Ambos foram corrigidos. Testes cobrem recusa antes de mutação, resolução de symlinks para fora do projeto, caminho compartilhado e disputa real entre backup/deploy em Linux. Revisão A deve ser repetida e revisão B final confirmada antes da operação. SigV4 PUT e HEAD também foram comparados independentemente com botocore usando endpoint com porta não padrão, sem contato externo: assinaturas coincidiram.
