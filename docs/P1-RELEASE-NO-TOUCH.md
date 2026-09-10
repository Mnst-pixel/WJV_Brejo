# Gate de release: configuração e rede atribuída ao Kairós

`scripts/compare-release-snapshots.py` complementa o comparador histórico. Sem `--manifest`, chama `compare-vps-snapshots.sh` e preserva seu exit code. O script antigo permanece intacto; backup/restore sem mudança de configuração podem continuar a utilizá-lo.

O manifesto v1 permite diferenças de hashes previamente especificadas para paths Kairós exatos. O manifesto v2 acrescenta a atribuição restrita de rede descrita abaixo. Mantém recursos alheios protegidos e retorna FAIL quando qualquer diferença não corresponde ao plano. Não gera autorização automaticamente a partir do snapshot posterior. Preparar/revisar o manifesto antes do deploy, preservá-lo em arquivo operacional protegido e registrar seu SHA-256; o resultado imprime esse hash e o commit declarado. O comparador verifica consistência das evidências, não confere sozinho se o commit foi implantado nem autentica o autor do manifesto.

## Manifesto v1

```json
{
  "version": 1,
  "release_commit": "cccccccccccccccccccccccccccccccccccccccc",
  "config_changes": [
    {
      "path": "/opt/kairos/current/infra/compose/compose.yaml",
      "before": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "after": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  ]
}
```

O exemplo contém hashes sintéticos. Usar o hash do conteúdo efetivamente capturado antes e o hash do arquivo revisado do release. `before: null` permite adição de um arquivo Kairós previamente ausente. `after` deve ser SHA-256 não nulo: essa primeira versão não autoriza apagar configurações históricas. Cada entrada deve produzir exatamente a mudança esperada; entradas duplicadas, não observadas, com hashes iguais ou errados reprovam o gate.

Paths permitidos são configurações sob `/opt/kairos/current/infra/`, configurações `infra` em releases/runtime Kairós, o virtual host exato `kairos-sslip.conf` nos diretórios sites-available/sites-enabled e unidades `/etc/systemd/system/kairos-*.service`/`.timer` com nomes concretos. Glob, traversal, paths de secrets e `.env` são recusados. O padrão da implementação reconhece o namespace, mas o manifesto sempre precisa nomear cada arquivo individualmente. Não permite `/etc/nginx/nginx.conf`, outros virtual hosts ou arquivos fora do Kairós.

```bash
python3 /opt/kairos/current/scripts/compare-release-snapshots.py \
  /opt/kairos/runtime/baselines/release-before \
  /opt/kairos/runtime/baselines/release-after \
  --manifest /opt/kairos/runtime/release-config-changes.json
```

Antes e depois devem ser capturados com a versão atual de `vps-snapshot.sh`; o snapshot posterior recebe o anterior como segundo argumento para continuar relendo overrides aposentados. Snapshots/manifests precisam permanecer protegidos contra escrita não autorizada; hashes não são assinaturas digitais. O comparador não altera esses arquivos.

## Inventários e fronteiras

As 14 entradas históricas continuam obrigatórias. Configurações são comparadas em `compose-config-hashes.txt`, `nginx-config-hashes.txt` e, quando presente, `release-config-hashes.txt`. O mesmo path em inventários diferentes precisa ter o mesmo hash; omissão em um inventário não pode esconder mudança. Adição de configuração Nginx alheia também reprova, mesmo quando o comparador antigo toleraria adições.

`vps-snapshot.sh` agora captura separadamente Caddyfile Kairós, virtual host e quatro unidades/timers de backup/health. Symlinks desses paths só podem resolver para os destinos próprios permitidos. O Compose histórico continua sendo capturado pela lista efetivamente declarada nos containers.

Identidades de containers/redes alheios devem continuar iguais; ter `kairos` no nome da imagem não exclui um container de outro projeto. Volumes e imagens anteriores devem permanecer. Serviços alheios, cron e certificados não admitem diferença. A existência/estado das novas imagens e containers Kairós ainda exige os gates próprios de release/health; o no-touch não substitui esses gates.

## Firewall e listener no manifesto v1

**Manifesto v1 não autoriza mudar firewall ou listeners.** IPv4/IPv6/NFT são comparados preservando ordem e conteúdo, normalizando apenas contadores e timestamps do iptables-save. Não elimina chains DOCKER/DOCKER-USER, interfaces bridge, regras de porta 4080 nem linhas contendo a palavra Kairós. Reordenação, adição ou remoção de regra compartilhada reprova.

Consequentemente, trocar bind de `0.0.0.0:4080` para `127.0.0.1:4080`, recriar bridges ou acrescentar uma rede parser que altere regras Docker ainda pode reprovar. O resultado informa `firewall_exceptions=false` e `listener_exceptions=false`; isso é um gate explícito pendente, não permissão para ignorar diferenças. Não alterar a captura para retirar linhas que reprovaram.

A evidência de 2026-09-10 em `modernizacao/evidencias/p0p2-baseline.json` identifica nomes das redes, mas não contém atribuição completa de IPs, endpoints, bridges e PortBindings. Por isso a primeira versão não infere que uma regra pertence exclusivamente ao Kairós só porque contém 4080 ou um prefixo Docker.

## Projeção de atribuição

`snapshot-network-ownership.py` é chamado pelo snapshot e grava `network-ownership.json`, incluindo:

- Containers: ID, nome, label de projeto Compose, redes/IPs IPv4/IPv6 e bindings de portas.
- Redes: ID, nome, driver, internal, projeto Compose, opção explícita de bridge, opções de bridge relevantes, subnets/gateways e endpoints com IDs/IPs.

O auxiliar consulta projeções Docker; não solicita `.Config.Env`, `.Config.Cmd` ou argumentos e não imprime secrets. Campos adicionais de aliases, labels arbitrários e options desconhecidas não entram no resultado. Captura todos os containers/redes para detectar compartilhamento e preservar os alheios. Atributos alheios dessa projeção também são comparados; uma rede nomeada Kairós contendo endpoint alheio recebe proteção integral.

A extensão v2 liga cada alteração concreta à porta publicada por container Kairós, IP atribuído e rede exclusiva com driver/options verificados, antes e depois. Deve preservar regras compartilhadas e a ordem das regras restantes, recusar redes compartilhadas e comprovar que nenhum binding alheio foi atingido. Nome de bridge inferido de hash truncado não é prova suficiente quando Docker aceita opção de nome próprio. A extensão permanece sujeita aos testes negativos e à revisão independente antes de habilitar a mudança pública.

## Validação e rollback

```bash
python3 -m unittest discover -s scripts/tests -p test_compare_release_snapshots.py -v
```

Os testes usam arquivos sintéticos e Docker simulado: hashes exatos, Nginx alheio, adições indevidas, paths malformados, inventário ausente, mismatch entre inventários, identidade alheia, listener4080, regra compartilhada/reordenada, contadores, projeção sem secrets e fallback legado.

Nenhum teste local substitui nova captura no VPS e comparação real. Após correção, repetir A/B integralmente conforme AGENTS.md. Não há migration nem alteração produtiva feita pelo comparador. Rollback do deploy deve ter manifesto próprio com hashes invertidos conhecidos para as configurações efetivamente revertidas, preservar novas configurações históricas e manter os mesmos gates de isolamento.


## Manifesto v2: exceções estritamente atribuídas

A captura `p0p2-network-20260910T191239Z`, produzida pelo commit `53d813e58be1cd56ab18a088e2ed906dba4d7779`, acrescentou evidência completa de redes. Foram observadas cinco redes Kairós exclusivas; o binding real do edge nessa captura é somente `0.0.0.0:4080 → 80/tcp`. O namespace IPv6 4080 não estava publicado nesse baseline.

O novo `scripts/release_network_policy.py` não altera firewall, redes, serviços ou snapshots. O comparador v2 exige todos os inventários da v1 e a projeção antes/depois. Exemplo com hashes sintéticos:

```json
{
  "version": 2,
  "release_commit": "cccccccccccccccccccccccccccccccccccccccc",
  "config_changes": [],
  "network_changes": [
    {
      "name": "kairos-parser",
      "before": null,
      "after": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  ],
  "edge_binding_change": {
    "container": "kairos-edge-1",
    "container_port": "80/tcp",
    "host_port": "4080",
    "before": ["0.0.0.0"],
    "after": ["127.0.0.1"]
  }
}
```

`network_changes` enumera cada registro de rede alterado, incluindo alterações dos IDs/IPs de endpoints. O hash é SHA-256 do **registro inteiro** de `network-ownership.json`, serializado por `json.dumps(record, sort_keys=True, separators=(",", ":"))`; `release_network_policy.digest(record)` implementa esse contrato. `null` representa rede ausente, nunca uma regra genérica. Redes extras, entradas repetidas, mudanças não observadas e hashes diferentes do esperado são recusados. O plano precisa nomear as redes e mudanças esperadas; IDs alocados pelo Docker devem ser conferidos contra esse plano antes de fixar o hash final do manifesto operacional, sem aceitar redes adicionais apenas por aparecerem no snapshot posterior.

`edge_binding_change` pode ser `null`. Quando presente, permite somente o container exato, protocolo TCP, porta externa 4080 e destino 80. Origem pública IPv4, opcionalmente acompanhada de `::`, pode tornar-se exclusivamente `127.0.0.1`. Outra porta, alvo, container ou binding adicional é recusado. Um segundo container associado à mesma porta torna a atribuição ambígua e bloqueia a exceção. Listeners são identificados por protocolo, estado, endereço/porta, peer e processo `docker-proxy`; outras linhas permanecem estritas.

### Provas necessárias para uma rede

- Projeto Compose `kairos`, nome Kairós, driver bridge, ID completo único, configuração padrão de bridge e IPv4 RFC1918 suportado (não loopback/reservado).
- Uma subnet/gateway válidos; nenhum overlap ou bridge compartilhado com outra identidade em qualquer um dos dois snapshots.
- Cada endpoint pertence a um container Kairós e consta reciprocamente no inspect do container, com mesmo ID, nome, endereço e rede; IPs duplicados e endpoints alheios são recusados.
- Todo attachment de container Kairós é conhecido e próprio. Configurações de bridge customizadas e IPv6 sem prova implementada bloqueiam a exceção.
- Uma rede adicionada nesta fase deve ser interna. O parser preserva sua rede isolada; não há fallback para conectá-lo à rede pública.

### Regras e ordem

Somente templates Docker exatos, nos pares table/chain corretos, são elegíveis: DROP de endereço próprio no raw, roteamento/DNAT da porta do edge, MASQUERADE da subnet própria, FORWARD/CT/BRIDGE e isolamento das redes internas. Cada regra esperada precisa aparecer exatamente uma vez em **ambas as visões correspondentes**, iptables e nft. A remoção de um DROP, uma duplicação, DNAT ambíguo, ACCEPT ampliado ou divergência entre as duas visões bloqueia.

As demais regras, declarações, políticas, chains e sua ordem ficam intactas; só contadores e timestamps já normalizados pela v1 são ignorados. O comparador preserva também a posição das regras próprias em relação às barreiras globais/customizadas: mover ACCEPT próprio para antes dos jumps DOCKER-CT/DOCKER-INTERNAL/DOCKER-BRIDGE reprova. Reordenação entre regras comprovadamente disjuntas pode ser atribuída ao Docker; política compartilhada ambígua permanece bloqueada. IPv6 continua sem exceção de firewall: precisa permanecer exatamente igual após a normalização de contadores.

O relatório contém redes autorizadas, IDs, bridges, subnets, endpoints, hashes dos registros e hashes dos conjuntos de regras autorizados/protegidos em cada lado. O motivo controlado de rejeição identifica atribuição ambígua sem imprimir configurações secretas. Esse relatório não substitui integridade dos snapshots nem a verificação de commit/imagem implantados.

### Verificação local da extensão

`pytest scripts/tests/test_compare_release_snapshots.py scripts/tests/test_release_network_policy.py -q`: **38 passed**; Ruff passou. Inclui regras alheias alteradas, ACCEPT amplo, mudança de listener alheio, endpoint estrangeiro, subnet compartilhada, endpoint não recíproco, falta/duplicação de proteção, regra em chain errada, cruzamento de jumps globais e porta ambígua.

Os cinco inventários reais de rede de 19:12 foram comparados consigo mesmos: PASS; os demais inventários do fixture permanecem sintéticos e iguais, portanto isso não é uma nova verificação integral do VPS. A evidência local está em `modernizacao/evidencias/p0p2-network-v2-selftest.json`. A mesma captura, com substituição sintética do ID da API e IPs retidos, passou validando os templates reais das redes afetadas. A criação sintética de bridge interno do parser passou com suas três regras completas de isolamento e reprovou quando ampliada para FORWARD externo. Fixtures reais permanecem fora do Git; em outro ambiente o teste da captura pode usar `KAIROS_NETWORK_BASELINE_DIR`, ou ficará explicitamente skipped se a evidência não estiver disponível.

Não houve alteração de firewall, novo snapshot produtivo ou deploy neste sublote. A revisão B independente e a comparação do deploy real ainda são obrigatórias. Rollback que reabra 4080 publicamente não é autorizado por esta exceção direcional; preserve o edge em loopback ou use um plano específico revisado.

### Correções encontradas na revisão B (2026-09-10)

Três reproduções independentes receberam PASS indevido: cruzar uma barreira global com porta negada (`! --dport 8080`) ou texto de comentário confundido com seletor; mover ACCEPT da porta publicada para depois do DROP do próprio bridge; e reiniciar container com nome `kairos-*` mas label de projeto alheio. Foram acrescentados testes negativos antes da correção, e todos falharam pelo PASS indevido esperado.

A atribuição agora interpreta tokens/quotes e negação dos seletores, exige ACCEPT antes do DROP correspondente nas duas visões de firewall, e usa ID+nome+projeto da projeção para filtrar recursos históricos no v2. O nome sozinho não encobre StartedAt/RestartCount de projeto estrangeiro.

Verificação A após correção: `pytest scripts/tests/test_compare_release_snapshots.py scripts/tests/test_release_network_policy.py scripts/tests/test_compose_snapshot.py -q`: **47 passed**, incluindo fixture de cinco inventários reais de rede, comparação consigo mesma e substituição sintética de ID com IP retido. Ruff passou. A tentativa adicional de executar os sete testes históricos `test_no_touch.py` falhou por ausência do executável Bash neste ambiente Windows; não é evidência de falha do comparador Bash nem foi convertida em sucesso. Precisa ser repetida em Linux. As correções invalidam a revisão B anterior: exigem nova revisão independente antes do uso produtivo.
