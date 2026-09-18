# Release de produto preparada, ainda inativa

Em 2026-09-11 04:59:44 UTC, a preparação do commit `c12e53a7416902315391d1b8c0a48603cbb1db6e` passou no VPS. O checkout produtivo continua em `f6ac1c3`, com a API do override histórico em `8f341aa`. Nenhum serviço foi trocado e o pointer `active-release` continua ausente.

## Artefatos e motivo

O objetivo deste lote é eliminar ambiguidades antes da janela de manutenção. O bundle Git foi transmitido por SFTP com criação exclusiva, deadlines, verificação de proprietário/permissões e SHA256 após leitura remota. SHA256 do bundle: `5aac0767585f2f9857b5398a69dce6583e86a36d0a5b1f90dfb213297126a21a`. Ele contém o histórico até `8643b7a`; o checkout selecionado é explicitamente **c12e53a**, fonte das imagens.

- Checkout Git limpo: `/opt/kairos/releases/c12e53a7416902315391d1b8c0a48603cbb1db6e`.
- Archive desse commit: SHA256 `0f147ae327c9c26ccb9e84574f763af448a8148ef0c7ad0c94cb7c9b1d81311a`.
- Descriptor protegido: `/opt/kairos/runtime/releases/product-c12e53a7416902315391d1b8c0a48603cbb1db6e`; `manifest.json` SHA256 `39855f1d5ca9e066e60c001f7127a66121c1c685ba12552b25a1221b111abc9e`.
- 14 serviços têm imagens identificadas por SHA256; API, worker, beat e migrate usam o mesmo artefato. API, parser e web têm label OCI do commit c12e53a. IDs completos em [P1-SCOPED-RESTORE.md](P1-SCOPED-RESTORE.md).
- 12 arquivos de ambiente separados por serviço, mais recovery e ACL canônica, foram criados em diretório novo e protegido. A conferência compara em memória cada projeção com a especificação versionada. Nenhum valor aparece nos relatórios.
- Quatro identidades Redis distintas foram preparadas para cache, API/broker, worker/broker e beat/broker. O arquivo mestre anterior permaneceu idêntico. As credenciais novas não estão ativas.

O script exato executado foi preservado em [prepare-product-c12e53a.sh](../scripts/releases/prepare-product-c12e53a.sh), SHA256 `00b213c2143cdbeb0bce245a0f308fcd1d4608f0fb9c8b83647ec8d752c7695e`. É uma operação exclusiva desta release: uma segunda execução deve recusar os destinos existentes. Não é um instalador genérico nem um comando de deploy.

## Testes e evidência

A: sintaxe, clone real do bundle em checkout temporário limpo, archive exato e 61 arquivos de scripts conferidos; 21 testes PASS/7 skips ambientais nos módulos reutilizados. B independente final: 47 PASS/7 skips POSIX, cinco probes de extração e seis de SFTP. Corrigidos antes de executar: identidade dos verificadores de evidência e ausência de deadlines na transferência. Ambos os conjuntos foram repetidos após correções.

Execução POSIX real: criação protegida de checkout/credenciais/descriptor **PASS**; `docker compose config --quiet` **PASS**; Git limpo **PASS**; imagem e revisão OCI **PASS**; no-touch v2 **PASS**, sem exceções de configuração, rede, firewall ou listeners. Nenhuma migration neste lote.

Evidência protegida no VPS: `/opt/kairos/runtime/p0/20260911T042557Z-foundations/release-preparation/result.json`, com logs no mesmo diretório. Baselines: `/opt/kairos/runtime/baselines/prepare-product-c12e53a-{before,after}`. Recibos locais: `modernizacao/evidencias/product-bundle-transfer.json` e `product-release-preparation.json`. A cópia dos verificadores usada nos snapshots saiu do archive fixado; não depende da integridade de uma extração anterior.

## Limites, rollback e próximo gate

`compose config` valida a configuração, mas não testa mounts, conectividade, tráfego ou grants. **O ensaio final dos mounts passou em 05:24:51 UTC**, como registrado abaixo: ACL Redis 0400 para UID999/GID1000, dois arquivos públicos montados com leitura 0644, Caddy UID1000 e PHP/WordPress UID33. Diretórios de credenciais permanecem 0700. Isso não substitui a validação HTTP completa após a transição.

Rollback deste lote: manter os artefatos inativos e continuar usando o conjunto produtivo anterior; não há mudança de banco, serviço ou credencial ativa a desfazer. Não apagar evidências nem executar Compose antigo para desfazer esta preparação. Se um artefato preparado falhar, preservar o diretório e preparar outro destino revisado, sem sobrescrever o anterior.

Faltam manutenção/drenagem, transição do broker, backup fresco imediatamente antes do cutover, grants/migrations produtivos, ativação, smoke público e rollback integral ensaiado. O restore real do candidato já passou, conforme o guia vinculado, mas não substitui esses gates. `PRODUCT_CORE_READY=NO`.

## Validação dos mounts preparada

[verify-product-mounts-c12e53a.sh](../scripts/releases/verify-product-mounts-c12e53a.sh) verifica a identidade Redis na imagem existente, prepara a cópia de runtime 0400 para esse UID/GID e dá leitura aos dois arquivos públicos montados por Caddy/WordPress somente no checkout inativo. Depois testa um Redis descartável com a ACL preparada e credenciais por stdin, Caddy sem root e lint PHP como usuário 33. Toda execução usa socket local, rede `none`, limites e volumes temporários explícitos, com cleanup vinculado a ID/nome/imagem/projeto/run e no-touch v2 final. O plano SQL é apenas preparado; não altera o banco.

Primeira execução em 05:06:40 UTC: **FAIL antes do lock/criação de arquivos/containers**. Dois templates Go do Docker não fechavam o documento JSON. A falha está preservada em `product-mount-verification.json`; não foi convertida em sucesso. Correção adiciona os delimitadores e um teste de regressão para strings escapadas e valores nulos. Os dois templates corrigidos passaram no Docker real em leitura, conforme `mount-projection-readonly.json`.

Script corrigido SHA256 `73bdd4903409800da469039ba5f7d150dc18b228ba7751c2482990d430f57618`; A repetida 27 PASS/5 skips ambientais e Ruff PASS. B anterior invalidada; B final repetida: **50 PASS/5 skips POSIX e 24 probes PASS**, incluindo renderização dos templates reais extraídos do script para que JSON incompleto falhe também nos cenários de cleanup. O script é exclusivo desta release e preserva artefatos em caso de falha.

Segundo ensaio em 05:10:13 UTC: **FAIL**, com cleanup e no-touch v2 **PASS**. Confirmou Redis UID **999**, GID **1000**; criou a ACL de runtime 0400 e ajustou a leitura dos dois arquivos públicos no checkout inativo. O teste parou na interpretação das respostas do Redis, antes de validar Caddy/WordPress. Recibo `product-mount-verification-final.json` preservado. Uma reprodução somente de leitura, sem credencial, confirmou que dois PINGs não autenticados geram duas respostas NOAUTH e duas linhas separadoras vazias.

A correção seguinte ignora somente separadores vazios e mantém a verificação de todas as respostas e negações esperadas. Cada tentativa terá evidência própria e exclusiva. Um arquivo de runtime anterior só pode ser verificado novamente se bytes, UID/GID, modo 0400, ausência de links, arquivo único e diretório 0700 coincidirem; não é sobrescrito. Script SHA256 `c515222ce1c49c11795675553ba0b39a4a88c7a78c8b373cbb67184d91e3074a`. A repetida: 28 PASS/5 skips e Ruff PASS; B final repetida: **51 PASS/5 skips POSIX e 38 probes PASS**, cobrindo reutilização, parser e gates Redis, create/cleanup/gate final. Nova execução real ainda pendente nesta revisão.

A tentativa seguinte em 05:15:08 UTC foi recusada antes do lock e de novas mutações: o comparador anterior, iniciado com `python -I`, havia escrito bytecode no checkout, apesar da variável ambiente que solicitava não o fazer. Esse cache não foi executado novamente nem removido. Recibo `product-mount-verification-v2.json` preserva a recusa. O executor passa a extrair os verificadores em diretório exclusivo de cada tentativa, a partir do archive Git de hash fixo, e a usar `-B` explicitamente no comparador. Essa correção também invalida A/B anteriores para a nova execução.

A/B finais repetidas no script SHA256 `a81e5676b7583e73d6ec10b565b9d2be694cb8570cd902b84a4a577b44cd2bca`: A **28 PASS/5 skips, Ruff PASS**, extração do archive real com 61 arquivos/zero cache; B **51 PASS/5 skips POSIX e 43 probes PASS**, incluindo extração adversarial e imports reais em cópia exclusiva, sem bytecode. Sem achado pendente nesse recorte. Esses testes ainda exigem o ensaio real descrito acima.

Em 05:20:10 UTC, o ensaio passou no Redis real: autenticação das cinco identidades, isolamento cache/broker e negação de comandos administrativos. O conjunto ainda ficou **FAIL** no Caddy, que retornou `operation not permitted` ao iniciar o executável. Cleanup de ambos os containers e no-touch v2 PASS. Causa: o ensaio omitia `NET_BIND_SERVICE`, já exigido pela file capability da imagem e já presente no Compose/teste de integração c12; [P0-UPLOAD-LIVE-TEST.md](P0-UPLOAD-LIVE-TEST.md). Corrigido o ensaio para reproduzir esse bounding set, mantendo UID1000, read-only, no-new-privileges e rede none. Não houve mudança na configuração candidata ou produtiva. Regressão confere a capability do ensaio contra o Compose. A repetida: 29 PASS/5 skips e Ruff PASS; B novamente requerida. Recibo anterior `product-mount-verification-v3.json` permanece FAIL.

B final repetida no script SHA256 `fd65f16e50d4258543953ba43dcb7cfd4c2b96f191e0369e37cbe688426e9b37`: **52 PASS/5 skips POSIX e 46 probes PASS**, incluindo as opções reais dos três containers. A capability extra está limitada ao Caddy; Redis/WordPress continuam sem capabilities. A execução POSIX real ainda será repetida.

## Resultado final dos mounts

**PASS em 2026-09-11 05:24:51 UTC**, executor versionado no commit `2df7c91`, fonte da aplicação e imagens permanecem **c12e53a**. Não houve migration nem deploy. Os testes anteriores FAIL são supersedidos para o gate atual, mas permanecem disponíveis como evidência dos defeitos do ensaio e suas correções.

- Redis com o arquivo de runtime real: cinco autenticações PASS; cache/broker segregados; CONFIG/ACL/FLUSHALL negados aos usuários de aplicação. UID999/GID1000 lidos na imagem pinada, sem suposição de GID999.
- Caddy: configuração candidata lida e validada como UID1000, com somente a capability já prevista no Compose; saída do processo zero.
- WordPress: arquivo do gate legível e sintaticamente válido pelo PHP como UID33; saída zero. Esse teste não é um teste HTTP do WordPress.
- Todos os containers: rede `none`, no-new-privileges, read-only, limites de CPU/RAM/PIDs e volumes temporários explícitos. Cleanup dos três IDs conferidos PASS; no-touch v2 PASS sem exceções.
- Plano SQL das credenciais preparadas: SHA256 `febf307590c532943c4c3b011b9efa114fb355a35974d512f4b6f6bf8360d979`. **PREPARED_ONLY**, nenhuma reconciliação em produção.

Evidência: `/opt/kairos/runtime/p0/20260911T042557Z-foundations/mount-verification-20260911T052434Z-ec2e57aa/result.json`, com plano SQL público e logs protegidos no mesmo diretório; recibo local `product-mount-verification-v4.json`. Baselines `mount-product-20260911T052434Z-ec2e57aa-{before,after}` em `/opt/kairos/runtime/baselines`.

Inventário complementar somente leitura em 05:10:34 UTC: Redis antigo continha três sets de bindings conhecidos e nenhuma fila/lista; o diretório `/configuration` do LocalAI não continha arquivos. O volume anônimo anterior deve ser preservado; a release prevê um volume novo com nome Kairós. Isso não comprova drenagem futura ou ausência de jobs ativos: repetir na manutenção. Evidência `cutover-volume-queue-inventory.json`.
