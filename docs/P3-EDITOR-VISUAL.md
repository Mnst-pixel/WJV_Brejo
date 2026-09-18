# Editor visual de conteúdo

O formulário de aula, resumo, artigo ou material permite escrever diretamente, selecionar um trecho para negrito/itálico, limpar destaque, escolher parágrafo/título/subtítulo/citação/lista e desfazer a última alteração de formatação. Depois de digitar novamente, o botão de desfazer formatação não substitui as novas palavras. A prévia editorial e a leitura do aluno apresentam a formatação da versão revisada.

Os controles de destaque operam em um parágrafo ou item de lista por vez. O editor informa quando a seleção atravessa blocos incompatíveis. A fonte jurídica continua no campo HTTPS próprio. A colagem insere texto simples; não incorpora imagens, scripts, estilos ou conteúdo remoto. Arrastar arquivos para o texto é recusado; anexos editoriais completos são um recorte separado.

## Persistência e revisão

`ContentVersion.body` permanece texto simples canônico. `structured_data.rich_text` contém uma árvore limitada e validada com parágrafos, títulos, citações, listas e trechos de texto com marcas booleanas. A projeção textual deve corresponder ao corpo. Quebras CRLF/CR de formulários são normalizadas para LF antes da comparação. O recibo editorial existente inclui corpo e estrutura, impedindo alteração da formatação após aprovação.

Não há migration, alteração automática de versões nem dependência externa nova. A estrutura não aceita HTML, links, atributos CSS, ferramentas, permissões ou nós executáveis. O servidor limita a 100.000 caracteres, 1.000 blocos/itens de lista e 5.000 trechos. Django e React renderizam somente elementos fixos com textos escapados. Estrutura antiga/desconhecida/incompatível usa corpo simples como fallback.

A validação central atende API e formulário. Antes de aprovar ou publicar, o comando recusa AST inválida, divergente ou não canônica; preserva o rascunho anterior para uma nova revisão explícita. Não normaliza nem reassina versões históricas durante a decisão.

Criar nova revisão preserva a formatação reconhecida e exige o mesmo workflow humano. Sem JavaScript, o formulário avisa que a nova versão será texto simples. O editor solicita confirmação do navegador antes de sair com alterações não enviadas; não promete autosave administrativo. Salvar rascunho continua sendo uma ação explícita.

## Validação e operação

Testes de formulário/AST/RBAC verificam conteúdo malicioso, campos desconhecidos, limites, discrepância de corpo, quebras de linha, fallback, revisão independente, restauração para rascunho e adulteração de marca após publicação. O E2E testa seleção/formatação → revisão → publicação → leitura do aluno. Controles de teclado/listas/colagem e mobile recebem revisão independente.

Rollback mantém `structured_data` e o texto canônico. Um cliente anterior pode apresentar o corpo simples, mas não deve sobrescrever a versão publicada nem reduzir o hash de aprovação. Deploy exige os gates operacionais documentados. Resultado final, commit e imagem são registrados em `P3-P6-ENTREGA.md`; a existência deste guia não indica implantação.
