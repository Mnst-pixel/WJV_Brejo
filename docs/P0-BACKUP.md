# Backup adicional antes do deploy P0

`scripts/backup-predeploy.sh` cria um arquivo novo para uma mudança controlada. Não chama o backup legado, não remove backups anteriores, não aplica retenção, não para escritores e não executa restore. Deve ser executado a partir do código versionado e revisado, como root, sem argumentos:

```bash
sudo bash scripts/backup-predeploy.sh
```

O checkout implantado `/opt/kairos/current` deve estar limpo. O script registra seu HEAD e os IDs efetivos das imagens/containers; criar o backup não substitui preservar a imagem anterior para rollback. Containers PostgreSQL, MariaDB e MinIO precisam manter nomes `kairos-<serviço>-1` e labels Compose de projeto/serviço Kairós. A rede `kairos-data` deve pertencer ao projeto e ser interna. Identidades divergentes interrompem a operação.

## Proteção e limites operacionais

- Exige `/opt/kairos/secrets/.env` root:root 0600; não faz `source`, expansão shell ou impressão de credenciais. O parser aceita valores literais sem interpolação, com aspas externas simples ou duplas opcionais. Variáveis duplicadas ou valores inválidos são recusados.
- Usa `umask 077` e lock exclusivo `.kairos-predeploy.lock`. Esse lock impede somente execuções simultâneas **deste script**; coordenar a janela com o timer legado, restore e outros escritores operacionais. O arquivo de lock vazio pode permanecer após execução.
- `pg_dump -Fc` fornece snapshot consistente do PostgreSQL. `mariadb-dump --single-transaction --quick` fornece consistência transacional para tabelas InnoDB; DDL concorrente ou tabelas não transacionais não têm essa garantia.
- MinIO é lido através de container `kairos-backup-<runid>-mc`, imagem local resolvida por ID, sem pull. Só `MINIO_ROOT_USER` e `MINIO_ROOT_PASSWORD` são passados do ambiente protegido; comandos fazem leitura do bucket `documents` para o staging. Nenhum comando escreve no bucket produtivo. O container tem limites de CPU/RAM/PIDs e label exclusivo de ownership. Seu diretório de configuração é criado em `/tmp/kairos-backup-mc` com modo 0700/umask 077; ambos os comandos mc recebem explicitamente `--config-dir`. Esse diretório existe somente no filesystem temporário do container e desaparece com sua remoção.
- WordPress e Hermes são arquivados dos diretórios Kairós confirmados, sem atravessar filesystems. Se o GNU tar detectar alteração durante a leitura e retornar erro, o script falha. Isso não transforma uma captura de arquivos vivos em snapshot global.
- Reserva de espaço deve ser avaliada antes da execução: dumps, cópia dos objetos, TARs e arquivo criptografado coexistem temporariamente. Não há quota de disco dedicada. Não iniciar se a pressão de disco/RAM puder afetar outros projetos.

**A captura não é atômica entre os dois bancos e arquivos.** Nenhum escritor é pausado. Objetos alterados entre leitura do banco e leitura do storage podem produzir referências temporalmente divergentes. A evidência registra início/fim e essa limitação. Para uma mudança que dependa de snapshot global, preparar separadamente janela de quiescência ou mecanismo equivalente; não atribuir essa garantia a este script.

## Conteúdo e publicação do arquivo

Formato compatível com `verify-restore-isolated.sh`: `postgres.dump`, `mariadb.sql`, `minio-documents/`, `wordpress.tar`, `hermes.tar`, `secrets.env`, `git-revision.txt` e `MANIFEST.sha256`. Acrescenta inventário Docker restrito a IDs, nomes, status, timestamps, tags/digests e label `org.opencontainers.image.revision`; não exporta `.Config.Env`, argumentos ou inspect bruto. A revisão declarada na imagem é registrada separadamente do HEAD do checkout, que pode ser diferente; label ausente permanece `null`, sem inferência a partir do Git local.

As configurações copiadas são Compose, Caddyfile, virtual host Nginx Kairós e quatro unidades/timers Kairós em `/etc/systemd/system`. O script também consulta somente o label `com.docker.compose.project.config_files` do container API validado. Divide a lista por vírgula sem executar/interpolar conteúdo e copia os arquivos adicionais, na ordem declarada, como `configuration/api-compose-extra-N.yaml`. O Compose base já capturado não é duplicado. Caminhos declarados e resolvidos devem ficar em `/opt/kairos/`; caminhos externos, listas vazias/malformadas e caracteres de controle interrompem o backup. Assim, um override externo ao checkout, mas dentro do diretório operacional Kairós, acompanha a imagem efetivamente usada.

Symlinks são resolvidos apenas para os caminhos Kairós permitidos e arquivados como arquivos regulares; `configuration/origins.tsv` registra origem/destino e `configuration/api-compose-config-files.txt` preserva a ordem original declarada pelo container. Não inclui configurações globais do Nginx, projetos alheios, chaves TLS, configurações externas de provedores ou estado do Docker daemon. Configurações adicionais que não apareçam nesses caminhos/labels continuam exigindo análise no preflight. Copiar os arquivos não executa `docker compose config`, migrations ou bootstrap.

O arquivo contém segredos e dados privados **dentro da camada criptografada** AES-256-CBC/PBKDF2 de 300.000 iterações, mantendo compatibilidade com o restore existente. Sua passphrase vem do ambiente protegido para a memória do processo, nunca dos argumentos ou logs. Não enviar o arquivo, dumps, staging ou passphrase ao Git. SHA-256 verifica integridade; não constitui assinatura autenticada do backup.

Durante a criação, o destino termina em `.pending`. Somente após criptografia concluída, arquivo não vazio e checksum conferido são publicados o par:

```text
/srv/kairos/backups/kairos-predeploy-<runid>.tar.gz.enc
/srv/kairos/backups/kairos-predeploy-<runid>.tar.gz.enc.sha256
```

O checksum é publicado antes do arquivo definitivo. O par final é novamente conferido, inclusive ownership/permissões. Nenhum arquivo anterior é sobrescrito. Arquivos `.pending` sobrevivem à falha para diagnóstico/retentativa controlada e não devem ser tratados como backup aceito. O timer legado continua com sua política de retenção própria; este script não a modifica.

## Resultado, falha e rollback

`KAIROS_PREDEPLOY_BACKUP=PASS scope=archive_created` significa que o arquivo final existe, seu checksum passou e a limpeza dos temporários próprios terminou. A saída também declara `RECOVERABILITY=NOT_YET_VERIFIED`. Executar o verificador isolado sobre **este arquivo exato**, registrar evidência e realizar no-touch antes/depois antes de qualquer deploy autorizado.

A limpeza remove somente o container cujo ID foi criado nesta execução e cujo label corresponde ao run, além do staging com caminho canônico/prefixo conferidos. Não remove volumes, bancos, redes ou backups anteriores. Não usa prune. O diretório `/srv/kairos/backups/kairos-backup-<runid>.evidence`, modo 0700, permanece com diagnóstico protegido; não imprimir dumps ou erros SQL em mensagens públicas.

Na falha, `private-error.log` (0600) preserva a saída privada do último comando capturado antes da remoção do staging. `result.txt` registra fase, código de saída geral, nome do comando/etapa e seu código de saída quando capturado, sem argumentos. Falhas que não passam pelo wrapper podem deixar esse último campo vazio. Antes de remover o mc, o script salva somente `State.ExitCode`, `State.OOMKilled` e `State.Error` em `private-mc-state.json` (0600). Esse último campo pode conter caminhos privados e não deve ser copiado para mensagens ou Git. Erros de inspeção/cleanup também ficam em arquivos privados 0600.

A tentativa real de 2026-09-09 às 19:03 UTC falhou no comando `timeout` e limpou os temporários, mas a versão então executada descartou o diagnóstico. A repetição com diagnóstico protegido identificou `phase=minio_mirror`, exit code 1, `OOMKilled=false` e erro de permissão ao salvar a configuração em `/root/.mc`. A correção configura um diretório privado gravável em `/tmp` nos dois comandos mc. CPU 0,35, memória 256 MiB, PIDs 64 e `cap-drop ALL` permanecem iguais; não houve ampliação de privilégios. O suporte ao flag foi conferido no [código oficial da versão RELEASE.2025-08-13T08-35-41Z](https://github.com/minio/mc/blob/RELEASE.2025-08-13T08-35-41Z/cmd/flags.go). Repetir backup, restore e no-touch para validar o resultado real.

SIGKILL, perda do daemon ou queda do host podem impedir a limpeza. Inspecionar o runid, label e caminhos antes de remover exclusivamente o container/staging dessa execução. O staging tem dados em claro sob modo 0700/0600; remoção comum não é apagamento criptográfico do disco. A imagem anterior e backups completos anteriores permanecem disponíveis.

Criar o backup não exige rollback produtivo. Para lote de API sem migration, rollback normal reaplica a imagem/configuração anterior, sem restaurar banco e perder atividade posterior. Restaurar dados é uma operação distinta, condicionada ao cenário de falha e à evidência de recuperação.

## Validação

Antes do uso: sintaxe Bash, revisão independente, testes sintéticos do parser/manifests e compatibilidade com o verificador. Sem execução real seguida de restore isolado, considerar este script preparado, com backup/recuperação **ainda não demonstrados**. Não herdar PASS de arquivo anterior.

Na preparação local de 2026-09-09, a sintaxe passou com GNU Bash 5.2.37. Os dois blocos Python embarcados compilaram; oito testes sintéticos do parser passaram, o manifesto estendido foi aceito pelo verificador de restore atual e a projeção de metadados passou com um respondedor Docker simulado. Nenhum desses testes executou Docker, rede ou VPS.

Após acrescentar a retenção de diagnóstico, um harness Bash com operação sintética de saída 42 conferiu: log privado preservado, código 42 registrado, projeção do estado mc preservada, ausência dos valores privados em stdout/stderr e limpeza limitada ao staging esperado. Os comandos Docker, ownership e permissões foram simulados nesse teste; precisam ser confirmados na repetição real. A sintaxe Bash foi novamente validada.

A regressão de configuração do mc foi verificada com fixture de CLI: os dois comandos precisam receber `--config-dir /tmp/kairos-backup-mc`, e a preparação precisa solicitar modo 0700. A fixture aceita o comando corrigido e rejeita a variante sem o flag, reproduzindo a dependência do diretório padrão. Não substitui execução do binário mc real.
