# Restore, migrations e aplicação com papéis separados

O ensaio anterior do candidato `4368891` recuperou backup real e aplicou 14 migrations: 64 tabelas e 86 registros originais preservados, com repetição idempotente. Backup `/srv/kairos/backups/kairos-predeploy-20260911T040123Z-a6436f9b9814.tar.gz.enc`; evidência protegida `/srv/kairos/backups/kairos-restore-20260911T040137Z-2c7c080ac39f.evidence`. Backup/restore/no-touch passaram. Esse resultado ainda usava o proprietário temporário do restore.

Este incremento prepara o ensaio combinado com os papéis segregados. `KAIROS_RESTORE_SCOPED_ROLES=1` é opt-in estrito do script `verify-restore-isolated.sh` e exige imagem SHA256/revisão exatas. O script cria outra cópia, chamada `kairos`, dentro do PostgreSQL descartável sem rede externa. A cópia original `kairos_restore` permanece intacta. Não executa SQL no PostgreSQL produtivo.

O probe exige host loopback, usuário inicial `kairos_restore`, database/owner esperados, run ID sintético e ausência dos quatro papéis. Gera quatro senhas diferentes somente em memória; nenhuma credencial real é reutilizada. Aplica o mesmo SQL de `database-roles.py` antes das migrations, conecta como `kairos_migrator`, migra, compara os registros originais e repete a migration. Reconcilia os grants depois, comprova negações de DDL/escalada/escrita imutável e conecta como `kairos_runtime`.

O smoke sintético percorre a pilha Django/DRF com sessões: criar conteúdo, revisar, aprovação independente, publicar, criar/editar nota vinculada, rejeitar acesso de outro aluno, repetir criação sem duplicar e rejeitar edição desatualizada. Todos os registros sintéticos, sessões e auditoria ficam numa transação revertida; os registros restaurados são comparados novamente. As sessões do probe são autenticadas pela fixture: isso **não testa senha, desafio MFA, edge HTTP ou navegador**. Esses gates continuam separados.

Correções necessárias:

- Reconciliação anterior às migrations não pode exigir a existência de tabelas P3/P6 futuras. Revogações de imutabilidade são condicionais à existência, dentro da mesma transação. Tabelas novas continuam sem grant runtime até a reconciliação posterior.
- A transição editorial bloqueia somente `ContentWorkflow` com `FOR UPDATE OF`; bloquear a versão imutável via join exigia privilégio UPDATE indevido. O conteúdo pai já é bloqueado para serializar transições concorrentes.
- A fixture PostgreSQL de privilégios passa a iniciar em `core.0001`, migrar como migrator e executar a API com runtime, em vez de criar todo o schema inicialmente como superuser.
- Reconciliação e restore fixam `/usr/bin/docker --host unix:///var/run/docker.sock` com ambiente mínimo, inclusive nas chamadas temporizadas. `DOCKER_HOST`, contextos, configurações/plugins e credenciais herdados não podem redirecionar criação, inspeção ou cleanup. O teste das funções shell usa um executável inofensivo e ambiente contaminado.

Arquivos: `scripts/database-roles.py`, `restore-migration-probe.py`, `restore-scoped-roles.py`, `scoped-runtime-probe.py`, `verify-restore-isolated.sh`, testes de grants/restore e `apps/api/core/content_workflow.py`. Sem migration nova.

Validação local: 15 contratos de SQL/guardas PASS e Ruff PASS. API: **570 PASS/30 skips explícitos**, 123,25 s; E2E completo Chromium: **PASS**, 39,12 s. A tentativa de executar toda a suíte operacional no Windows teve 155 PASS/39 skips e 11 falhas por ausência do executável Bash; esses contratos devem rodar no Linux, não foram declarados aprovados localmente. Revisão B, imagem Linux e restore combinado ainda em fechamento; não declarar o ensaio combinado operacional antes das evidências abaixo.

Rollback deste incremento não implantado: reverter seu commit de código, preservando os recibos e backups. O ensaio não ativa papéis em produção. A eventual troca produtiva exige manutenção, backup fresco, plano congelado, grants antes/depois, smoke integral e rollback da release; o sucesso deste probe sozinho não autoriza afirmar P1 completo.

## Primeira imagem e ensaio combinado

Commit `8f351f731c8ad7a757acea2ab38fbdac044499af`, fonte SHA256 `9c6d1f235445331d1da2a0aed5c4f173f00ba691cbc25b74288577c94c569af4`. API `sha256:88c23464b556c0b3875de043c08d99cc7f9aee7b0eb2bdbbbea80bbc0a5d323c`; parser `sha256:d62526c209c906d1dd72d7aced06b8c76ddeb0bc213a0bb0f4b57228fe411f0d`. Linux isolado: **599 API PASS/1 skip browser**, 188,01 s; **215 operações PASS/3 skips Git**, 27,72 s; mais **13 contratos Git PASS**. Inclui schema antigo → migrator → grants → API runtime, e wrappers shell executados com ambiente Docker contaminado. PHP/WordPress12→1 nonce/Caddy/Gunicorn PASS. Build/integração/no-touch exit0, zero recursos preexistentes modificados. Execução `/opt/kairos/runtime/p0/20260911T041627Z-foundations`, evidência `/opt/kairos/runtime/tests/kairos-test-20260911T041722Z-75691adc2afa`.

B final desse commit: 16 contratos PASS/9 skips de ambiente; 36 workflow/editorial PASS/3 skips PostgreSQL. Sem achado de código remanescente. Scan: 17 valores ativos versus 416 arquivos versionados, zero correspondências.

Ensaio com backup novo `/srv/kairos/backups/kairos-predeploy-20260911T042200Z-03e3aac5eccf.tar.gz.enc`: migrations/grants/API passaram na cópia real, mas o recibo recebeu quatro logs JSON de negações esperadas antes do documento final. O parser estrito corretamente recusou o arquivo. **Resultado integral FAIL**; não chegou à conclusão MariaDB/MinIO. Cleanup/no-touch PASS. Evidência preservada `/srv/kairos/backups/kairos-restore-20260911T042214Z-8a215a0ebcaa.evidence`.

Correção: `emit_report` descarta a saída de diagnóstico durante o probe e emite exatamente um documento JSON somente depois do retorno bem-sucedido. Exceção não produz recibo parcial. Dois testes permanentes cobrem logs misturados e falso PASS parcial. Repetição A/B e restore integral são obrigatórios após essa correção.

## Repetição final aprovada

Commit **`c12e53a7416902315391d1b8c0a48603cbb1db6e`**, fonte Git SHA256 **`0f147ae327c9c26ccb9e84574f763af448a8148ef0c7ad0c94cb7c9b1d81311a`**. API **`sha256:042d06a4cdc875a73150415d97ff34305bfb1b7f772deed9a4a5d1eff1cb2455`**, parser `sha256:1e1592bd7fa1ab9183c9ce9bef751d697ac52e906da8a25e65976df073c5168c`. Linux: **599 API PASS/1 browser skip**, 188,58 s; **217 operações PASS/3 Git skips**, 27,77 s; **13 contratos Git PASS**. WordPress/MariaDB 12 concorrentes/1 nonce, PHP/Caddy/Gunicorn/inventário e cleanup PASS. Execução `/opt/kairos/runtime/p0/20260911T042557Z-foundations`, evidência `/opt/kairos/runtime/tests/kairos-test-20260911T042642Z-f2c586542ec2`.

B após a correção: **18 contratos PASS/9 skips de ambiente**, **36 workflow PASS/3 PostgreSQL skips**, mais cinco probes independentes de logging, restauração de streams e falhas sem recibo. Nenhum finding remanescente no recorte.

**Restore integral PASS às 04:34 UTC de 2026-09-11**. Backup novo `/srv/kairos/backups/kairos-predeploy-20260911T043307Z-8ce27bbc4683.tar.gz.enc`; evidência `/srv/kairos/backups/kairos-restore-20260911T043321Z-df1fcf2d739c.evidence`. Checksum, manifesto, arquivos, PostgreSQL, MariaDB e MinIO passaram; recursos temporários removidos. **14 migrations como migrator**, **64 tabelas/86 registros originais preservados**, repetição idempotente; grants restritos e API editorial/notas como runtime sem superuser PASS. Isolamento entre alunos, replay e versão desatualizada PASS, todos os registros sintéticos revertidos. O restore foi chamado com `DOCKER_HOST`, `DOCKER_CONTEXT` e `DOCKER_CONFIG` sintéticos inválidos, comprovando o uso do socket fixo.

Recibos locais: `modernizacao/evidencias/p0p2-candidate-20260911T042557Z.json`, `p3-scoped-migration-rehearsal-final-20260911.json` e `strict-scoped-evidence.json`. A comparação suplementar **v2, sem qualquer exceção**, aprovou tanto os snapshots da imagem quanto os do restore: nenhuma alteração de configuração, rede, firewall ou listener autorizada/observada.

**Não houve deploy nem ativação de grants produtivos.** Este gate de ensaio está fechado; ainda faltam coordenador de manutenção/drenagem/cutover, compatibilidade/rollback integral, smoke público e rotina operacional ativada.

## Imagem web do mesmo commit

Next.js **`sha256:651bf1767d3a6d90924e212bf7579dadd8196e53a2e7c20c42f6a02d7cef6824`**, label OCI **`c12e53a7416902315391d1b8c0a48603cbb1db6e`**. Build pelo Dockerfile versionado, com a árvore web comparada ao archive Git fixado acima e base Node local `sha256:244cc2b53f46f9e876304391d17682b0ddae9ac33491f4857e25e35a36ba7995`. Sem pull ou alteração da base; limite de build 1536 MiB/CPU0.

Smoke em container descartável uid10001, rede none, filesystem somente leitura, sem capabilities e com 384 MiB: health/login/CSS **200**, área privada **307 para /app/entrar** com API indisponível, sem X-Powered-By. Cleanup e comparador **v2 sem exceções PASS**. Execução `/opt/kairos/runtime/p0/20260911T042557Z-foundations/web-build-20260911T044017Z-c50602773d9a`; recibo local `modernizacao/evidencias/product-web-build-c12e53a.json`. Manifesto sem mudanças `cdf36715bb7ebff3be80c2afe54f782b88192f352ed2f1452fe916e0621e3706`.

A operação preparada foi revisada B antes de executar: cinco cenários de cleanup e seis de smoke, além de ambiente Python contaminado. Foram corrigidos comparador legado, cleanup de resposta perdida, falso positivo de redirecionamento, vínculo independente archive/commit e `PYTHONOPTIMIZE`. Helper operacional revisado SHA256 `a0bcee1b88199ccd91efe28df9849b539d97d6f7d005248628bd8af7a1c7b812`; revisão local não foi usada como substituto do build/smoke real. **API, parser e web candidatos agora correspondem ao mesmo commit; ainda não implantados.**
