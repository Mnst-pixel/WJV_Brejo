# Kairós — registro de fidelidade visual

Data da verificação: 2026-08-27

## Artefatos

- Conceito desktop: `dashboard-desktop-concept.png`
- Implementação desktop: `dashboard-desktop-actual.png`
- Conceito móvel: `dashboard-mobile-concept.png`
- Implementação móvel (primeiro viewport): `dashboard-mobile-actual.png`
- Implementação móvel (página completa): `dashboard-mobile-full-actual.png`

Os conceitos foram gerados com o seguinte direcionamento de produção: criar uma interface premium e sóbria para a plataforma jurídica educacional **Kairós**, usando a ilustração fornecida do sapo como símbolo central; caverna escura, verde profundo, pergaminho, bronze e azul-oráculo; tipografia Montserrat; painel desktop com navegação lateral, próximo passo, jornada, agenda, Pomodoro, gráfico de desempenho e base jurídica; e uma composição móvel responsiva com cabeçalho compacto e navegação inferior. Evitar aparência genérica de SaaS, excesso de brilho e texto ilegível.

## Comparação

| Ponto | Conceito | Implementação verificada | Resultado |
|---|---|---|---|
| Hierarquia desktop | Navegação fixa, cabeçalho, duas faixas de cartões e barra jurídica | Mesma hierarquia e proporções gerais, com os controles utilitários incorporados à lateral | Fiel |
| Linguagem visual | Caverna, linhas concêntricas, verde profundo, pergaminho e bronze | Fundo de caverna próprio, texturas concêntricas e a mesma paleta sem efeitos decorativos excessivos | Fiel |
| Marca | Sapo ilustrado e nome Kairós | Usa o símbolo original fornecido, sem redesenho, na lateral e no cabeçalho móvel | Mais fiel à fonte |
| Componentes centrais | Próximo passo, jornada, agenda, Pomodoro, desempenho e base jurídica | Todos presentes, navegáveis e com estados interativos | Fiel |
| Responsividade | Herói, três etapas da jornada e navegação inferior | Mesma ordem; conteúdo adicional continua abaixo do primeiro viewport, sem cortes horizontais | Fiel e funcional |
| Tipografia | Montserrat com títulos fortes e texto contido | Montserrat hospedada localmente, escalas fluidas e foco visível | Fiel |

## Ajustes realizados após a inspeção

- Corrigida a rota dinâmica dos módulos, que inicialmente retornava 404 por importar configuração de um componente cliente.
- Corrigidos o tamanho do ícone do CTA móvel e o alinhamento dos itens da agenda.
- Adicionado contraste atrás do texto do cartão com o símbolo, preservando a ilustração e a legibilidade.
- Verificados o Pomodoro, o painel de acessibilidade, o menu móvel e a navegação para Estudar e Questões.

## Diferenças intencionais

- A implementação mostra o símbolo original entregue pelo usuário, enquanto o conceito contém uma interpretação gerada da marca.
- A barra jurídica informa cobertura por fonte, em vez de sugerir uma data global que poderia criar falsa sensação de atualização completa.
- Em telas móveis, o gráfico e a base jurídica permanecem disponíveis por rolagem; o conceito mostra apenas a primeira dobra.
