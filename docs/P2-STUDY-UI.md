# Integração da interface com persistência canônica

Esta alteração preserva componentes, classes, paleta, grid e desenho da plataforma. Conecta controles existentes a dados da conta e identifica as visualizações ainda demonstrativas. Não transforma dados ilustrativos em histórico de estudante.

## Preferências

`SettingsWorkspace` usa o hook compartilhado `useStudyPreferences`: GET/PATCH `/api/auth/me`, com CSRF no PATCH. Movimento reduzido, densidade reduzida e largura confortável usam valores retornados pelo servidor; ficam desabilitados até carregar e durante salvamento. Erros e confirmação aparecem no próprio formulário. Nenhum desses valores usa localStorage como fonte principal.

As duas regras visuais novas são opt-in: `html[data-reduced-density="true"]` aumenta espaçamento dos controles; `html[data-comfortable-reading="true"]` limita texto de leitura/respostas a 68ch. O AppShell aplica os atributos usando o hook compartilhado. Preferência ausente é false; o layout padrão permanece igual. Movimento reduzido conserva a regra existente.

## Metas no dashboard

O bloco antes preenchido com agenda fictícia passa a mostrar até três metas retornadas por `/api/goals/`. Datas vêm de `target_date`, sem horários inventados; metas sem data mostram traço. O link leva à lista de metas da conta.

Concluir dispara PATCH no objeto escolhido com `progress:100`. A interface só substitui o valor após a resposta confirmada do servidor, desabilita cliques duplicados durante envio e mantém itens concluídos identificados. Falha de rede não é confundida com rejeição definitiva: orienta recarregar para conferir o estado real antes de tentar novamente. A data de conclusão é responsabilidade do backend.

O bloco Pomodoro e seu hook não foram modificados por este lote. Progresso estático, jornada com etapas e gráfico mantêm o desenho, mas recebem rótulos visíveis de demonstração e descrição acessível correspondente. O seletor de período ilustrativo fica desabilitado; nenhum número demonstrativo é apresentado como resultado real do aluno.

## Arquivos

`FileManager` lista `/api/files/`, permite paginação, atualização manual e apresenta estados de quarentena/processamento/rejeição em linguagem simples. Enquanto houver trabalho pendente, atualiza até dez registros visíveis por rodada a cada cinco segundos, somente com a página visível. O componente cancela atualizações após sair da tela. Respostas antigas da listagem não sobrescrevem uma solicitação mais recente.

Upload continua multipart com CSRF. Sucesso recarrega a lista; erro de quota/tipo/tamanho retornado pela API aparece no formulário. Em resposta incerta, orienta consultar a lista antes de reenviar. A lista não depende da seleção local do input nem de cache no browser, portanto reaparece após reload.

Abrir arquivo solicita `/api/files/<id>/download/` e só habilita o controle quando `scan_status=clean` e `processing_status=processed_pending_review`. O backend retorna `/api/files/<id>/content/` na mesma origem e repete sessão, autoridade atual, ownership e estado ao servir o attachment. Esconder ou desabilitar botão não é segurança. MinIO permanece privado na rede Docker; o browser não recebe URL interna ou acesso anônimo ao storage.

Excluir solicita DELETE do objeto. A linha sai após confirmação; a mensagem distingue exclusão registrada de limpeza física concluída. Falha de rede orienta atualizar, pois o servidor pode ter concluído mesmo sem o cliente receber a resposta. Erros preservam a lista disponível; não exibem dumps, chaves privadas ou detalhes internos de processamento.

## Integrações

A área de configurações consulta `/api/integrations/status/` e mostra e-mail, INLABS, DataJud e backup externo. `unconfigured` aparece como configuração externa pendente; `configured_unverified` como configuração presente com validação operacional pendente. Nenhum desses estados é rotulado como operacional. Falha de consulta tem mensagem própria e não impede preferências ou módulos independentes.

Os botões de privacidade existentes sem endpoint funcional ficam desabilitados e identificados como indisponíveis nessa tela, evitando cliques sem resultado. Não foi implementada exportação/exclusão de conta por este lote.

## Verificação de integração/E2E

Executar na imagem candidata após typecheck/lint/build, com contas e dados sintéticos:

1. Entrar como aluno A, abrir configurações, alterar cada preferência, aguardar confirmação e recarregar. GET deve devolver os valores; switches e atributos devem refletir a conta. Entrar como B e verificar isolamento. Simular falha de PATCH e ausência de sessão: não exibir confirmação de salvamento.
2. Criar uma meta real, abrir dashboard, concluir, recarregar e verificar `progress=100` no dashboard e na API. Repetir PATCH/refresh não deve criar outra meta. Falha de rede deve orientar consulta do estado real.
3. Verificar conta sem metas: estado vazio sem agenda demonstrativa. Conferir rótulos de demonstração no progresso, jornada e gráfico, inclusive nomes acessíveis.
4. Enviar documento limpo, observar lista e evolução de estado, recarregar, abrir download autenticado na mesma origem e conferir conteúdo/attachment/no-store. Repetir a URL sem sessão e com outra conta: acesso negado. Tentar abrir durante quarentena deve ser bloqueado também pela API. Repetir com EICAR no ambiente isolado e com quota excedida.
5. Aluno B não deve listar/consultar/abrir/excluir arquivo de A. Excluir como A, recarregar e conferir ausência da linha. Simular erro/timeout de DELETE e validar aviso de confirmação incerta.
6. Listar mais de uma página de uploads e verificar paginação e atualização. Sair da tela deve encerrar o timer de consulta.
7. Ausência de SMTP/INLABS/DataJud/off-host deve aparecer como pendência, mantendo estudo/metas/preferências disponíveis. Configuração preenchida sem teste não deve aparecer como operacional.

Nenhuma dependência npm nova foi adicionada. Este documento registra fluxos esperados para verificação; não é evidência de E2E executado. O coordenador registra resultados do build e testes reais na entrega P0–P2. Não há migration neste ajuste de interface; os endpoints/modelos canônicos são entregues pela fundação backend.
