# P0 — troca controlada da API e rollback

Este lote altera somente a imagem da API. O checkout produtivo geral, worker, frontend, bancos, redes, portas e demais serviços permanecem na revisão anterior. Registrar separadamente `source_revision` da API e `production_checkout`: um único HEAD não representa todos os serviços durante uma implantação incremental.

## Preparação

Usar a exportação Git, imagem e evidências exatas da mesma rodada. `deploy-api-p0.py` exige backup predeploy criado há menos de uma hora, checksum válido, recuperação isolada concluída, limpeza aprovada, ao menos 48 testes da imagem sem skips/falhas e smoke do Gunicorn. Confere que a API produtiva ainda usa a imagem base registrada no build e que o checkout está limpo.

```bash
python3 scripts/deploy-api-p0.py prepare \
  /opt/kairos/runtime/p0/RUN \
  /srv/kairos/backups/kairos-restore-RESTORE.evidence \
  /opt/kairos/runtime/tests/kairos-test-TEST
```

O modo prepare cria `deploy-plan.json` protegido com commit, IDs de imagens, hashes de fonte/configuração, backup e evidências. Não troca containers. A comparação do Compose permite somente imagem, entrypoint e command da API; recusa qualquer outro desvio. Revisar o plano e executar o mesmo comando com `apply` somente para a mudança autorizada.

## Aplicação e comprovação

Um lock exclusivo impede duas execuções simultâneas deste procedimento. `apply` exige igualdade com o plano preparado e gera snapshot anterior. Executa somente `docker compose ... up -d --no-deps --no-build api`, usando `p0-api.override.yaml`. O override gera estáticos com collectstatic e inicia Gunicorn com exec, sem migrations ou bootstraps. Isso atende também imagens antigas usadas em rollback, cujos assets podem ter existido apenas na camada gravável do container removido. Há uma breve indisponibilidade possível durante a substituição desse único container.

Depois: saúde do container, endpoints públicos HTTPS live/ready e CSS administrativo, recusa de login sem CSRF, hashes dos quatro arquivos dentro da API e snapshot/comparador no-touch. Um release somente é aprovado com todos esses gates. `deploy-result.json` registra resultado e imagem observada. Logs de erro ficam em `deploy-private.log`, protegido, sem publicação automática.

O snapshot posterior recebe o baseline anterior e calcula novamente os hashes de todos os arquivos Compose previamente registrados, inclusive overrides que deixaram de estar ativos. Arquivo removido ou hash alterado continua reprovando o gate. Isso distingue a troca autorizada do caminho ativo da alteração de um arquivo preexistente; nenhum hash antigo é reutilizado sem leitura atual.

O script não atualiza o checkout geral nem muda o default do Compose histórico. **Toda recriação posterior da API deve repetir o override e o ID da imagem do plano ativo.** Rodar o Compose histórico sozinho pode reintroduzir a imagem anterior e seus bootstraps. O caminho do plano ativo deve constar no registro de operação; uma evolução posterior pode consolidar essa configuração após revisão.

## Rollback

Falha no apply, saúde, smoke, hash, snapshot posterior ou no-touch provoca tentativa de rollback somente da API. Reaplica o ID anterior com coleta de estáticos e Gunicorn, verifica readiness/CSS e executa novo snapshot/comparador. Nunca modifica recursos alheios para fazer o comparador passar. Falha do próprio rollback fica explícita no resultado; o operador deve inspecionar a imagem observada antes de qualquer retentativa.

Rollback manual do lote, com valores conferidos em `deploy-plan.json`:

```bash
KAIROS_P0_API_IMAGE=sha256:ID_ANTERIOR \
docker compose --project-name kairos --env-file /opt/kairos/secrets/.env \
  -f /opt/kairos/current/infra/compose/compose.yaml \
  -f /opt/kairos/runtime/p0/RUN/source/infra/compose/p0-api.override.yaml \
  up -d --no-deps --no-build api
```

Não restaurar banco para reverter este lote sem migration: isso descartaria atividade posterior. O rollback conserva chaves MFA já ativadas. Voltar à imagem anterior às correções MFA reabre essas vulnerabilidades; a imagem intermediária deste lote já contém as correções. Não repetir `apply` cegamente após perda de conexão ou interrupção: inspecionar plano, resultado, imagens e snapshots. SIGKILL/queda do host podem impedir o rollback automático.

## Testes do procedimento

`python3 scripts/tests/test_deploy_api_p0.py` executa 25 cenários sintéticos sem Docker/rede: preparação, gates de recusa, plano alterado, sucesso, lock e falhas de up/saúde/HTTP/CSS/hash/no-touch/snapshot/rollback. Os mocks não substituem a rodada real. Rodar também Ruff, compilação Python, revisão independente e os testes Linux do comparador. Cada apply real exige evidências próprias; aprovação de testes não equivale a implantação.
