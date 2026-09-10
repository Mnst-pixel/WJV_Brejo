# Gate de release: mudanças explícitas de configuração

`scripts/compare-release-snapshots.py` complementa o comparador histórico. Sem `--manifest`, chama `compare-vps-snapshots.sh` e preserva seu exit code. O script antigo permanece intacto; backup/restore sem mudança de configuração podem continuar a utilizá-lo.

Com manifesto, o novo comparador aceita exclusivamente diferenças de hashes previamente especificadas para paths Kairós exatos. Mantém recursos alheios protegidos e retorna FAIL quando qualquer diferença não corresponde ao plano. Não gera autorização automaticamente a partir do snapshot posterior. Preparar/revisar o manifesto antes do deploy, preservá-lo em arquivo operacional protegido e registrar seu SHA-256; o resultado imprime esse hash e o commit declarado. O comparador verifica consistência das evidências, não confere sozinho se o commit foi implantado nem autentica o autor do manifesto.

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

## Firewall e listener: exceções ainda não habilitadas

**Manifesto v1 não autoriza mudar firewall ou listeners.** IPv4/IPv6/NFT são comparados preservando ordem e conteúdo, normalizando apenas contadores e timestamps do iptables-save. Não elimina chains DOCKER/DOCKER-USER, interfaces bridge, regras de porta 4080 nem linhas contendo a palavra Kairós. Reordenação, adição ou remoção de regra compartilhada reprova.

Consequentemente, trocar bind de `0.0.0.0:4080` para `127.0.0.1:4080`, recriar bridges ou acrescentar uma rede parser que altere regras Docker ainda pode reprovar. O resultado informa `firewall_exceptions=false` e `listener_exceptions=false`; isso é um gate explícito pendente, não permissão para ignorar diferenças. Não alterar a captura para retirar linhas que reprovaram.

A evidência de 2026-09-10 em `modernizacao/evidencias/p0p2-baseline.json` identifica nomes das redes, mas não contém atribuição completa de IPs, endpoints, bridges e PortBindings. Por isso a primeira versão não infere que uma regra pertence exclusivamente ao Kairós só porque contém 4080 ou um prefixo Docker.

## Projeção preparada para atribuição futura

`snapshot-network-ownership.py` é chamado pelo snapshot e grava `network-ownership.json`, incluindo:

- Containers: ID, nome, label de projeto Compose, redes/IPs IPv4/IPv6 e bindings de portas.
- Redes: ID, nome, driver, internal, projeto Compose, opção explícita de bridge, opções de bridge relevantes, subnets/gateways e endpoints com IDs/IPs.

O auxiliar consulta projeções Docker; não solicita `.Config.Env`, `.Config.Cmd` ou argumentos e não imprime secrets. Campos adicionais de aliases, labels arbitrários e options desconhecidas não entram no resultado. Captura todos os containers/redes para detectar compartilhamento e preservar os alheios. Atributos alheios dessa projeção também são comparados; uma rede nomeada Kairós contendo endpoint alheio recebe proteção integral.

Uma futura exceção de firewall precisa ligar cada alteração concreta à porta publicada por container Kairós, IP atribuído e rede exclusiva com driver/options verificados, antes e depois. Deve preservar regras compartilhadas e a ordem das regras restantes, recusar redes compartilhadas e comprovar que nenhum binding alheio foi atingido. Nome de bridge inferido de hash truncado não é prova suficiente quando Docker aceita opção de nome próprio. Essa extensão deve ter novos testes negativos e revisão independente antes de habilitar a mudança pública.

## Validação e rollback

```bash
python3 -m unittest discover -s scripts/tests -p test_compare_release_snapshots.py -v
```

Os testes usam arquivos sintéticos e Docker simulado: hashes exatos, Nginx alheio, adições indevidas, paths malformados, inventário ausente, mismatch entre inventários, identidade alheia, listener4080, regra compartilhada/reordenada, contadores, projeção sem secrets e fallback legado.

Nenhum teste local substitui nova captura no VPS e comparação real. Após correção, repetir A/B integralmente conforme AGENTS.md. Não há migration nem alteração produtiva feita pelo comparador. Rollback do deploy deve ter manifesto próprio com hashes invertidos conhecidos para as configurações efetivamente revertidas, preservar novas configurações históricas e manter os mesmos gates de isolamento.
