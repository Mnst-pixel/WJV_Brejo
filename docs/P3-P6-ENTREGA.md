# P3–P6 — plataforma educacional

Execução incremental iniciada em 10/09/2026 a partir de `8a36d5fc993a26f621462bc87c2717780639c6b4`, na branch `astra/kairos-p3-p6-produto`.

**Entrega em andamento. PRODUCT_CORE_READY=NO.** A aprovação do trabalho P0–P2 autoriza a próxima implementação; não transforma os gates operacionais pendentes em evidências de produção.

## Baseline imediatamente anterior

Revalidação somente leitura em 10/09/2026 22:42:55 UTC, evidência externa ao Git `modernizacao/evidencias/p3-p6-initial-state.json`:

- HEAD local `8a36d5fc993a26f621462bc87c2717780639c6b4`; `origin/main` atualizado `cb4708d80b8214e931bc94a871e2ee5e130a4dbf`.
- Checkout VPS `/opt/kairos/current`: `f6ac1c3c510a4f442b9101d599e6598fe8428ca0`, limpo.
- API implantada: `8f341aa4c87e2a6692b557cfafd0204bee7b910c`; imagem `sha256:078a0937a5a89cc374cd43c3848d105587d4ea7c0f82807e7f7352fdff417eee`.
- Compose histórico e override `/opt/kairos/runtime/p0/20260909T194305Z/source/infra/compose/p0-api.override.yaml` continuam ativos. Ponteiro canônico de release ausente.
- API, web, PostgreSQL, Redis, MinIO, WordPress, ClamAV e edge saudáveis, zero reinícios; worker em execução sem healthcheck.
- PostgreSQL: 19 migrations, 3 usuários; `kairos_app` ainda superuser/createdb/createrole.
- Disco livre: 50.659.438.592 bytes; memória disponível: 5.409.536 KiB.
- Timers de backup e saúde ativos e habilitados. Backup recente `kairos-predeploy-20260910T222458Z-abe1a93603cc.tar.gz.enc`: 68.903.872 bytes, modo 0600, checksum válido. Restore/migrations isolados desse arquivo estão documentados na entrega P0–P2.
- Nenhum recurso de produção alterado nesta etapa. As pendências de cutover integral, rollback operacional e ativação dos privilégios mínimos permanecem em `P1-CUTOVER-PENDING.md`.

## Decisão administrativa

Solução híbrida: painel editorial próprio, renderizado pelo Django e apoiado nos comandos de negócio existentes; Django Admin permanece para formulários operacionais especializados. Next.js continua responsável pela experiência do aluno e pelo login com MFA. WordPress permanece público/editorial institucional.

Motivo: o admin anterior usa formulários genéricos e não oferece ações editoriais completas. Reutilizar transações, autorização e versões imutáveis reduz duplicação e mantém o fluxo operacional sem terminal, JSON ou identificadores técnicos digitados pelo operador. O primeiro recorte é conteúdo e taxonomia; as demais áreas ainda não são declaradas completas.

## Lote P3.1 — operação editorial

Alterações:

- Navegação, indicadores editoriais reais, busca por título, filtro por disciplina/situação, paginação e estados vazios.
- Criar disciplina/tema/subtema por formulário. Vínculos existentes de temas não podem ser movidos pelo admin especializado.
- Criar rascunho, prévia segura, nova revisão, histórico, comparação com versão anterior e restauração para novo rascunho.
- Enviar para revisão, aprovar por outra pessoa, publicar e arquivar pelos serviços existentes. POST repetido não executa a decisão seguinte.
- Importar acervo antigo por prévia e confirmação, deduplicação e revisão humana. GET de prévia não cria dados.
- MFA obrigatório mesmo sem `is_staff`; autorização real por ação, CSRF e respostas privadas sem cache. Texto escapado, sem executar HTML.
- Fonte, datas e comentários por campos amigáveis; hash gerado no servidor com indicação explícita de que é hash do texto autoral. Não se afirma que o site da fonte foi coletado.
- Paleta Kairós, símbolo existente e Montserrat local sob licença OFL; formulários responsivos e foco visível.

Arquivos: `apps/api/core/editorial_*.py`, `core/templates/editorial/*`, `core/static/editorial/*`, `core/admin.py`, `kairos/urls.py`, `tests/test_editorial_workspace.py`, `tests/browser/*`, `apps/web/components/LoginForm.tsx`.

Migrations: nenhuma neste lote; modelos P0–P2 reutilizados. Novos registros são inseridos somente pelo operador autorizado.

Testes e evidências: 17 testes HTTP do painel passaram; revisão B independente Django executou 76 testes com sucesso, com 3 concorrências PostgreSQL explicitamente pendentes. A revisão B inicial encontrou limites divergentes entre formulário/PostgreSQL e validação do pai fora da transação. Ambos receberam correção e regressões. O E2E real passou com senha/TOTP no Next.js, criação de disciplina/conteúdo, revisão/publicação por três papéis e aluno negado (403); desktop 1440×1000 e mobile 390×844, sem overflow e sem erros inesperados. HTTP428 no desafio MFA é esperado e verificado. Evidências externas: `modernizacao/evidencias/p3-editorial-browser/editorial-browser.json`, `editorial-desktop.png`, `editorial-mobile.png`. Rerun final/imagem em preparação.

Problemas de executor resolvidos: o Chromium esperado pelo Playwright não estava instalado; o Chromium alternativo falhou no spawn; Chrome local com perfil descartável funcionou. O proxy de teste passou a encaminhar WebSocket do Next.js; sem isso não ocorria hidratação. Os controles do login aguardam hidratação e o destino editorial usa URL local fixa, fora do roteador Next.js. Uma tentativa de executar scripts via pnpm iniciou instalação automática local; arquivos auxiliares gerados foram removidos e a verificação usou diretamente os executáveis Node/TypeScript/ESLint, preservando `package-lock.json`. Esses eventos não envolveram produção nem alteração das dependências declaradas.

Validação local adicional: suíte API completa com 448 testes aprovados e 19 skips explícitos de plataforma/integrações/browser; o browser foi executado separadamente e passou duas vezes, com a última execução em 9,90 s. TypeScript, ESLint sem warnings e build Next.js otimizado passaram. Ruff e `git diff --check` passaram. As imagens e os testes PostgreSQL do novo commit ainda precisam ser registrados.

Commit/imagem/deploy: ainda sem release P3 implantada. Não existe evidência que autorize declarar este painel disponível no VPS atual. Guia leigo: [EDITORIAL.md](EDITORIAL.md).

Rollback: retornar ao artefato anterior remove as novas rotas e formulários, preservando versões, aprovações, taxonomia e provenance nos modelos existentes. Publicação indevida deve ser arquivada pelo comando autorizado; restauração editorial cria revisão e exige nova aprovação. Não reverter dados com DELETE. A troca da release completa depende do coordenador de cutover/rollback P1 e do backup validado.

## Matriz funcional

“Disponível” abaixo significa produção verificada, não somente código local.

| Funcionalidade | Implementada | Testada | Disponível ao aluno | Disponível ao admin | Pendência | Evidência |
|---|---|---|---|---|---|---|
| Administração editorial sem JSON | Parcial | HTTP/RBAC e E2E real | Não | Não | Completar áreas e publicar release | `test_editorial_workspace.py`, `editorial-browser.json` |
| Disciplina → tema → subtema | Criar/listar | Validação, limites e corrida de pai | Não | Não | Associação editorial completa e deploy | Testes de taxonomia |
| Rascunho → revisão → aprovação → publicação | Sim, serviços reutilizados | Serviço, HTTP e E2E real | Não | Não | Deploy | `test_content_workflow.py`, `editorial-browser.json` |
| Histórico/restauração de conteúdo | Sim, restaura para rascunho | HTTP e preservação da publicação | Não | Não | Comparação detalhada, agendamento e deploy | Teste de workflow completo |
| Legado não verificado | Prévia/importação/revisão | Serviço existente; UI a ampliar | Não | Não | Mesclar/rejeitar/classificar em lote | `content_workflow.py` |
| Editor visual e anexos relacionados | Não | Não | Não | Não | WYSIWYG, múltiplos anexos e metadados pedagógicos | Pendente |
| Usuários/planos e painel de operação completo | Fundação backend | P0–P2 | Não verificado | Não verificado | Jornadas leigas completas | Entrega P0–P2 |
| Dashboard, metas, notas, arquivos, Pomodoro | Fundação existente | P0–P2 | Release antiga apenas | Não | Jornada e próximo passo pedagógico | Entrega P0–P2 |
| Questões e sessões personalizadas | Modelos/serviços iniciais | Fundação P0–P2 | Não verificado | Não | Autoria/revisão, filtros e histórico completo | Pendente P5 |
| Simulado 1ª fase, autosave e nota | Engine inicial | Consistência P0–P2 | Não verificado | Não | Configuração e E2E completo | `test_attempt_consistency.py` |
| Analytics pedagógicos | Parcial | Consultas básicas | Não verificado | Não | Metas quantitativas, tendências e recomendações determinísticas | Pendente P4/P5 |
| Casos/peças/espelhos de 2ª fase | Modelos iniciais | Insuficiente | Não | Não | Modelo complementar e editor visual de critérios | Pendente P6 |
| Prova 2ª fase, autosave e submissão | Não completa | Não | Não | Não | Editor, recuperação, envio imutável e histórico | Pendente P6 |

## Execução do navegador

Harness opt-in `tests/browser/test_editorial_browser.py`: Django test database descartável, Next.js local, proxy somente loopback e usuários sintéticos. A senha e o TOTP sintéticos passam por stdin e nunca são gravados em evidências. Definir `KAIROS_BROWSER_TESTS=1`, `KAIROS_NODE_BIN`, `KAIROS_PLAYWRIGHT_MODULE`, `KAIROS_CHROMIUM_EXECUTABLE`, `KAIROS_E2E_NEXT_URL` e diretório externo de evidências `KAIROS_BROWSER_EVIDENCE_DIR`. Executar pytest com `--ds=kairos.test_settings`. Nunca apontar esse harness para produção.

Fallback de automação: Browser plugin not available; Playwright regular instalado no runtime. O Chrome local usa perfil descartável, sem perfil pessoal. Alvos: login Next.js/senha/TOTP → formulários Django → publicação por três papéis; bloqueio de aluno; desktop 1440×1000 e mobile 390×844.

## Próximos lotes e gate

Concluir o painel editorial com evidências A/B, ampliar autoria de questões e provas usando as versões existentes, implementar a jornada de treino/simulado, e completar casos/espelhos/submissões da segunda fase. Cada lote recebe testes e documentação antes da homologação e da implantação. A modernização completa ainda exige resolver as pendências operacionais herdadas e executar os quatro E2E exigidos pelo usuário.

`PRODUCT_CORE_READY=NO`
