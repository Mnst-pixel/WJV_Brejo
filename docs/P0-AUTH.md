# P0 — MFA, CSRF e isolamento de tentativas

Fonte primária: Relatório de Auditoria Integral do Kairós, consolidado em 2026-09-09. Este lote trata o segredo MFA exposto por pré-sessão antiga, tentativas ilimitadas de OTP, login sem CSRF e alteração do vínculo de tentativa. Não conclui todos os achados P0 nem a modernização P1–P9.

## Regra Zero e escopo

Revalidação de 2026-09-09 às 18:22:59 UTC: HEAD produtivo e origin/main em `f6ac1c3c510a4f442b9101d599e6598fe8428ca0`, checkout limpo; sem diferenças nos containers, schema e contagens comparadas com a auditoria. PostgreSQL com 72 tabelas; 3 usuários ativos administrativos, dos quais 2 com MFA. Disco livre: 52.889.329.664 bytes; RAM disponível: 4.767.490.048 bytes. Timers Kairós ativos. Backup de 06:28:29 UTC com 66.790.512 bytes e checksum válido; checksum sozinho não demonstra recuperação.

Branch: `astra/kairos-p0-seguranca`. Não há migration, alteração de dependências, bootstrap, mudança de senha/secret produtivo ou mudança de papéis neste lote. O código permanece compatível com as chaves MFA ativas existentes. A rota autenticada correta é `/api/auth/me`.

## Comportamento

- Cadastro MFA dura 300 segundos, vinculado à prova de senha, versão de sessão e usuário administrativo ativo. Cada nova entrada com senha substitui a pré-sessão do navegador.
- O segredo pendente fica criptografado na sessão do servidor; não substitui o fator ativo antes de um OTP válido. A confirmação bloqueia a linha do usuário, ativa o fator e incrementa a versão das sessões. Outras pré-sessões tornam-se inválidas.
- Mudança de senha, revogação de sessões, desativação, retirada de staff e expiração invalidam o cadastro. Pré-sessões legadas exigem nova entrada com senha.
- OTP: até 10 verificações por usuário em janela fixa de 300 segundos, independente de IP/navegador. Sucesso zera o contador da janela; nova configuração não o zera. A virada da janela restabelece o orçamento mesmo se uma chave antiga perder TTL. Janelas fixas permitem concentração de tentativas junto à fronteira.
- Um passo TOTP aceito não pode abrir outra sessão enquanto ainda for válido. Usa cache compartilhado; indisponibilidade do controle devolve 503 e recusa autenticação. Redis deve permanecer disponível, compartilhado e com memória suficiente; limpeza/perda de cache remove contadores e marcadores de replay.
- Login, início e confirmação MFA exigem CSRF, inclusive antes da autenticação. Clientes devem obter `/api/auth/csrf` e enviar cookie/token na escrita. O cliente web existente já realiza esse fluxo.
- Uma tentativa somente aceita simulado do próprio usuário. Depois de criada, seu vínculo com o simulado é imutável em PUT/PATCH, inclusive entre dois simulados do mesmo usuário.

## Validação reproduzível

Em ambiente local isolado, instalar `apps/api/requirements-dev.txt`, definir uma `DJANGO_SECRET_KEY` exclusiva de teste e executar em `apps/api`:

```text
python -m pytest -q
python -m ruff check core/mfa.py core/views.py core/serializers.py kairos/settings.py tests/test_mfa_security.py tests/test_attempt_ownership.py
python manage.py check --settings=kairos.test_settings
python manage.py makemigrations --check --dry-run --settings=kairos.test_settings
```

Os testes usam chaves efêmeras e dados sintéticos. As regressões iniciais produziram 25 falhas e 2 sucessos no código anterior. Na rodada final, a suíte local passou com 44 testes e quatro skips explícitos; Ruff e Django check limpos, sem migrations pendentes. Avisos locais: diretório `staticfiles` ausente, sem falha funcional da suíte. Na imagem candidata com PostgreSQL/Redis isolados, os 48 testes passaram sem skips e o smoke confirmou manifesto/CSS reais.

Cobertura: pré-sessões simultâneas/antigas, expiração/revogação, segredo pendente, limite entre clientes/IPs, reinício do cadastro, OTP reutilizado, falha de cache, CSRF ausente/origem indevida/fluxo válido, ownership e imutabilidade de tentativas. Testes existentes também verificam aluno impedido de consultar auditoria e dados de outro aluno.

A suíte local usa SQLite/LocMem e não comprova concorrência de bloqueios PostgreSQL/Redis reais nem E2E do navegador. A homologação isolada e as revisões independentes A/B foram executadas conforme `P0-INTEGRATION.md`; resultados, limitações e implantação constam em `P0-ENTREGA-2026-09-09.md`. Os testes HTTP não substituem automação visual do frontend.

## Deploy e rollback

Antes do deploy: repetir Regra Zero, obter backup atual dos bancos/storage/configuração, registrar imagens por ID e commit implantado, executar recuperação isolada conforme `P0-RESTORE.md`, homologar a imagem candidata e registrar snapshots no-touch. Não iniciar o Compose produtivo como ambiente de desenvolvimento.

O entrypoint histórico executa migrations e bootstraps a cada início. Para este lote sem migration, gerar os estáticos e iniciar Gunicorn sobre a configuração validada. A imagem também gera os assets no build. Não reiniciar com bootstrap administrativo implícito: ele pode reativar/promover contas.

Rollback de código: aplicar `git revert` dos commits deste lote em branch própria; não reescrever histórico. Rollback de serviço: reaplicar somente a imagem/configuração API anterior previamente registrada, sem bootstrap. Não restaurar banco para desfazer um lote sem migration: isso descartaria atividade posterior. As chaves ativadas continuam compatíveis; pré-sessões podem exigir novo login. O rollback reabre os achados corrigidos e deve ser registrado como incidente, com mitigação e novo prazo.

## Operação e limites

403 no cadastro MFA: configuração expirada/revogada; recarregar a página de login e entrar com senha para iniciar novamente. 429: aguardar a próxima janela, no máximo cinco minutos. OTP já usado: aguardar o próximo código do autenticador. 503: verificar disponibilidade do Redis e configuração da aplicação; nunca remover o segundo fator como correção automática.

Ainda pendentes em lotes separados: revisão integral RBAC/admin e teste de autoelevação de editor, isolamento/scopes de IA/MCP, privilégios de banco, minimização de secrets por serviço, edge HTTP, uploads/quotas, configuração SMTP e demais achados da auditoria. Nenhum deles é declarado resolvido por este lote.
