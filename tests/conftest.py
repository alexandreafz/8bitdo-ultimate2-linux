import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_device import FakeController  # noqa: E402

BLANK_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "blank_config.bin")


@pytest.fixture
def fake(monkeypatch):
    f = FakeController().install(monkeypatch)
    yield f
    f.close()


@pytest.fixture(autouse=True)
def no_real_hardware(request, monkeypatch, tmp_path):
    """Tests never see the controllers plugged into the machine running them (test_discovery sets its own roots)."""
    from ultimate2 import discovery
    if request.module.__name__ == "test_discovery":
        return
    monkeypatch.setattr(discovery, "SYS", str(tmp_path / "no-sys"))


@pytest.fixture(autouse=True)
def cli_in_english(monkeypatch):
    """u2ctl follows the system language; the tests read its English text unless they pick Portuguese."""
    from ultimate2 import mensagens
    monkeypatch.setattr(mensagens, "LANG", "en")
