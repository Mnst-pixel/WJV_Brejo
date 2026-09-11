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
