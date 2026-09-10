# Fronteira de inferência e ferramentas — P0/P2

## Alteração e motivo

O consultor usa o modelo LocalAI existente diretamente, sem sessão Hermes, histórico remoto, ferramentas ou execução de comandos. A política roda no backend antes da recuperação: `ai.consult`, ownership de conversa/tentativa, estado da prova e enumeração das ações. Um `Agent.tool_allowlist` editado no banco não concede ferramentas a esse caminho. Perguntas e evidências nunca são convertidas em chamadas de ferramenta.

`ai_policy.py` admite somente filtros textuais limitados, data ISO e UUID de tentativa. O marcador legado `page=consultor` é aceito e descartado. Data inválida retorna validação; ausência da data resolve explicitamente a data atual. Evidências são enviadas como JSON no papel de usuário e não substituem o system prompt versionado. Isso contém a autoridade do modelo; não garante correção semântica de toda resposta.

`ai_transport.py` só aceita `http://localai:8080` e os caminhos fixos de geração/embeddings. Não utiliza proxies de ambiente, não segue redirects nem admite resposta comprimida. Bearer próprio do LocalAI autentica a chamada. Não há entrada que permita escolher URL, filesystem, comando ou recurso administrativo.

Limites compartilhados pelo cache Django/Redis: 12 consultas por usuário/minuto, 60 consultas globais/minuto e 120 requisições upstream/minuto. Cinco falhas de transporte numa janela de um minuto abrem o circuito até a janela seguinte. As janelas fixas podem permitir um pico na fronteira do minuto; não são sliding windows. Falha de cache nega a consulta. A busca lexical pode continuar caso embeddings estejam indisponíveis; geração permanece sujeita aos gates.

Conexão limitada a 3 s; leitura/escrita/pool a 10 s por operação, orçamento observado entre blocos de 45 s, até 64 KiB por resposta e 12 mil caracteres de texto. Uma leitura em andamento pode terminar até 10 s após o orçamento total. Sem retries automáticos. Corpo/schema/modelo inesperados e propostas `tool_calls`/`function_call` são recusados. Embeddings são processados em lotes de quatro, valores finitos e gravação transacional, preservando o modelo já armazenado.

O resultado registra usuário, prompt, fontes/hashes, modelo resolvido e política `kairos-policy-v1`. Mensagens, sucesso e auditoria são gravados atomicamente. Campos com credenciais configuradas e padrões comuns são redigidos antes de persistência/retorno. Redaction não equivale a detector universal de dados pessoais. A confiança da resposta gerada é `null`, pois não há estimador jurídico calibrado; ausência de evidência mantém confiança zero. `AgentRun`, `Message` e serializer aceitam `null`; a UI atual usa apenas `answer`.

## Arquivos e migrations

- `apps/api/core/services/ai.py`, `ai_policy.py`, `ai_transport.py`, `retrieval.py`.
- `apps/api/tests/test_ai_security.py`.
- Este documento.

Nenhuma migration ou dependência externa nova. Integração exige que a matriz RBAC conceda `ai.consult` aos papéis apropriados e que `ConsultView` exija a mesma permissão. Configuração opcional `LOCALAI_CHAT_MODEL` resolve por padrão `qwen3-1.7b-kairos`; a resposta precisa confirmar o mesmo nome. O modelo e a credencial de serviço precisam estar presentes no ambiente protegido.

## Verificação A

Com `PYTHONUTF8=1` e secret sintético de teste, executar de `apps/api`:

```text
python -m pytest --ds=kairos.test_settings tests/test_ai_security.py tests/test_retrieval.py -q
python -m ruff check core/services/ai.py core/services/ai_policy.py core/services/ai_transport.py core/services/retrieval.py tests/test_ai_security.py
python -m ruff format --check core/services/ai.py core/services/ai_policy.py core/services/ai_transport.py core/services/retrieval.py tests/test_ai_security.py
```

Testes cobrem RAG hostil, scopes/tools/command/path/URL não aceitos, autorização, isolamento de usuário, compatibilidade do contexto da UI, data inválida, modelo inesperado, output excessivo, redirects, compressão, redaction, limite, cache indisponível e circuito. Incluem uma consulta com socket HTTP real em loopback, credencial sintética, resposta e persistência; o transporte de teste remapeia o único host permitido ao servidor descartável. Não é benchmark do modelo real nem avaliação jurídica. A suíte integrada com PostgreSQL/Redis reais, revisão B e inferência de homologação ficam como gates de integração/deploy.

## Deploy, rollback e limites

O commit/imagem e evidências finais pertencem ao manifesto do lote integrado. Não houve deploy independente deste módulo. Rollback usa a imagem anterior e a configuração protegida correspondente, conforme procedimento central; não há migração de dados a desfazer. Não restaurar acesso aos serviços MCP históricos sem avaliar novamente seus riscos.

A mudança do consultor não torna o MCP completo. Root deve impedir caminho alternativo para Hermes/MCP antigos e reduzir secrets/redes por serviço. Gateway futuro deve autenticar identidade de máquina, aceitar delegação curta assinada pelo backend (chave ausente no agente), intersectar scopes com autorização atual do usuário e allowlist fixa, e rejeitar ferramentas genéricas. Consulta e administração permanecem separadas. Proposta inicial: `corpus.search` publicado e `study.notes.search` com owner obrigatório, sem rede arbitrária ou leitura de arquivos. Corpus vazio/ausência de credenciais externas continuam estados explícitos; não inventar dados para declarar IA operacional.
# Gate complementar de publicação

Recuperação e indexação do corpus exigem estado publicado, responsável humano de aprovação e timestamps de aprovação/publicação presentes e não futuros. Um flag `published` isolado não libera trechos. A indexação relê a aprovação no banco antes de chamar o modelo e novamente sob lock antes de persistir embeddings; revogação durante a avaliação aborta a gravação. Fixtures de teste registram responsável sintético explicitamente; nenhum conteúdo legado é promovido por essa adaptação.
