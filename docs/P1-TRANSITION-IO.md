# Inspeção local e registros protegidos da transição

`release_transition_io.py` complementa o modelo puro, sem executar comandos de implantação. `collect` usa `/usr/bin/docker --host unix:///var/run/docker.sock`, ambiente mínimo, timeout, limite de saída e campos fixos. A projeção de rede é lida novamente para detectar mudança durante a coleta. Não lê Env, Cmd, mounts ou secrets. Imagens alheias não são inspecionadas: suas identidades observadas são preservadas, incluindo containers cuja imagem foi retirada do catálogo Docker externo.

`freeze` valida o plano e o snapshot integral antes de criar um diretório exclusivo. `plan.json`, `before.json`, `baseline.json` e `FROZEN.json` têm modo 0600, O_EXCL/O_NOFOLLOW, hashes e fsync. A cadeia de diretórios é conferida até a raiz contra symlinks, donos indevidos e escrita de terceiros; o /tmp root-owned com sticky bit é permitido para fixtures isoladas, sem modificar /tmp global.

O manifesto do snapshot deve enumerar exatamente seu conteúdo. Arquivos opcionais, como release-config-hashes.txt, não podem ser acrescentados fora dele. Regenerar um manifesto após alteração também muda seu vínculo com o freeze. Hardlinks e arquivos expostos são recusados.

`before_mutation` revalida os registros, estado Docker e configurações declaradas e grava STARTED.json uma vez. `seal` exige esse registro, confere o estado posterior e passa pelo comparador integral antes de gravar RECEIPT.json uma vez. Um resultado parcial ou uma falha não cria recibo de sucesso. O coordenador ainda deve fazer snapshot completo fresco/recomparação sob `.operation.lock` antes da primeira mutação: STARTED sozinho não prova ausência de drift contemporâneo de firewall, listeners, volumes ou serviços.

Compatibilidade com o estado real: retenção preserva containers parados com endereço vazio; não autoriza ativar/desativar seus endpoints. IPv6 não declarado é recusado também em attachments inativos. Labels OCI legadas ausentes podem permanecer vazias; imagem e metadados observados continuam exatos, e aplicações novas/substituídas exigem a revision da release.

Testes locais e Linux, hashes de fonte, coleta real e ensaio sem mudanças constam em P3-P6-ENTREGA. O ensaio não é deploy nem prova manutenção, drenagem de filas, privilégios do banco, restore, migration, cutover ou rollback. Esses são os próximos componentes do coordenador, conforme P1-CUTOVER-PENDING.

Sem migration. Rollback desta biblioteca não altera dados ou recursos; preservar os registros emitidos como evidência. Não entregar essas funções para endpoints web, agentes IA ou chamadas arbitrárias de ferramentas. A integração futura deve usar somente raízes fixas e entradas protegidas do operador de release; parâmetros substituíveis de raízes e de coletor existem para as fixtures de teste.
