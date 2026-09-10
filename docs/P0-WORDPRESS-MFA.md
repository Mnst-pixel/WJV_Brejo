# WordPress: barreira administrativa com MFA

## Evidência e alteração

O repositório anterior contém somente o MU-plugin visual `kairos-brand.php`; a documentação exige MFA para administradores, mas não comprova MFA nativo do WordPress. Isso não prova ausência de plugins adicionais no VPS: o inventário real permanece um gate da implantação. As credenciais e os conteúdos humanos do WordPress não são alterados.

O Caddy consulta `/api/internal/wordpress-auth` antes de encaminhar uma requisição WordPress. O endpoint exige a prova interna `KAIROS_PROXY_TOKEN`; a rota `/api/internal/*` responde 404 ao público. O método e URI originais são definidos pelo próprio `forward_auth`. A execução ordenada usa `route`, conforme a [documentação oficial de forward_auth](https://caddyserver.com/docs/caddyfile/directives/forward_auth) e de [route](https://caddyserver.com/docs/caddyfile/directives/route).

Login, `/wp-admin`, PHP executável, escritas REST, method override, previews, contexto REST `edit`, cookies de autenticação WordPress e Authorization exigem sessão Kairós atual de administrador com `settings.manage`, MFA habilitado, segredo MFA cadastrado e verificação MFA da sessão. O estado do usuário e a versão da sessão são relidos sob lock. Aluno, editor, suporte e service account são recusados. XML-RPC é recusado inclusive para administradores. GET/HEAD/OPTIONS anônimos do blog e REST de leitura permanecem disponíveis.

## Defesa no WordPress e replay

O MU-plugin obrigatório `kairos-admin-gate.php`, montado read-only individualmente, exige uma atestação HMAC até para acesso HTTP direto pela rede Docker. A chave interna dedicada `KAIROS_WORDPRESS_GATE_KEY` é gerada por release-secrets, com escopo apenas API/WordPress. WordPress não recebe a prova de edge; Caddy não recebe a chave de assinatura.

A atestação dura no máximo 10 segundos, tolera somente 2 segundos futuros e vincula método, URI exata, hashes de Cookie, Authorization e method override, classe de autorização e nonce aleatório de 128 bits. O Caddy remove qualquer atestação enviada pelo cliente, copia exclusivamente a resposta interna e remove o cabeçalho da resposta WordPress. Nenhuma chave, cookie ou senha integra o token.

Atestações administrativas têm uso único: INSERT em option_name único no MariaDB reclama o nonce atomicamente entre processos Apache. Registros próprios `_kairos_gate_nonce_*` expirados são removidos em lotes de 256, sem autoload; capacidade de 4096 registros falha fechada. Não há migration Django nem alteração de conteúdo WordPress. Provas públicas permitem apenas leitura sem identidade WordPress e expiram em 10 segundos; não usam registro de replay. O MU-plugin impede obtenção de identidade por prova pública, bloqueia administração/REST de escrita sem classe administrativa e desabilita application passwords/XML-RPC nativos. WP-CLI continua uma operação privilegiada local, fora do fluxo HTTP.

## Operação e impactos

1. Entrar em `/app` com conta administrativa Kairós e concluir MFA.
2. Abrir `/wp-admin/`; autenticar também com a conta WordPress existente.
3. As duas autorizações são necessárias em cada nova requisição administrativa. Revogação Kairós bloqueia o próximo acesso; uma requisição já autorizada pode terminar dentro da janela de 10 segundos.

Editor WordPress que não possui `settings.manage` no Kairós fica bloqueado nesta etapa. Não há concessão automática de papel. Formulários públicos com POST, AJAX via `wp-admin/admin-ajax.php`, preview e wp-cron HTTP também exigem autorização e devem ser inventariados antes do deploy. Não foi criado cron privilegiado alternativo. Caso o agendamento WordPress seja necessário, preparar WP-CLI em rotina própria validada; não abrir exceção HTTP sem avaliação. Cookies WordPress remanescentes sem sessão Kairós válida fazem até leitura exigir novo login Kairós. Plugins com ações mutáveis em GET público precisam revisão específica no inventário: a barreira não torna seguro código de plugin arbitrário.

O blog depende do endpoint Django para a autorização de cada requisição dinâmica: falha/time-out de API causa falha fechada; não usar fallback sem autenticação. Assets servidos diretamente pelo Apache não executam o MU-plugin, mas passam pelo Caddy público e não fornecem autenticação administrativa. PHP só é confiável com o MU-plugin carregado: confirmar mount real e inventário de plugins antes da entrega. WordPress comprometido com execução arbitrária de PHP e leitura de sua chave fica fora da proteção HMAC; a segregação de rede/credenciais e o patching continuam obrigatórios.

## Testes e gates

`pytest tests/test_wordpress_auth_gate.py`: 42 testes locais PASS (autorização atual, revogação, MFA, roles, escopo, XML-RPC, métodos/encoding, prova de edge e contrato de assinatura). `php wordpress/tests/test-admin-gate.php` testa contrato, alterações de campos, expiração, replay e limites com banco simulado; sua execução PHP é um gate separado, não evidência de MariaDB real.

Antes de declarar operacional: validar Caddy com a imagem pinada; executar contrato PHP; inventariar plugins/rotas WordPress reais; testar HTTP público e interno, cookies válidos/inválidos, MFA completo, replay concorrente em MariaDB isolado e páginas/REST/cron afetados. Não houve VPS, deploy ou modificação de credenciais humanas nesta implementação.

## Rollback

Reverter somente pela release anterior completa (imagem API, Caddy, Compose, escopos de secrets e MU-plugin). Retirar isoladamente a barreira reabre o risco de administração sem MFA e não é rollback aceitável com administração pública. Até alternativa MFA validada, manter administração bloqueada no edge. Registros efêmeros de nonce podem permanecer sem efeito; não remover opções humanas por prefixos amplos.
