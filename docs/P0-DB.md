# P0 — PostgreSQL com papéis separados

## Alteração e motivo

`scripts/database-roles.py` prepara uma política reprodutível para o banco `kairos` no container `kairos-postgres-1`. API e worker deixam de receber o superusuário herdado. Segredos internos são gerados por `release-secrets.py`, não pelo banco nem pelo aplicativo. O arquivo recovery.env fica protegido, não é montado nos serviços de aplicação e não entra no Git.

| Identidade | Acesso |
|---|---|
| kairos_runtime | CONNECT/USAGE; DML nas tabelas da aplicação; sem CREATE de schema/tabela/database, sem membros herdados, sem superuser/createrole/bypassrls/replication |
| kairos_worker | SELECT/UPDATE de FileAsset e IngestionRun; INSERT de AuditLog; SELECT(id)/UPDATE(updated_at) em User para o lock; sem leitura de password/MFA |
| kairos_migrator | Dono do schema public e das relações core_*, auth_* e django_*; DDL de migrations; sem superuser/createdb/createrole |
| kairos_backup | SELECT nas tabelas/sequências, CONNECT/USAGE; sessão inicia read-only, sem DML/DDL |

Runtime não modifica/apaga auditoria, decisões e versões jurídicas/prompt imutáveis, nem escreve em django_migrations. SourceDocumentVersion aceita somente mudanças de estado/atores/timestamps pelo runtime. Aprovação continua sujeita ao workflow e RBAC da aplicação. As permissões de tabela/coluna e memberships antigos dos papéis gerenciados são reconciliados; NOINHERIT sozinho não impede SET ROLE. PUBLIC perde permissões no banco/schema/tabelas/sequências, pois grants herdados por PUBLIC poderiam burlar as restrições.

O lock de usuário no worker requer UPDATE em pelo menos uma coluna além de SELECT. A coluna updated_at permite esse lock sem conceder leitura de credenciais; os caminhos worker carregam User.only('id'). Esse requisito está descrito na [documentação PostgreSQL 17 de privilégios](https://www.postgresql.org/docs/17/ddl-priv.html).

## Plano e aplicação

Entrada permitida: arquivo chamado recovery.env, absoluto, regular root:root 0600 dentro de `/opt/kairos/secrets`. Banco e nomes de papéis são fixos; senhas internas seguem o token_hex(48) criado pela projeção e precisam ser distintas. Parser nunca executa dotenv nem comandos. Plano inclui apenas identidades, contrato e SHA-256 do SQL; não imprime SQL ou valores privados.

```bash
python3 /opt/kairos/current/scripts/database-roles.py plan --recovery /opt/kairos/secrets/RELEASE/recovery.env
python3 /opt/kairos/current/scripts/database-roles.py apply --recovery /opt/kairos/secrets/RELEASE/recovery.env --expected-plan-hash HASH_DO_PLANO
```

Aplicação é explícita e exige hash correspondente; credencial/contrato alterado invalida o plano. A CLI adquire o lock operacional compartilhado, confere container/labels Kairós e envia SQL apenas pelo stdin a docker exec/psql. Não há password em argumentos, stdout ou logs de diagnóstico devolvidos. A sessão administrativa usa o socket local do container, como os procedimentos anteriores; HBA que exigir senha deve ser tratado operacionalmente antes da execução, sem expor credenciais no comando.

Todo DDL/grant está numa transação com ON_ERROR_STOP, lock_timeout e statement_timeout. A sessão desabilita log_statement e reduz logging de erro antes de enviar passwords; auditoria externa de SQL, caso habilitada no futuro, precisa ser avaliada antes de provisionar secrets. O retorno APPLIED comprova commit do SQL, não substitui testes com as quatro identidades.

## Migrations, extensões e reconciliação

Extensões e seus objetos não têm ownership transferido: a seleção exclui membros de extensão via pg_depend. A extensão vector já instalada permanece sob proprietário anterior. Uma migration que introduza extensão privilegiada deve ter a extensão provisionada separadamente pelo operador; não elevar o migrator a superuser para contornar isso.

Ordem de implantação: backup/restore comprovado → plano/ensaio PostgreSQL isolado → aplicação dos papéis → migration com migrate.env → reconciliação dos grants com o mesmo recovery.env/plano → troca coordenada API/worker → smoke autenticado por papel. Não executar applications entre migration e reconciliação. Tabelas novas não ganham DML de runtime/worker automaticamente; falham fechadas até a reconciliação. Backup recebe SELECT por default privilege do migrator.

O script não contém migration Django: muda ownership/grants, sem alterar dados de negócio. `pg_dump` futuro deve autenticar como kairos_backup e a recuperação deve usar o operador de restore. Restore em ambiente novo precisa criar papéis e reconciliar ownership/grants após restaurar os objetos; o ensaio anterior de dados não comprova automaticamente recuperação dos grants novos. Não trocar o restore isolado para runtime/migrator de produção.

MariaDB/WordPress permanecem fora deste script: confirmar separadamente MARIADB_USER com acesso somente ao banco WordPress. PostgreSQL isolado não equivale a aprovação de MariaDB.

## Testes e limites

Nove testes sintéticos passaram: plano determinístico/redigido, nome/banco/senha inválidos, bloqueio de mudança de plano, container estrangeiro, SQL por stdin, erro sem vazamento, limites worker, preservação de extensões e fail-closed de tabelas novas. Ruff passou. Não houve VPS nem PostgreSQL real neste sublote.

Gate integrado obrigatório: testar login com cada role; runtime DML permitido/DDL e SET ROLE negados; worker processa upload e grava auditoria mas SELECT password/mfa negados; backup pg_dump funciona e UPDATE falha; migrator forward/back funciona; extensão vector permanece; após reconciliação novo modelo fica acessível; catálogo/grants repetidos idempotentes. Fazer backup e restore reais com a nova topologia antes de declarar P0 banco concluído.

## Rollback

Guardar a projeção protegida anterior e inventário de owner/grants antes de aplicar. Falha antes de COMMIT desfaz alterações; timeout/desconexão pode ter resultado incerto e exige inspeção, sem assumir rollback. Reconciliar novamente com o mesmo recovery.env é idempotente. Para desfazer uma rotação interna, reaplicar plano gerado a partir da projeção anterior, sem apagar papéis, tabelas ou dados. Reverter a aplicação para credencial superuser histórica reabre o risco; preferir rollback de imagem mantendo papéis/grants restritos compatíveis. Ownership/grants anteriores, quando necessários, exigem um plano explícito revisado; não há DROP ROLE automático.

## Testes reais dos quatro papéis no PostgreSQL isolado

`scripts/tests/test_database_roles_integration.py` exige opt-in `KAIROS_TEST_DB_ROLES=1` dentro da rede descartável do runner de integração. O host é fixo `kairos-test-postgres`, bootstrap `kairos_test`, porta 5432, senha sintética e run ID emitidos pelo runner. O fixture recusa banco `kairos` ou papéis já existentes antes de provisionar. Bancos e papéis recebem marcador da execução; a limpeza verifica esse marcador antes de remover apenas recursos criados no teste.

Os sete testes executam SQL real via psycopg e migrations reais com os modelos/configuração de produção e adapters externos desativados. Cobrem worker com lock de `User.id` sem senha/MFA, DML de runtime, negação de UPDATE/DELETE dos registros imutáveis, privilégios de backup mesmo retirando o default read-only, migrations pelo migrator, novas tabelas sem grant de runtime até reconciliação, remoção de memberships herdadas e preservação do proprietário da extensão vector. Quando os binários estão presentes, `pg_dump` autentica como backup e `pg_restore` recupera os dados sintéticos em outro banco marcado, verificando contagens e constraints.

Execução local sem opt-in: **7 skipped**, explicitamente sem alegação de SQL real. Ruff passou. A execução real e sua evidência pertencem ao runner Linux isolado; nenhum endpoint de produção é configurável nesses testes. Opt-in sem psycopg é falha, não sucesso por skip.
