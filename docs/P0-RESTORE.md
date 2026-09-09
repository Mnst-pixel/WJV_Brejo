# P0 — verificação isolada de recuperação

Este procedimento substitui o uso do verificador histórico para o gate de recuperação do lote P0. Não altera o backup original, os bancos produtivos ou o Compose implantado. `scripts/verify-restore.sh` continua existente, mas não deve ser utilizado para comprovar isolamento: ele cria bancos e bucket nos serviços produtivos.

## Preparação e execução controlada

O operador deve registrar HEAD, imagens efetivas, disco/RAM disponíveis e snapshot no-touch imediatamente antes. O script cria somente recursos `kairos-restore-<timestamp>-<random>-…`, identificados por label do run. Não utiliza Compose, portas publicadas, redes produtivas, credenciais de bancos produtivos ou bootstrap da aplicação. Não executar simultaneamente com outro ensaio ou backup; reservar pelo menos 1 GiB de RAM disponível e o espaço exigido pelo script.

Pré-requisitos já esperados no VPS: Bash, Python 3 padrão, Docker, OpenSSL e utilitários GNU. Não há instalação nem pull. Imagens locais padrão: `pgvector/pgvector:0.8.6-pg17-trixie`, `mariadb:12.3.3`, `kairos-minio` e `minio/mc:RELEASE.2025-08-13T08-35-41Z`. O script resolve essas referências para IDs imutáveis antes de criar containers. Se necessário, informar IDs já verificados através de `KAIROS_RESTORE_PG_IMAGE`, `KAIROS_RESTORE_MY_IMAGE`, `KAIROS_RESTORE_MINIO_IMAGE` e `KAIROS_RESTORE_MC_IMAGE`.

Disponibilizar, fora do Git, um arquivo root:root 0600 contendo **somente** a passphrase de criptografia do backup, com newline final opcional. Não passar `.env` ou a própria passphrase como argumento. Não usar shell tracing. A passphrase não é devolvida nem registrada pelo script; cabe ao operador remover o arquivo temporário de passphrase após o ensaio, caso tenha sido criado para essa finalidade.

```bash
sudo bash scripts/verify-restore-isolated.sh \
  /srv/kairos/backups/kairos-AAAAMMDDTHHMMSSZ.tar.gz.enc \
  /opt/kairos/secrets/restore-passphrase
```

Substituir o nome pelo arquivo explicitamente aprovado. O script não escolhe `--latest`. O limite de extração padrão é 2 GiB por TAR; `KAIROS_RESTORE_MAX_BYTES` permite de 1 MiB a 16 GiB. Exige espaço livre de quatro vezes esse limite mais 1 GiB. O limite e a política conservadora de recusar links, arquivos especiais, nomes de controle/traversal e duplicações podem rejeitar um backup legítimo; nesse caso registrar a causa e revisar o formato, sem contornar silenciosamente a validação.

## O que é efetivamente conferido

- Checksum externo exato, descriptografia e manifesto interno cobrindo todos os arquivos regulares.
- Extração completa de WordPress e Hermes para diretórios temporários protegidos; presença da configuração WordPress, arquivos Hermes, configuração secreta não vazia e commit de 40 caracteres. A extração preserva bytes, mas normaliza permissões para 0700/0600 neste ensaio.
- Restore real de PostgreSQL em volume/container novos, sem rede; falha em erro de restauração, usuários/migrations ausentes ou constraints/índices inválidos. Registra somente contagens agregadas. `--no-owner --no-privileges` isola o ensaio: owners/grants originais não são validados.
- Restore real de MariaDB em volume/container novos, sem rede; `mariadb-check` e contagens positivas de opções/usuários WordPress.
- Restore de objetos em MinIO novo, acessível apenas em rede interna exclusiva; download de retorno e comparação exata de caminhos relativos, tamanhos e SHA-256. Zero objetos é permitido somente quando o componente arquivado também está vazio.
- Containers limitados a 0,5 CPU, 640 MiB sem swap e 128 PIDs, sem Docker socket; bancos são parados sequencialmente. O armazenamento temporário continua sujeito à capacidade de disco do host, sem quota Docker dedicada.

Credenciais dos serviços temporários são novas. SQL, logs internos, nomes de objetos e conteúdos privados não aparecem no relatório nem no Git. Resultados ficam em `/srv/kairos/backups/kairos-restore-<runid>.evidence`, protegidos; contêm IDs de imagens, recursos e contagens. Logs privados transitórios são descartados pela limpeza, inclusive na falha.

## Gates e interpretação

`KAIROS_RESTORE_ISOLATED=PASS scope=archived_data` requer todas as etapas acima e a remoção bem-sucedida dos recursos criados. Qualquer erro ou timeout retorna código não zero. Isso comprova recuperação dos dados **contidos naquele arquivo**.

Ainda não comprova: consistência de um mesmo instante entre bancos e arquivos, equivalência com contagens originais ausentes no manifesto histórico, owners/grants, versões/policies de objetos, execução da aplicação, configuração externa não arquivada, recuperação fora do VPS ou comparação no-touch. Esses limites aparecem também na evidência. O gate de deploy continua exigindo comparação no-touch antes/depois e verificação independente; não declarar plataforma operacional somente com este resultado.

O script não executa inferência, envia e-mails, publica conteúdo, roda migrations/bootstraps da API nem inicia WordPress/Hermes contra dados recuperados. Uma homologação funcional posterior deve permanecer isolada e usar credenciais e destinos externos próprios.

## Falha, limpeza e rollback

O trap remove exclusivamente containers/volumes/redes registrados e cujo label corresponde ao run. Não utiliza `prune`, `compose down`, wildcard de remoção Docker ou recursos produtivos. O diretório transitório é removido somente após conferir seu caminho canônico e prefixo exclusivo; a evidência permanece. Recursos que falharam na limpeza exigem inspeção manual por ID/nome e label, nunca remoção ampla.

SIGKILL, queda de energia ou perda do daemon podem impedir o trap. Nesse caso usar o runid da evidência, conferir labels e montagens de cada recurso e remover somente esses recursos temporários. Descriptografados permanecem protegidos por modo 0700/0600 até essa limpeza. Remoção normal não equivale a apagamento criptográfico do disco.

Este ensaio não exige rollback produtivo. Para o lote API sem migration, rollback deve reaplicar a imagem/configuração anterior somente aos serviços alterados, sem restaurar o banco e sem executar bootstraps. A preparação e verificação desse deploy são tarefas separadas.

## Validação antes de uso

O comparador `scripts/compare-vps-snapshots.sh` agora exige todos os inventários e filtra recursos Kairós pelo nome em ambos os snapshots. Isso aceita uma baseline que já contém a plataforma e impede que uma imagem cujo nome contenha Kairós esconda alterações em outro projeto. Configurações, listeners, imagens/volumes anteriores e regras permanecem sujeitos aos gates conservadores existentes. Executar `python3 -m unittest discover -s scripts/tests -v` em Linux com Bash e utilitários GNU; são sete cenários, incluindo inventários ausentes e mudanças alheias. O runtime Git mínimo do Windows não inclui `realpath`, portanto não substitui essa execução Linux.

Executar `bash -n scripts/verify-restore-isolated.sh` e revisão independente. Sem execução real em containers, considerar o script preparado, com restauração **ainda não demonstrada**. A primeira execução controlada deve produzir evidência de todas as etapas e no-touch; corrigir qualquer falha e repetir integralmente antes do deploy.

Na preparação local de 2026-09-09, a análise de sintaxe passou com GNU Bash 5.2.37 (disponível como `sh.exe` no runtime Git). O helper Python compilou e passou por 18 verificações com fixtures temporárias: extração válida, traversal, caminho absoluto, barra invertida, caractere de controle, symlink, hardlink, FIFO, duplicação, limite de tamanho, checksum correto/incorreto, cobertura do manifesto, objetos vazios, objetos iguais e divergentes. Essas verificações não executaram Docker, rede ou VPS e não substituem o restore real.
