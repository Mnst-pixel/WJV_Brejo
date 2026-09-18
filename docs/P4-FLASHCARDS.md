# Flashcards pessoais e revisão

Implementação candidata, ainda não implantada. A biblioteca preserva a linguagem visual Kairós e acrescenta uma área para criar, editar, revelar respostas, avaliar lembrança, consultar histórico, arquivar e reativar cartões. Disciplina/tema aparecem pelo nome. Referências são informações pessoais não verificadas; uma autoavaliação de memória não confere validade jurídica ao texto.

## Persistência e consistência

PostgreSQL é a fonte canônica. Criação usa chave UUID por titular; reenvio idêntico devolve o cartão atual, sem duplicar, mesmo após edição. PATCH exige a versão observada. Edição ou revisão concorrente perde com 409 e não sobrescreve outra operação. Toda mutação trava primeiro o usuário e revalida sua permissão/sessão; depois trava o cartão. Conta esperada impede que um rascunho seja gravado sob outra sessão.

Avaliações recebem UUID próprio, versão do cartão e nota de lembrança 1–5. O servidor calcula a próxima revisão: 10 minutos, 1, 3, 7 ou 14 dias, respectivamente (`fixed-recall-v1`). Não usa relógio, pontuação ou agenda fornecidos pelo navegador. A revisão guarda cópia do texto e referência avaliados, instante e regra de agenda; reenvio retorna o recibo original. Edição posterior preserva recibos e recoloca o cartão na fila de revisão. Arquivamento preserva o histórico e bloqueia novas revisões; DELETE não está disponível.

`sessionStorage` mantém somente cópia temporária, limitada e separada por conta, de texto ou operação ainda não confirmada. Após refresh, o aluno confere o servidor antes de repetir. O rascunho local não substitui dados confirmados. Repetir uma avaliação pendente usa o mesmo UUID e não incrementa o histórico duas vezes. Se houver versão concorrente, o texto local permanece visível e exige decisão explícita; não há mescla automática.

## Arquivos e migration

- Backend: `core/personal_flashcards.py`, `models.py`, `serializers.py`, `views.py`.
- Frontend: `FlashcardsWorkspace.tsx`, `flashcards.css`, `LibraryWorkspace.tsx`.
- Schema: **0016_personal_flashcards** acrescenta versão, recibos de criação/revisão, arquivamento e agenda; constraints de faixa, versão e unicidade por titular; índice titular/arquivamento/data.
- Grants: `scripts/database-roles.py` retira UPDATE/DELETE do runtime em `core_flashcardreview`, junto às demais tabelas imutáveis. Reconciliar depois da migration.
- Legado: texto, titularidade e timestamps preservados. A agenda usa a última revisão do mesmo titular, sem inventar cópia histórica ausente. Revisões antigas permanecem identificáveis pelo snapshot vazio.

## Verificação e limites

A focada inicial: 19 PASS, duas corridas PostgreSQL pendentes do ensaio Linux; migration forward/reverse/forward preserva texto e agenda legados. B backend final: 80 PASS/3 skips PostgreSQL, Ruff e migrations sem drift; provas independentes de replay após arquivamento, ownership e migração com revisões de diferentes titulares. Achado corrigido: UUID inválido na rota de revisão retornava 500; o lookup DRF agora retorna 404. Essa correção exige a repetição final A.

Build Next.js, TypeScript e ESLint passaram. A completa inicial: **588 testes API PASS/32 skips explícitos**. E2E integrado real **PASS em 52,62 s**, com criação/perda POST/refresh, avaliação/perda de confirmação/reenvio único, edição/perda PATCH, recuperação de rascunho não enviado, troca externa de aba, conflito HTTP409 com outra aba, comparação e salvamento explícito, histórico, arquivamento e reativação. Um cartão final na versão8 e um único recibo histórico. Os quatro fluxos anteriores de administração, questões e ambas as fases permaneceram aprovados.

Correções durante a validação: faltava caminho para manter texto após conflito; bloqueio de navegação persistia na aba de leitura; labels aninhados incorporavam texto/opções ao nome acessível; botão da lista mantinha fundo padrão do navegador e os painéis usavam classe inexistente. Agora há comparação explícita, dirty associado à aba atual, vínculos htmlFor/id e estilos existentes do Kairós. A primeira execução de navegador excedeu180s; duas reproduções com timeout limitado localizaram o problema dos labels. Resultados anteriores não contam como aprovação final.

B frontend após correções funcionais: **21 probes PASS**, incluindo perdas, replay, conta, cache temporário e listagens concorrentes; **18 API PASS**; Chromium390 DOM/CSS sem overflow, labels e foco conferidos. Ajuste visual final exige repetição A/B. Testes de concorrência e privilégios PostgreSQL reais aguardam imagem isolada. Não declarar o módulo operacional antes desses gates e do deploy.

A final repetida após os ajustes: **588 API PASS/32 skips**, 141,86s; Ruff e migration sem drift. **E2E completo PASS, 49,60s**, incluindo os fluxos anteriores. Build/TypeScript/ESLint PASS. Screenshot real `modernizacao/evidencias/p3-editorial-browser/flashcards-mobile.png` inspecionada; fundo, bordas e painéis corrigidos, sem overflow em390/768/1440. Evidência consolidada: `editorial-browser.json`, chave `flashcardsWorkflow`; fixture também confere o cartão/recibo diretamente no banco descartável. B final visual em fechamento; sem deploy.

B final visual repetida: **21 probes PASS**, Chromium390 com labels/foco/sem overflow PASS, screenshot real inspecionada e sem achados. Hashes conferidos: workspace `ef0611843b6364ab9def3a24695349b8216d226478d6ef16e4aad3f7892d069a`; biblioteca `8d33025f62af73027aca02b6fdaddf7a9ce3b68a80feb78e417852f5b0eb2d8f`; CSS `2046e378c608028ddd669f5459155f411913ff4725a6095ed0c4fada397b63e7`. A/B locais concluídas; imagem Linux/PostgreSQL e deploy ainda pendentes.

## Imagem e PostgreSQL aprovados

Commit **5a5e82ee337e150b0e21b16f902d5b261682ae85**, archive SHA256 `66db4eb447c5c5abf51aee63ff3e809eb6caa54ec5eb824ed838fee8348aab84`. Imagem API **`sha256:7daa1078564a1b7cf63873278b742b94fb7a45125d415b01e038b605ba3be0e9`**; parser **`sha256:78c8fa535673ec9fa6cbd9092acfd637378b5575e44b7d08f0f96db2c96f0573`**. Revisões OCI conferidas; nenhuma imagem de produção substituída.

Linux isolado: **619 API PASS/1 skip browser opt-in**, 202,77s, incluindo ambas as corridas PostgreSQL de flashcards, migration histórica e privilégios reais. **268 operações PASS/18 skips**, 37,93s; 15 dependem do Node ausente nesse container Python (o contrato de manutenção já passou com Node/Caddy reais em ensaio separado), três contratos Git executados separadamente em conjunto de **13 PASS**. WordPress/PHP/MariaDB, Caddy, Gunicorn e inventário PASS; nonce concorrente12→1 aceito.

Execução: `/opt/kairos/runtime/p0/20260911T062434Z-foundations`; evidência de integração: `/opt/kairos/runtime/tests/kairos-test-20260911T062521Z-79d56ed2561d`; recibo local `modernizacao/evidencias/p0p2-candidate-20260911T062434Z.json`. Build, integração e comparador no-touch exit0. Comparador suplementar v2 **PASS sem exceções** em06:31:39UTC, helpers extraídos de novo do archive de hash conferido: `strict-verification/result.json`; recibo local `strict-flashcards-evidence.json`.

Nenhuma migration produtiva ou deploy neste lote. O Next.js foi compilado/testado localmente no mesmo commit; ainda não há nova imagem web/descriptor de produção para esse commit. A release inativa c12e53a não contém este módulo e não deve ser apresentada como tal.

## Deploy e rollback

Aplicar somente após backup novo e restore aprovado, em janela controlada, usando imagem da mesma revisão que a migration. O deploy candidato c12e53a anterior não contém este módulo; não reutilizar seu descriptor como se contivesse flashcards completos. Preparar uma nova release com commit/imagens correspondentes.

Rollback preferencial mantém schema aditivo e recibos, desabilitando a nova interface/endpoints em imagem compatível. A reversão de 0016 remove colunas novas, portanto não deve ser usada após novas escritas sem preservar/exportar esses dados e reconciliá-los. O teste de roundtrip com legado demonstra reprodutibilidade, não autoriza destruir revisões recentes. A versão antiga da API não deve receber tráfego com schema incompatível.
