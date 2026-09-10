# Gateway de ferramentas com delegação — P0/P2

## Contrato e autoridade

Este broker Django oferece somente duas operações de consulta: `corpus.search` sobre documentos publicados e `study.notes.search` sobre notas pertencentes ao usuário delegado. Não aceita URL, caminho, comando, código, alteração de papel ou nome de ferramenta transitiva. Resultados são dados não confiáveis; nenhum resultado é reinterpretado como política ou executado. O modelo de geração permanece sem ferramentas.

São necessárias duas identidades independentes: sessão humana no momento da delegação e conta de serviço no momento da chamada. A conta humana precisa de `ai.consult`; busca de notas também exige `study.use`. Contas administrativas precisam de MFA habilitado e verificado na sessão atual. Contas de serviço não podem emitir delegações. O usuário delegado vem exclusivamente da sessão, nunca do corpo da requisição.

A conta de serviço precisa estar ativa, ter o papel `conta-de-servico`, permissões atuais `service.integrate` e `mcp.query`, e não pode ser staff/superuser. O bearer identifica um único principal configurado fora do payload. Tokens iguais em dois principals são recusados. Comparação de tokens usa `hmac.compare_digest` e os valores não entram nos logs.

Cada delegação é assinada com uma chave dedicada do Django, contém audiência `kairos-mcp-readonly-v1`, serviço, UUID da máquina, UUID humano, versão da sessão, prova de MFA, scopes e nonce aleatório. Expira em 60 segundos e pode ser consumida uma única vez. O Redis usa `add` atômico para recusar replay; falha do cache nega a operação. Mudança de papéis, desativação, troca de principal/scope e revogação da sessão são revalidadas antes da execução. Assinatura e scopes não permitem que a máquina delegue poder adicional a si mesma.

## Configuração protegida

O root integra `core.mcp_views.MCPDelegationView` em `/api/mcp/delegate` e `MCPToolCallView` em `/api/mcp/call`. Os testes usam URLs próprias para não editar o roteamento central em paralelo.

`KAIROS_MCP_PRINCIPALS` é um mapping em settings, materializado a partir de configuração protegida pelo deploy:

```python
{
    "kairos-tools": {
        "token": "<credencial própria de pelo menos 32 caracteres ASCII>",
        "user_id": "<UUID da conta kairos_tool_client>",
        "scopes": ["corpus.search", "study.notes.search"],
    }
}
```

`KAIROS_MCP_DELEGATION_KEY` tem pelo menos 32 caracteres e deve ser distinta de `SECRET_KEY` e de todos os bearers de máquina. Só o backend confiável recebe essa chave. Containers de modelo não recebem a chave, bearer MCP, credenciais de banco ou secrets administrativos. Configuração ausente falha fechada; placeholders nunca habilitam a integração operacional.

## HTTP

1. Sessão humana + CSRF faz POST `/api/mcp/delegate` com `{"service_id":"kairos-tools","scopes":["study.notes.search"]}`. Retorna `delegation`, `expires_in:60` e `audience`, com `Cache-Control:no-store`.
2. Cliente de máquina faz POST `/api/mcp/call` com bearer próprio e `{"delegation":"<assinatura>","tool":"study.notes.search","arguments":{"query":"processo","limit":5}}`.
3. O broker intersecta autorização humana atual, principal atual, permissão da máquina, scopes assinados e allowlist fixa. Retorna `tool`, `items`, `trust:"untrusted_data"` e `policy`.

Uma falha depois de consumir a delegação exige emissão de outra; repetir o mesmo token é sempre negado. Não usar tokens em query strings ou logs. Não há endpoint administrativo nesse broker.

## Limites e disponibilidade

- JSON máximo de 16 KiB, inclusive quando Content-Length não é confiável; leitura limitada antes do parsing.
- Consulta textual até 400 caracteres, limite inteiro de 1 a 5 resultados, trechos de até 1.200 caracteres, resposta máxima de 32 KiB.
- Até 20 emissões por usuário/minuto, 20 chamadas por usuário/minuto e 60 por serviço/minuto, em janelas fixas compartilhadas.
- Notas consultam somente o banco local com owner obrigatório. Corpus usa o retrieval publicado existente; embeddings opcionais usam o transporte LocalAI limitado e seu circuit breaker, com fallback lexical. Não há adapter externo arbitrário; circuit breaker de fornecedor externo não se aplica às notas locais.
- Eventos de emissão, conclusão e negação registram ator, serviço, ferramenta, quantidade/status e request ID existentes; não persistem bearer, assinatura, pergunta ou resultado nas colunas de metadata.

O caminho antigo Hermes/MCP precisa ser isolado/desativado pelo Compose canônico. Este contrato não prova funcionamento de DataJud/INLABS, ferramentas externas ou encadeamento modelo→tool. Isso permanece explicitamente fora da prontidão deste gateway fundacional.

## Verificação e operação

Arquivos: `apps/api/core/mcp_boundary.py`, `mcp_views.py`, `tests/test_mcp_scopes.py` e este documento. Nenhuma dependência ou migration neste lote; a criação da conta e o seed de permissões são integrados pelo lote RBAC/deploy.

Verificação A local: 37 testes passaram, 1 teste de replay concorrente ficou condicionado ao PostgreSQL/Redis isolado. Inclui sessão+CSRF e bearer em HTTP real com `live_server`, ownership, corpus publicado, scopes, injection, mudança de permissões após emissão, MFA, assinatura, binding, replay, expiração, corpo máximo e cache indisponível. Warnings locais de diretório `staticfiles` ausente são conhecidos; a imagem deve passar o gate de estáticos. Ruff e formatação passaram.

```text
python -m pytest --ds=kairos.test_settings tests/test_mcp_scopes.py -q
python -m pytest --ds=kairos.integration_test_settings tests/test_mcp_scopes.py -q
python -m ruff check core/mcp_boundary.py core/mcp_views.py tests/test_mcp_scopes.py
```

Revisão independente B, execução real com Redis/PostgreSQL, roteamento e smoke da imagem são gates do lote integrado. Commit, imagem, deploy e evidências finais devem constar em `P0-P2-ENTREGA.md`. Rollback usa a imagem/configuração anterior validada; nenhuma alteração de schema desse módulo requer reversão. Nunca reativar o stack MCP histórico apenas para contornar falha de configuração deste broker.
