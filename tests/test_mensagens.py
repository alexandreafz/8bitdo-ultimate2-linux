"""u2ctl in Brazilian Portuguese: its English messages translated when shown."""
import argparse

import pytest

from ultimate2 import cli, discovery, mensagens


@pytest.fixture
def pt(monkeypatch):
    monkeypatch.setattr(mensagens, "LANG", "pt")


def test_follows_the_system_language(monkeypatch):
    monkeypatch.setattr(mensagens, "LANG", None)
    monkeypatch.setenv("LANGUAGE", "pt_BR:pt")
    assert mensagens.tr("restored") == "restaurado"
    monkeypatch.setenv("LANGUAGE", "en_US")
    assert mensagens.tr("restored") == "restored"


def test_exact_patterns_and_unknown(pt):
    t = mensagens.tr
    assert t("back to X") == "de volta ao modo X"
    assert t("battery     91% (discharging)") == "bateria     91% (descarregando)"
    assert t("8BitDo Ultimate wireless: 80% (charging)") == "8BitDo Ultimate wireless: 80% (carregando)"
    assert t("8BitDo: 5% (odd state)") == "8BitDo: 5% (odd state)"          # unknown status word kept
    assert t("saved 1652 bytes to /x.bin") == "1652 bytes salvos em /x.bin"
    assert t("write failed at offset 45") == "a gravação falhou na posição 45"
    assert t("something new") == "something new"
    assert t("restored") == "restaurado" and mensagens.tr("controller  firmware 2.04, battery 50%, colorway 3") == \
        "controle    firmware 2.04, bateria 50%, cor 3"


def test_cli_speaks_portuguese(pt, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: True)
    monkeypatch.setattr(discovery, "bluetooth_u24g", lambda: False)
    cli.main(["list"])
    assert "`u2ctl xmode enter` abre a configuração do modo X" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="rode `u2ctl xmode enter`"):    # a device error, translated on the way out
        cli.main(["info"])
    with pytest.raises(SystemExit):
        cli.main(["xmode"])
    assert "faltam os argumentos: action" in capsys.readouterr().err


def test_device_io_errors_translated_others_left_alone(pt, monkeypatch, tmp_path):
    def broken(argv):
        raise IOError("controller did not confirm the save")
    monkeypatch.setattr(cli, "_main", broken)
    with pytest.raises(SystemExit, match="o controle não confirmou a gravação"):
        cli.main([])

    def missing(argv):
        open(tmp_path / "nope")
    monkeypatch.setattr(cli, "_main", missing)
    with pytest.raises(FileNotFoundError):
        cli.main([])

    def numeric(argv):
        raise SystemExit(3)
    monkeypatch.setattr(cli, "_main", numeric)
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 3


def test_help_is_translated(pt, capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert out.startswith("uso: u2ctl") and "mostra esta ajuda e sai" in out and "opções:" in out
    assert argparse._ is mensagens.tr
