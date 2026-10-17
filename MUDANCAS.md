# O que mudou em relação ao original

Comparação entre o original **8bitdo-ultimate2-linux 0.1.0-beta.6** (commit `7257f07`, guardado sem alterações) e o
estado atual (`0.1.0b6+u24g7`). Para ver as linhas exatas: `git diff 7257f07 HEAD -- <arquivo>`.

**Resumo:** 36 arquivos, 27 modificados e 9 novos, +2.048 / −114 linhas; nenhum arquivo removido. Todas as mudanças
acrescentam suporte ao **8BitDo Ultimate 2.4G**; o comportamento com o Ultimate 2 Wireless continua o mesmo.

## Código do programa (`src/ultimate2/`)

| Arquivo | Situação | Linhas | O que mudou |
| --- | --- | --- | --- |
| `protocol.py` | modificado | +61 | Classe `Model` (Ultimate 2 e Ultimate 2.4G); formato de pacote do 2.4G (`81 <tamanho> 04 …`); CRC `0x8408`; leitura da versão; PIDs `3012`/`3013`/`3106`; `describe()` |
| `discovery.py` | modificado | +36 −2 | Aceita o 2.4G pelo PID quando o descritor tem o relatório `0x81`; detecta modo X (`3106`) e Bluetooth; `connected_model()` |
| `device.py` | modificado | +64 −23 | Pacote, tamanho do registro (1652), salvar (`0x15`) e tempos conforme o modelo; resposta conferida pelo offset; perfil ativo lido antes de gravar; avisos de modo X e Bluetooth |
| `config.py` | modificado | +106 −13 | Layout do registro de 1652 bytes; códigos de tecla do 2.4G; nome do perfil em UTF-16LE; registros de macro; perfil novo igual ao do app oficial; `same()` |
| `cli.py` | modificado | +42 −12 | Comandos `u2ctl xmode enter|leave`, `u2ctl keepalive` e `u2ctl battery`; mensagens por modelo; `theme` recusado no 2.4G |
| `xmode.py` | **novo** | +87 | Abre a configuração do modo X pelo USB (sequência do Windows: `02 08 03` + vibração) e volta com `81 05 00 51 02` |
| `battery.py` | **novo** | +31 | Bateria do controle no Bluetooth (lida do kernel) |
| `keepalive.py` | **novo** | +50 | Mantém o controle em X sendo lido para não desligar ao trocar de perfil |
| `__init__.py` | modificado | +1 −1 | Versão `0.1.0b6+u24g6` |

## Interface gráfica (`src/ultimate2/gui/`)

| Arquivo | Linhas | O que mudou |
| --- | --- | --- |
| `app.py` | +12 −7 | Escolhe o modelo ao abrir; título pelo modelo; estado do modo X; devolve ao X ao fechar |
| `catalog.py` | +14 | Seções, botões e funções do 2.4G (sem Giroscópio, LEDs, L4/R4); `for_model()` |
| `controller.py` | +15 −12 | Desenho sem L4/R4 e sem anéis de LED no 2.4G; P1/P2 rotulados; gatilhos e analógicos na numeração do modelo |
| `editor.py` | +25 −8 | Carrega e grava só as seções que o modelo tem |
| `live_input.py` | +14 −5 | Numeração dos botões no modo D (2.4G) além da do `xpad` |
| `pages.py` | +11 −6 | Páginas e textos por modelo; sem vibração nos gatilhos no 2.4G |
| `sync.py` | +77 −13 | Reinicia a janela se aparecer outro modelo; abre/fecha o modo X; avisos de modo X e Bluetooth; verificação do registro inteiro no 2.4G; janela de erro copiável |
| `widgets.py` | +40 | `error_dialog()`: mensagem de erro selecionável com botão Copiar |
| `i18n.py` | +10 | Traduções das mensagens novas |

## Sistema e empacotamento

| Arquivo | Situação | O que mudou |
| --- | --- | --- |
| `udev/70-8bitdo-u2.rules` | modificado (+2) | Também dá ao usuário logado acesso ao nó USB dos aparelhos 8BitDo |
| `packaging/ultimate2-keepalive.service` | **novo** | Serviço de usuário do systemd que roda `u2ctl keepalive` |
| `packaging/build-deb.sh` | modificado | Instala o serviço; `postinst` aplica a regra aos USB e ativa o serviço; aceita versões `+u24gN`; descrição do pacote |
| `pyproject.toml` | modificado | Versão e descrição |

## Testes (`tests/`)

| Arquivo | Situação | O que mudou |
| --- | --- | --- |
| `test_u24g.py` | **novo** (+539) | Protocolo, registro, transporte, CLI, descoberta, Bluetooth, `xmode`, `keepalive` |
| `gui/test_u24g_gui.py` | **novo** (+239) | Interface no modo 2.4G, modo X, Bluetooth |
| `fake_device.py` | modificado | O emulador de firmware também responde como o 2.4G |
| `conftest.py` | modificado | Nenhum teste enxerga controles reais conectados |
| `gui/conftest.py`, `gui/test_widgets.py` | modificados | Modelo fixo nos testes antigos; testes da janela de erro |
| `test_cli.py`, `test_device.py` | 1–2 linhas | Mensagem e assinatura ajustadas |

Resultado: 270 → 323 testes, cobertura de 100%.

## Ferramentas (`tools/`, novas)

| Arquivo | Para quê |
| --- | --- |
| `probe_u24g.py` | Teste só de leitura do 2.4G: versão e registro, salvo em arquivo |
| `xmode_switch.py` | Experimento que reproduz a captura do Windows para abrir o modo X (precisa de root) |
| `xmode_handshake.py` | Experimento anterior, sem efeito; mantido como registro |

## Documentação

| Arquivo | O que mudou |
| --- | --- |
| `docs/PROTOCOL.md` | Seção "8BitDo Ultimate 2.4G": modos, pacotes, registro, Bluetooth, abertura do modo X, keepalive |
| `README.md` | Parágrafo sobre o Ultimate 2.4G |
| `CHANGELOG.md` | Entrada `0.1.0-beta.6+u24g6` |
| `CONTRIBUTING.md` | Como rodar os testes sem GLX |
| `MUDANCAS.md` | Este arquivo |
