# Manutenção e observação do broker

Este gate prepara a transição da infraestrutura legada para a release de produto. Não ativa manutenção, troca imagens ou aplica migrations. A aplicação candidata continua em `c12e53a`; `PRODUCT_CORE_READY=NO`.

## Observação limitada

`scripts/legacy_drain_probe.py` consulta somente `active`, `reserved` e `scheduled` de uma identidade Celery exata, além do inventário Redis DB0 legado. Não imprime argumentos, nomes de filas, credenciais ou mensagens de exceção. Respostas ausentes/ambíguas, chaves desconhecidas, tipos reservados incorretos ou qualquer trabalho pendente impedem um resultado vazio. O inventário termina em 512 páginas/256 chaves; sockets têm timeout de três segundos e o processo POSIX termina obrigatoriamente após 20 segundos. Redis aceita somente o endpoint legado fixo, sem querystring/fragmento ou opções que alterem DB/timeouts.

Esse RPC pode criar metadados transitórios de resposta do Celery. Não remove jobs nem modifica conteúdo educacional. O resultado sempre contém `producers_stopped=false` e `drain_confirmed=false`: uma fotografia vazia com tráfego aberto não prova drenagem. Na transição, bloquear escritas, parar produtores identificados, executar warm shutdown controlado, conferir filas e tarefas novamente e preservar o broker anterior. Uma falha de observação não autoriza troca de prefixo ou descarte de filas.

Verificação A: **46 testes PASS**, Ruff PASS. B independente: **46 testes e 38 probes PASS**, incluindo os três defeitos inicialmente encontrados e corrigidos: querystrings capazes de alterar conexões, páginas SCAN vazias sem limite e nomes reservados com tipo inesperado. SHA256 final do probe: `9f89483be7839eda5b65dedee183a081392a10a04328d7933375a6c65a8e149b`.

Execução real em **2026-09-11 05:47:38 UTC**: identidade/imagem/labels da API e do worker legados conferidas; `active=0`, `reserved=0`, `scheduled=0`; três sets conhecidos, nenhuma entrada em filas, nenhuma mensagem não reconhecida e nenhuma chave desconhecida. Resultado **EMPTY_AT_OBSERVATION**, não drenagem. Deadline foi instalado no processo real; sua expiração forçada não foi ensaiada. Recibo local: `modernizacao/evidencias/legacy-worker-observation-final-20260911.json`.

O primeiro wrapper de transporte falhou em compilação Python, antes de executar qualquer comando Docker; recibo `legacy-worker-observation-20260911.json` preservado como FAIL. Corrigido o framing de newline do wrapper, sem alterar o probe revisado. Nenhum serviço foi parado, nenhuma credencial/banco foi alterado. Rollback deste lote: deixar de executar o observador; não há estado persistente de aplicação a desfazer.

## Resposta HTTP de manutenção

O arquivo `infra/caddy/maintenance.Caddyfile` prepara uma resposta textual 503 para todas as rotas e métodos, com `Retry-After: 60`, cache privado/no-store, sem upstream, cookies, redirects ou conteúdo dinâmico. O ensaio `scripts/verify-maintenance-isolated.py` usa imagens pinadas, containers descartáveis sem portas publicadas, rede `none` e cliente que compartilha somente o namespace desse servidor de teste. Verifica 36 combinações de rota/método antes e depois de reiniciar exclusivamente esse componente temporário.

As verificações de HTTP usam requisições reais e rejeitam respostas 200, cabeçalhos ausentes, disclosure, cookies, redirects e reflexão de conteúdo. Cleanup exige ID, nome, imagem e labels de projeto/run; snapshots completos e comparador no-touch v2 não admitem exceções. A reinicialização do componente de manutenção **não comprova rollback integral da release**. Ensaio real, ativação pública, bloqueio efetivo de escritas, drenagem final e rollback integral ainda pendentes nesta revisão.
