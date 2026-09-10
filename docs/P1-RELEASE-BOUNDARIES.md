# P1 — execução local de release e configuração recuperável

## Correções verificáveis

`release-manifest.py`, `kairos-compose.py` e `backup-postgres.py` executam Docker com `--host unix:///var/run/docker.sock`. Variáveis herdadas `DOCKER_*`, `COMPOSE_*`, `GIT_*`, `KAIROS_IMAGE_*` e `KAIROS_SECRETS_*` são removidas antes de Git/Docker; somente o descriptor validado recompõe variáveis públicas do Compose. Assim `DOCKER_HOST`, contexto/TLS/config alternativo ou `GIT_DIR` não redirecionam silenciosamente uma operação para outro daemon/checkout. A opção explícita de socket também prevalece sobre o contexto salvo no config Docker do operador.

O wrapper adquire `.operation.lock` antes de ler ponteiro, HEAD, hashes e construir o comando de alteração. Mantém release.env exato, checkout limpo, commit correspondente, imagens imutáveis e serviços explícitos. Migrations continuam em modo próprio, sem comando arbitrário. Caminhos de namespace rejeitam links simbólicos no arquivo e nos diretórios intermediários.

`release-secrets.py` recusa nomes de serviço/variável que poderiam produzir arquivos fora do diretório ou injetar linhas. Exige origem root0600 regular, diretório pai root0700 e destino novo sem symlink. Gera `KAIROS_PROXY_TOKEN` independente, projetado somente nos serviços declarados pela configuração. Nenhum valor é impresso.

## Backup do PostgreSQL

Em release ativo, o helper usa exclusivamente `kairos_backup`, validando ponteiro/manifest root0600, namespace de credenciais e identidade do container. Senha chega por stdin, nunca argv; stderr do pg_dump não é encaminhado. Não exige checkout saudável para permitir recuperação de um incidente no código.

Antes do primeiro corte, a ausência de active-release só permite o backup histórico quando a inspeção da API implantada comprova projeto Kairós, serviço api, ausência da marca `managed=release` e exatamente um override P0 existente dentro de `/opt/kairos/runtime/p0`. Ausência de ponteiro sozinha, symlink quebrado ou serviço de outro projeto falham fechados. Depois do corte não existe fallback silencioso para o usuário privilegiado.

## Captura de configuração

`capture-release-config.py` aceita apenas staging payload root0700 sob `/srv/kairos/backups`. Valida todas as fontes antes da primeira cópia, confere release.env contra manifesto e cria artefatos root0600 sem sobrescrever caminhos existentes. Inclui manifesto, ponteiro, ambiente público, ambientes por serviço existentes, recovery obrigatório e `redis.acl` canônico obrigatório. A cópia operacional `runtime/redis.acl` pertencente ao UID Redis é regenerada do canônico no restore.

O payload ainda contém segredos em texto no staging protegido até a criptografia e limpeza realizadas pelo fluxo de backup. Não publicar/copiar esse diretório como evidência. Esta mudança não substitui o restore isolado, a verificação do arquivo criptografado nem o no-touch comparator.

## Evidência e rollback

Testes incluem repositório Git temporário real, mudança real de commit, injeção de GIT_DIR/DOCKER_HOST, divergência release.env, serviço arbitrário, ausência de ponteiro, container estrangeiro e projeção inválida. Casos de permissões e symlink exigem Linux executado como root em fixture temporária; não simulam prova de chmod no Windows. Nenhum teste usa Docker produtivo ou credenciais reais.

Rollback reverte somente scripts/configuração versionados ao commit aprovado e preserva os artefatos protegidos anteriores. Nunca restaurar fallback implícito ou variável Docker herdada para contornar validação. O operador deve restaurar descriptor e checkout correspondentes, mantendo socket local explícito.
