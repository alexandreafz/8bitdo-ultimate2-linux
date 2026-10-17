"""Brazilian Portuguese for ``u2ctl``: its messages stay in English in the code (``u2gui`` matches some of the device
errors by their words) and are translated when shown, following the system language like ``u2gui`` does."""
import re

from .gui.i18n import system_lang

LANG = None                      # None = the system language; tests set "en" or "pt"

EXACT = {
    # parser
    "Configure the 8BitDo Ultimate 2 Wireless and the Ultimate 2.4G (mode switch on D) on Linux.":
        "Configura o 8BitDo Ultimate 2 Wireless e o Ultimate 2.4G no Linux.",
    "hidraw node (default: auto-detect)": "nó hidraw (padrão: detecção automática)",
    "list detected devices": "lista os controles detectados",
    "firmware version and active slot": "versão do firmware e perfil ativo",
    "read config as JSON": "lê a configuração em JSON",
    "write edited JSON back": "grava de volta um JSON editado",
    "turn slot 0-2 into a custom profile with app defaults": "cria no perfil 0-2 um perfil com os padrões do app",
    "show or set the active LED theme (Ultimate 2 only)": "mostra ou muda o tema de LED ativo (só Ultimate 2)",
    "Ultimate 2.4G on X: open its config channel (enter) or go back to X (leave)":
        "Ultimate 2.4G no modo X: abre a configuração (enter) ou volta ao modo X (leave)",
    "battery of the controller over Bluetooth (Ultimate 2.4G)": "bateria do controle no Bluetooth (Ultimate 2.4G)",
    "keep Ultimate 2.4G pads on X read so they stay connected (systemd user service)":
        "mantém o Ultimate 2.4G no modo X sendo lido para não desligar (serviço de usuário do systemd)",
    "save raw config record": "salva a configuração bruta num arquivo",
    "write raw config record": "grava no controle uma configuração bruta",
    # argparse's own words
    "usage: ": "uso: ",
    "positional arguments": "argumentos",
    "options": "opções",
    "show this help message and exit": "mostra esta ajuda e sai",
    "the following arguments are required: %s": "faltam os argumentos: %s",
    "%(prog)s: error: %(message)s\n": "%(prog)s: erro: %(message)s\n",
    "invalid choice: %(value)r (choose from %(choices)s)": "opção inválida: %(value)r (escolha entre %(choices)s)",
    "unrecognized arguments: %s": "argumentos não reconhecidos: %s",
    # messages
    "warning: the controller is also connected over Bluetooth, which uses the D-mode configuration: changes made "
    "here (X mode) do not apply there":
        "atenção: o controle também está conectado pelo Bluetooth, que usa a configuração do modo D: o que for mudado "
        "aqui (modo X) não vale nele",
    "Ultimate 2.4G in X mode: `u2ctl xmode enter` opens its X configuration (or set the switch to D)":
        "Ultimate 2.4G no modo X: `u2ctl xmode enter` abre a configuração do modo X (ou coloque a chave em D)",
    "Ultimate 2.4G over Bluetooth: no configuration channel there, use the USB cable (switch on D)":
        "Ultimate 2.4G no Bluetooth: por ali não dá para configurar, use o cabo USB (chave em D)",
    "no 8BitDo controller reporting its battery: it is only known over Bluetooth (the 2.4G receiver does not report "
    "it)":
        "nenhum controle 8BitDo informando a bateria: ela só é conhecida pelo Bluetooth (o receptor 2.4G não a informa)",
    "no write access to the controller's USB node: reinstall the package (udev rule) and replug it":
        "sem permissão no USB do controle: reinstale o pacote (regra udev) e reconecte o controle",
    "no Ultimate 2.4G on X found, or it did not open its config mode":
        "nenhum Ultimate 2.4G no modo X encontrado, ou ele não abriu a configuração",
    "config mode open (X configuration); `u2ctl xmode leave` goes back to X":
        "configuração aberta (modo X); `u2ctl xmode leave` volta ao modo X",
    "no answer from controller": "o controle não respondeu",
    "changed:": "alterado:",
    "(nothing)": "(nada)",
    "saved and verified": "salvo e verificado",
    "verify failed: controller config differs from what was written":
        "verificação falhou: a configuração do controle difere do que foi gravado",
    "back to X": "de volta ao modo X",
    "verify failed: controller config differs from the backup":
        "verificação falhou: a configuração do controle difere do backup",
    "restored": "restaurado",
    # device errors
    "8BitDo Ultimate 2.4G found in X mode: run `u2ctl xmode enter` to open its X configuration (or set the switch on "
    "its back to D)":
        "8BitDo Ultimate 2.4G no modo X: rode `u2ctl xmode enter` para abrir a configuração do modo X (ou coloque a "
        "chave de trás em D)",
    "8BitDo Ultimate 2.4G connected over Bluetooth, which has no configuration channel: connect the USB cable "
    "(switch on D) to configure it":
        "8BitDo Ultimate 2.4G conectado pelo Bluetooth, que não permite configurar: ligue o cabo USB (chave em D) "
        "para configurá-lo",
    "no 8BitDo config interface found (is the controller plugged in / paired?)":
        "nenhum controle 8BitDo configurável encontrado (ele está conectado?)",
    "controller did not confirm the save": "o controle não confirmou a gravação",
    "controller did not confirm the LED theme": "o controle não confirmou o tema de LED",
}

STATUS = {"discharging": "descarregando", "charging": "carregando", "full": "carregada",
          "not charging": "sem carregar", "unknown": "desconhecido"}

PATTERNS = [(re.compile(rx), pt) for rx, pt in (
    (r"^battery     (\d+)% \((.+)\)$", "bateria     {0}% ({1:status})"),
    (r"^(.+): (\d+)% \((.+)\)$", "{0}: {1}% ({2:status})"),
    (r"^device      (.+)$", "dispositivo {0}"),
    (r"^report pid  (.+)$", "pid         {0}"),
    (r"^mode/slot   (.+)$", "modo/perfil {0}"),
    (r"^controller  firmware (\S+), battery (\d+)%, colorway (\S+)$", "controle    firmware {0}, bateria {1}%, cor {2}"),
    (r"^the (.+) has no X/D modes$", "o {0} não tem modos X/D"),
    (r"^the (.+) has no LED themes$", "o {0} não tem temas de LED"),
    (r"^unknown \((.*)\)$", "desconhecido ({0})"),
    (r"^saved (\d+) bytes to (.+)$", "{0} bytes salvos em {1}"),
    (r"^(.+): expected (\d+) bytes for the (.+), got (\d+)$", "{0}: esperados {1} bytes para o {2}, mas tem {3}"),
    (r"^permission denied on (.+): install udev/70-8bitdo-u2.rules \(see README\)$",
     "sem permissão em {0}: instale a regra udev/70-8bitdo-u2.rules (veja o README)"),
    (r"^read failed at offset (\d+)$", "a leitura falhou na posição {0}"),
    (r"^write failed at offset (\d+)$", "a gravação falhou na posição {0}"),
)]


def tr(text):
    """``text`` in the user's language (English unless the system is in Portuguese)."""
    if (LANG or system_lang()) != "pt":
        return text
    if text in EXACT:
        return EXACT[text]
    for rx, pt in PATTERNS:
        m = rx.match(text)
        if m:
            groups = list(m.groups())
            for i in range(len(groups)):                # a "{n:status}" slot takes the battery status word
                if "{%d:status}" % i in pt:
                    pt = pt.replace("{%d:status}" % i, "{%d}" % i)
                    groups[i] = STATUS.get(groups[i], groups[i])
            return pt.format(*groups)
    return text
