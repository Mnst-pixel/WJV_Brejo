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

`compose config` valida a configuração, mas não testa mounts, conectividade, tráfego, grants ou permissões de leitura pelo UID do container. A ACL Redis destinada ao bind de runtime **ainda não foi criada**: a identidade deve ser conferida na imagem pinada e a leitura testada de forma isolada. O checkout novo tem proteção restrita e ainda precisa de uma política explícita de permissões para os dois bind mounts de código.

Rollback deste lote: manter os artefatos inativos e continuar usando o conjunto produtivo anterior; não há mudança de banco, serviço ou credencial ativa a desfazer. Não apagar evidências nem executar Compose antigo para desfazer esta preparação. Se um artefato preparado falhar, preservar o diretório e preparar outro destino revisado, sem sobrescrever o anterior.

Faltam manutenção/drenagem, transição do broker, backup fresco imediatamente antes do cutover, grants/migrations produtivos, ativação, smoke público e rollback integral ensaiado. O restore real do candidato já passou, conforme o guia vinculado, mas não substitui esses gates. `PRODUCT_CORE_READY=NO`.

## Validação dos mounts preparada

[verify-product-mounts-c12e53a.sh](../scripts/releases/verify-product-mounts-c12e53a.sh) verifica a identidade Redis na imagem existente, prepara a cópia de runtime 0400 para esse UID/GID e dá leitura aos dois arquivos públicos montados por Caddy/WordPress somente no checkout inativo. Depois testa um Redis descartável com a ACL preparada e credenciais por stdin, Caddy sem root e lint PHP como usuário 33. Toda execução usa socket local, rede `none`, limites e volumes temporários explícitos, com cleanup vinculado a ID/nome/imagem/projeto/run e no-touch v2 final. O plano SQL é apenas preparado; não altera o banco.

Primeira execução em 05:06:40 UTC: **FAIL antes do lock/criação de arquivos/containers**. Dois templates Go do Docker não fechavam o documento JSON. A falha está preservada em `product-mount-verification.json`; não foi convertida em sucesso. Correção adiciona os delimitadores e um teste de regressão para strings escapadas e valores nulos. Os dois templates corrigidos passaram no Docker real em leitura, conforme `mount-projection-readonly.json`.

Script corrigido SHA256 `73bdd4903409800da469039ba5f7d150dc18b228ba7751c2482990d430f57618`; A repetida 27 PASS/5 skips ambientais e Ruff PASS. B anterior invalidada; B final repetida: **50 PASS/5 skips POSIX e 24 probes PASS**, incluindo renderização dos templates reais extraídos do script para que JSON incompleto falhe também nos cenários de cleanup. O script é exclusivo desta release e preserva artefatos em caso de falha.
