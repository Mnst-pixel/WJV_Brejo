# P0 — dependências Python da imagem candidata

Data da consulta: 2026-09-10. Esta entrega é uma alteração de dependências existentes; não adiciona biblioteca funcional nem aplica alteração ao VPS. A revisão independente e os testes Linux da imagem reconstruída são gates separados.

Prova de imagem em 21:19 UTC: a candidata `sha256:8407f1b0a48ce449623766c7bea707f1bc73fd39466540acc1affeb1c0f1826c` contém cryptography 50.0.1, Pillow 12.3.0, pip 26.2.1 e nenhum bleach. `pip check` passou no build. OpenSSL do sistema é 3.5.7 (pacotes Debian `3.5.7-1~deb13u2`), OpenSSL embarcado em cryptography é 4.0.2; lxml usa libxml2 2.14.6 compilada/efetiva, não a libxml2 Debian. Inventário completo protegido: `modernizacao/evidencias/p0p2-runtime-sbom.json`. Essa é uma imagem de teste, não a imagem ainda implantada.

## Alteração e motivo

O Dockerfile de release também atualiza `openssl`, `libssl3t64` e `openssl-provider-legacy` para `3.5.7-1~deb13u2`, conforme o [Debian Security Tracker](https://security-tracker.debian.org/tracker/source-package/openssl). A imagem observada tinha `3.5.4-1~deb13u2`. O build instala versões exatas no container; não atualiza pacotes do host. A prova efetiva de instalação e o inventário final dependem do build Linux. Zero alertas OSV Python não significa zero vulnerabilidades nos pacotes do sistema operacional.

`scripts/build-foundations.sh` recebe fonte exportada de commit, usa a imagem base SHA registrada e produz tags imutáveis por commit para API/parser. Os três wheels são fornecidos fora do Git e conferidos pelo lock SHA256; o build recusa sobrescrever uma tag candidata existente. A origem completa de `core`, `kairos`, entrypoint, manage e legado é comparada com a fonte versionada no teste do artefato; árvores herdadas são removidas antes do COPY para impedir módulos obsoletos sobreviventes.

| Componente existente | Inicial observado | Candidato | Decisão |
| --- | --- | --- | --- |
| cryptography | 45.0.7 | 50.0.1 | Corrige avisos de memória, validação criptográfica e OpenSSL embarcado. |
| Pillow | 11.3.0 | 12.3.0 | Corrige avisos de memória e decodificação de formatos não confiáveis. |
| pip | 25.3 na imagem base | 26.2.1 | Atualiza o instalador já presente; corrige extração, entry points e URLs de pacotes. |
| bleach | 6.2.0 | Removido | Nenhum import/uso no repositório; projeto oficialmente sem manutenção. Não se mantém uma dependência vulnerável sem uso. |
| cffi | 2.1.1 | 2.1.1 | Dependência existente satisfaz cryptography 50 (`cffi>=2.0.0`); sem alteração. |

A busca no código encontra cryptography no mecanismo Fernet de MFA; não demonstrou exploração das rotas X.509/PKCS#7. Pillow processa PNG/JPEG validados no parser isolado. Nem todo aviso abaixo é alcançável pela aplicação, mas o pacote distribuído deve ser corrigido. A remoção de bleach não substitui uma política de sanitização usada: nenhuma chamada ao pacote foi encontrada. O sandbox, limites e allowlist do parser continuam necessários após o upgrade.

## Origem, licença e manutenção

- [PyPI cryptography](https://pypi.org/project/cryptography/50.0.1/) e [changelog oficial](https://cryptography.io/en/latest/changelog/): versão estável 50.0.1; Apache-2.0 OR BSD-3-Clause. Compatível com CPython 3.13 e ABI3; distribuição binária inclui OpenSSL atualizado.
- [PyPI Pillow](https://pypi.org/project/pillow/12.3.0/) e [release notes oficiais](https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html): versão estável 12.3.0, Python>=3.10; MIT-CMU.
- [PyPI pip](https://pypi.org/project/pip/26.2.1/) e [changelog oficial](https://pip.pypa.io/en/stable/news/): 26.2.1, Python>=3.10; MIT.
- [Projeto Bleach](https://pypi.org/project/bleach/): Apache-2.0, sem manutenção desde 2026-06-05; eliminado. A correção técnica dos dois avisos existe em 6.4.0, mas não resolve o estado de manutenção.

Licenças permissivas dos componentes já existentes permanecem compatíveis com sua distribuição, preservando os avisos e arquivos de licença das wheels. Não houve adoção de um serviço externo ou nova biblioteca.

## Avisos e faixas afetadas

A consulta OSV da imagem base observou 55 distribuições Python. Quatro pacotes foram sinalizados. Registros GHSA e PYSEC que são aliases foram deduplicados por GHSA nesta tabela; a contagem de registros da API não é a contagem de vulnerabilidades independentes. As faixas abaixo são as dos registros GHSA consultados, não uma afirmação de explorabilidade de cada fluxo do Kairós.

| Pacote | Aviso | CVE | Faixa afetada registrada |
| --- | --- | --- | --- |
| bleach | [GHSA-8rfp-98v4-mmr6](https://osv.dev/vulnerability/GHSA-8rfp-98v4-mmr6) | Sem CVE no registro | 0 ≤ versão < 6.4.0 |
| bleach | [GHSA-gj48-438w-jh9v](https://osv.dev/vulnerability/GHSA-gj48-438w-jh9v) | Sem CVE no registro | 0 ≤ versão < 6.4.0 |
| cryptography | [GHSA-537c-gmf6-5ccf](https://osv.dev/vulnerability/GHSA-537c-gmf6-5ccf) | Sem CVE no registro | 0.5.0 ≤ versão < 48.0.1 |
| cryptography | [GHSA-g6cj-pr64-35w5](https://osv.dev/vulnerability/GHSA-g6cj-pr64-35w5) | CVE-2026-69247 | 44.0.0 ≤ versão < 50.0.0 |
| cryptography | [GHSA-jwv3-5hgf-82ww](https://osv.dev/vulnerability/GHSA-jwv3-5hgf-82ww) | CVE-2026-69249 | 42.0.0 ≤ versão < 49.0.0 |
| cryptography | [GHSA-m2h6-j472-rp4c](https://osv.dev/vulnerability/GHSA-m2h6-j472-rp4c) | CVE-2026-69248 | 45.0.0 ≤ versão < 49.0.0 |
| cryptography | [GHSA-m959-cc7f-wv43](https://osv.dev/vulnerability/GHSA-m959-cc7f-wv43) | CVE-2026-34073 | 0 ≤ versão < 46.0.6 |
| cryptography | [GHSA-p423-j2cm-9vmq](https://osv.dev/vulnerability/GHSA-p423-j2cm-9vmq) | CVE-2026-39892 | 45.0.0 ≤ versão < 46.0.7 |
| cryptography | [GHSA-r6ph-v2qm-q3c2](https://osv.dev/vulnerability/GHSA-r6ph-v2qm-q3c2) | CVE-2026-26007 | 0 ≤ versão < 46.0.5 |
| pillow | [GHSA-45hq-cxwh-f6vc](https://osv.dev/vulnerability/GHSA-45hq-cxwh-f6vc) | CVE-2026-55379 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-4x4j-2g7c-83w6](https://osv.dev/vulnerability/GHSA-4x4j-2g7c-83w6) | CVE-2026-55798 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-5x94-69rx-g8h2](https://osv.dev/vulnerability/GHSA-5x94-69rx-g8h2) | CVE-2026-54060 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-5xmw-vc9v-4wf2](https://osv.dev/vulnerability/GHSA-5xmw-vc9v-4wf2) | CVE-2026-42309 | 11.2.1 ≤ versão < 12.2.0 |
| pillow | [GHSA-62p4-gmf7-7g93](https://osv.dev/vulnerability/GHSA-62p4-gmf7-7g93) | CVE-2026-54058 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-6r8x-57c9-28j4](https://osv.dev/vulnerability/GHSA-6r8x-57c9-28j4) | CVE-2026-59199 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-8v84-f9pq-wr9x](https://osv.dev/vulnerability/GHSA-8v84-f9pq-wr9x) | CVE-2026-54059 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-9hw9-ch79-4vh6](https://osv.dev/vulnerability/GHSA-9hw9-ch79-4vh6) | CVE-2026-59205 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-cfh3-3jmp-rvhc](https://osv.dev/vulnerability/GHSA-cfh3-3jmp-rvhc) | CVE-2026-25990 | 10.3.0 ≤ versão < 12.1.1 |
| pillow | [GHSA-fj7v-r99m-22gq](https://osv.dev/vulnerability/GHSA-fj7v-r99m-22gq) | CVE-2026-59198 | 5.2.0 ≤ versão < 12.3.0 |
| pillow | [GHSA-jjj6-mw9f-p565](https://osv.dev/vulnerability/GHSA-jjj6-mw9f-p565) | CVE-2026-59200 | 5.1.0 ≤ versão < 12.3.0 |
| pillow | [GHSA-phj9-mv4w-65pm](https://osv.dev/vulnerability/GHSA-phj9-mv4w-65pm) | CVE-2026-55380 | 0 ≤ versão < 12.3.0 |
| pillow | [GHSA-pwv6-vv43-88gr](https://osv.dev/vulnerability/GHSA-pwv6-vv43-88gr) | CVE-2026-42311 | 10.3.0 ≤ versão < 12.2.0 |
| pillow | [GHSA-r73j-pqj5-w3x7](https://osv.dev/vulnerability/GHSA-r73j-pqj5-w3x7) | CVE-2026-42310 | 4.2.0 ≤ versão < 12.2.0 |
| pillow | [GHSA-vjc4-5qp5-m44j](https://osv.dev/vulnerability/GHSA-vjc4-5qp5-m44j) | CVE-2026-59204 | 8.2.0 ≤ versão < 12.3.0 |
| pillow | [GHSA-whj4-6x5x-4v2j](https://osv.dev/vulnerability/GHSA-whj4-6x5x-4v2j) | CVE-2026-40192 | 10.3.0 ≤ versão < 12.2.0 |
| pillow | [GHSA-wjx4-4jcj-g98j](https://osv.dev/vulnerability/GHSA-wjx4-4jcj-g98j) | CVE-2026-42308 | 0 ≤ versão < 12.2.0 |
| pillow | [GHSA-xj96-63gp-2gmr](https://osv.dev/vulnerability/GHSA-xj96-63gp-2gmr) | CVE-2026-59197 | 0 ≤ versão < 12.3.0 |
| pip | [GHSA-58qw-9mgm-455v](https://osv.dev/vulnerability/GHSA-58qw-9mgm-455v) | CVE-2026-3219 | 0 ≤ versão < 26.1 |
| pip | [GHSA-6vgw-5pg2-w6jp](https://osv.dev/vulnerability/GHSA-6vgw-5pg2-w6jp) | CVE-2026-1703 | 0 ≤ versão < 26.0 |
| pip | [GHSA-jp4c-xjxw-mgf9](https://osv.dev/vulnerability/GHSA-jp4c-xjxw-mgf9) | CVE-2026-6357 | 0 ≤ versão < 26.1 |
| pip | [GHSA-qwm4-qh6w-59xr](https://osv.dev/vulnerability/GHSA-qwm4-qh6w-59xr) | CVE-2026-13346 | 0 ≤ versão < 26.2.0 |
| pip | [GHSA-wf93-45jw-7689](https://osv.dev/vulnerability/GHSA-wf93-45jw-7689) | CVE-2026-8643 | 0 ≤ versão < 26.1.2 |

A composição candidata contém 54 distribuições (remoção de bleach, três upgrades). Uma nova consulta de **todas as 54 versões, incluindo transitivas**, não retornou avisos OSV em 2026-09-10. Isso não prova ausência absoluta de vulnerabilidades e não cobre os pacotes Debian, o frontend ou outros serviços. O inventário candidato ainda exige confirmação no artefato construído.

## Reprodutibilidade e evidências

- `apps/api/requirements.txt`: pins da aplicação; bleach removido.
- `apps/api/requirements.runtime.lock`: três upgrades binários com SHA256, incluindo pip como ferramenta preexistente. Este arquivo não é um lock integral de todas as transitivas; complementa a imagem base fixa cujo inventário foi capturado.
- `config/python-runtime-inventory.json`: inventário inicial observado, candidato explicitamente marcado como não implantado, nomes/URLs/tamanhos/SHA256 das três wheels.
- As wheels ficam fora do Git em `modernizacao/ops/runtime-wheels`; nomes aceitos estão no lock/inventário. O build deve copiar somente esses artefatos, conferir hashes e executar instalação offline com `--no-deps --require-hashes --no-index`. Nunca usar um glob para aceitar artefatos não declarados.
- A remoção de bleach no build deve ser seguida de `python -m pip check`; conflito de dependência reprova a imagem. O teste local já passou após a remoção.
- Evidências fora do Git: `p0p2-api-packages.json`, `p0p2-api-package-inventory.json`, `p0p2-base-api-all-python-osv.json`, `p0p2-selected-osv-details.json`, `p0p2-pip-osv-details.json`, `p0p2-proposed-api-all-python-osv.json`, `p0p2-runtime-wheels.json`, `p0p2-runtime-compatibility.json`. Metadados PyPI foram preservados junto dessas evidências.

## Verificação A local

Ambiente Windows CPython 3.12 isolado, sem acesso ao VPS. Instalados cryptography 50.0.1, Pillow 12.3.0, pip 26.2.1; cffi 2.1.1 preservado; bleach removido.

- `python -m pip check`: PASS, nenhuma dependência quebrada.
- Um token Fernet sintético foi gerado com cryptography 45.0.7 **antes** do upgrade e decifrado com 50.0.1: PASS. Token adulterado recusado: PASS. Novo roundtrip: PASS. Chave/token sintéticos ficam fora do Git; nenhum segredo real foi lido.
- PNG e JPEG sintéticos gerados em memória, `Image.open().verify()` e carga integral com Pillow 12.3.0: PASS.
- `pytest --ds=kairos.test_settings tests/test_mfa_security.py tests/test_mfa_concurrency.py tests/test_auth_rbac.py tests/test_http_auth.py tests/test_upload_security.py tests/test_upload_pipeline_live.py tests/test_upload_admin.py -q`: **72 passed, 12 skipped**. Skips explícitos: imagem construída, PostgreSQL/Redis, ClamAV e fixtures live isoladas. Não contam como evidência desses ambientes.
- `python -m unittest discover -s services/parser -p test_parser.py -v`: **2 passed, 9 skipped**, pois seccomp, processo OCR e `/tmp` privado exigem Linux.

## Gates restantes, deploy e rollback

Nenhuma migration. Ainda é obrigatório construir as imagens API/parser com estes artefatos, executar `pip check`, comparar o inventário efetivo ao candidato, repetir MFA/HTTP e upload/ClamAV/OCR/seccomp em Linux e realizar verificação B independente. Não declarar implantação ou P0 completo a partir dos testes Windows.

O commit e os digests finais serão registrados pela entrega de release após build e validação. Rollback operacional usa os digests anteriores e o manifesto protegido previamente capturado; não há regravação de segredos MFA ou migração de dados causada por este lote. Retornar à imagem anterior reintroduz as dependências sinalizadas e deve ser apenas uma contingência temporária documentada.
