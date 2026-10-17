"""u2gui built for the 8BitDo Ultimate 2.4G (mode switch on D): no gyro/LED pages, 20 buttons, its js numbering."""
import struct

import pytest

from fake_device import FakeController
from ultimate2 import config, device, discovery, protocol
from ultimate2.gui import app as app_mod

from .conftest import clear_timers, make_app, pump, texts

SIZE = protocol.U24G_CFG_SIZE
BLANK = b"\xff" * 16 + bytes([1, 0, 4, 0]) + b"\xff" * (SIZE - 20)
THREAD = app_mod.threading.Thread


def new_app(monkeypatch):
    """make_app(), then device workers run again (the joystick reader was skipped at construction)."""
    a = make_app(monkeypatch)
    monkeypatch.setattr(app_mod.threading, "Thread", THREAD)
    return a


@pytest.fixture
def u24(monkeypatch):
    f = FakeController(cfg=BLANK, firmware=204, usb_pid=0x3012).install(monkeypatch)
    yield f
    f.close()


@pytest.fixture
def ua(u24, monkeypatch, fast):
    """A fresh App built for the 2.4G that has read the fake controller."""
    monkeypatch.setattr(app_mod.discovery, "connected_model", lambda: protocol.U24G)
    a = new_app(monkeypatch)
    a.read_device()
    pump(a)
    yield a
    pump(a)
    clear_timers(a)
    a.destroy()


def test_pages_buttons_and_texts(ua):
    assert ua.model is protocol.U24G and ua.title() == "8BitDo Ultimate 2.4G — Linux"
    assert set(ua.pages) == {"home", "buttons", "sticks", "triggers", "rumble", "profile"}
    assert ua.buttons == config.BUTTONS_U24G and set(ua.v["keys"]) == set(config.BUTTONS_U24G)
    parts = set(ua.map_items)
    assert {"P1", "P2"} <= parts and not {"P3", "P4"} & parts
    home = texts(ua.home_canvas)
    assert "Ultimate 2.4G" not in home and "L4" not in home and "R4" not in home
    assert "Traseiros P2 / P1" in home and "P1" in home and "PR" not in home
    assert not any(leds for c, leds in ua.led_items)                      # no LED rings drawn
    assert "D-input" in ua.info_label.cget("text") and "Ultimate 2.4G (cable, config)" in ua.info_label.cget("text")
    assert ua.fw_label.cget("text") == "firmware 2.04" and ua.active_slot == 4


def test_empty_profile_then_autosave_writes_the_whole_record(ua, u24):
    assert not ua.v["enabled"].get() and ua.v["keys"]["Star"].get() == "Menu" and ua.v["sticks"]["left_start"].get() == 0
    ua.v["keys"]["A"].set("B")
    pump(ua, lambda: ua._save_job is None and not ua.busy, timeout=10)
    writes = [e for e in u24.log if e[0] == protocol.CMD_WRITE]
    assert sum(e[2] for e in writes) == SIZE and u24.saves == 1
    assert ua.status.cget("text").startswith("✓ Salvo")                  # the save counter is not a mismatch
    assert ua.base == bytes(u24.cfg)                                      # base follows the controller
    s = config.decode(bytes(u24.cfg))["slots"][0]
    assert s["flag"] == "enabled" and s["mapping"]["A"] == "B" and s["mapping"]["P1"] == "None"
    assert struct.unpack_from("<I", bytes(u24.cfg), 12)[0] == 1           # the firmware's own crc_value
    ua.v["rumble_l"].set(2)
    pump(ua, lambda: ua._save_job is None and not ua.busy, timeout=10)
    assert config.decode(bytes(u24.cfg))["slots"][0]["rumble"]["left"] == pytest.approx(.4) and u24.saves == 2
    assert ua.status.cget("text").startswith("✓ Salvo")


def test_creating_profile_3_saves_without_a_verify_error(ua, u24, dlg):
    ua.select_slot(2)
    ua.v["rumble_r"].set(4)
    pump(ua, lambda: ua._save_job is None and not ua.busy, timeout=10)
    s = config.decode(bytes(u24.cfg))["slots"][2]
    assert s["flag"] == "enabled" and s["name"] == "Perfil 3" and s["rumble"]["right"] == pytest.approx(.8)
    assert ua.status.cget("text").startswith("✓ Salvo") and not dlg.errors


def test_save_that_does_not_stick_is_reported(ua, u24, dlg):
    u24.corrupt_commit = True
    ua.v["keys"]["B"].set("X")
    pump(ua, lambda: ua._save_job is None and not ua.busy, timeout=10)
    assert "verificação falhou" in ua.status.cget("text") and dlg.errors


def test_load_existing_profile(u24, monkeypatch, fast):
    doc = config.default_slot(config.decode(BLANK), 0, "Meu")
    doc["slots"][0]["mapping"]["P2"] = "TurboAuto"
    doc["slots"][0]["mapping"]["Home"] = "Swap"                           # not offered: shows the default
    u24.cfg[:] = u24.pending[:] = config.encode(doc, BLANK)[0]
    monkeypatch.setattr(app_mod.discovery, "connected_model", lambda: protocol.U24G)
    a = new_app(monkeypatch)
    try:
        a.read_device()
        pump(a)
        assert a.v["enabled"].get() and a.v["name"].get() == "Meu"
        assert a.v["keys"]["P2"].get() == "TurboAuto" and a.v["keys"]["Home"].get() == "Home"
        a.select_button("P2")
        assert a.map_title.cget("text") == "Botão P2"
    finally:
        clear_timers(a)
        a.destroy()


def test_live_input_uses_the_d_mode_numbering(ua):
    ua.pad_event(1, 1, 3)                                  # js button 3 = X
    ua.pad_event(1, 1, 12)                                 # 12 = Home
    ua.pad_event(1, 1, 15)                                 # unmapped
    assert ua.pad_down == {"X", "Home"}
    ua.pad_event(32767, 2, 4)                              # axis 4 = RT, 5 = LT
    ua.pad_event(-32767, 2, 5)
    assert "RT" in ua.pad_down and "LT" not in ua.pad_down
    assert ua.trigger_level("RT") == 1 and ua.trigger_level("LT") == 0 and ua.trigger_level("A") is None
    ua.pad_axes.update({2: 32767, 3: 0})                   # right stick on axes 2/3
    ua.show("buttons")
    ua.animate()
    assert ua.map_items["R3"]["off"][0] > 0


def test_another_model_restarts_the_window(u24, monkeypatch, fast):
    monkeypatch.setattr(app_mod.discovery, "connected_model", lambda: protocol.U2)     # e.g. plugged in later
    a = new_app(monkeypatch)
    destroyed = []
    monkeypatch.setattr(a, "destroy", lambda: destroyed.append(1))
    a.read_device()
    pump(a, lambda: destroyed)
    assert a.restart is True and a.doc is None
    clear_timers(a)
    app_mod.tk.Tk.destroy(a)


def test_x_mode_status(monkeypatch, fast):
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: True)
    a = new_app(monkeypatch)
    try:
        assert a.model is protocol.U24G
        a.read_device()
        pump(a)
        assert "modo X" in a.status.cget("text") and a._retry_job
    finally:
        clear_timers(a)
        a.destroy()


def test_bluetooth_status(monkeypatch, fast):
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: False)
    monkeypatch.setattr(discovery, "bluetooth_u24g", lambda: True)
    a = new_app(monkeypatch)
    try:
        assert a.model is protocol.U24G
        a.read_device()
        pump(a)
        assert "Bluetooth" in a.status.cget("text") and "cabo USB" in a.status.cget("text") and a._retry_job
    finally:
        clear_timers(a)
        a.destroy()


def test_x_mode_opens_the_x_configuration(monkeypatch, fast):
    from ultimate2 import xmode
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: True)
    monkeypatch.setattr(xmode, "enter", lambda: True)
    a = new_app(monkeypatch)
    reads = []
    try:
        a.read_device()
        monkeypatch.setattr(a, "read_device", lambda retry=False: reads.append(retry))
        pump(a, lambda: reads)
        assert a.xmode_open and a.xmode_tried
    finally:
        clear_timers(a)
        a.xmode_open = False
        a.destroy()


def test_x_mode_open_fails(monkeypatch, fast):
    from ultimate2 import xmode
    a = new_app(monkeypatch)
    try:
        def denied():
            raise PermissionError
        monkeypatch.setattr(xmode, "enter", denied)
        a.enter_xmode()
        pump(a)
        assert "reinstale o pacote" in a.status.cget("text") and not a.xmode_open
        monkeypatch.setattr(xmode, "enter", lambda: False)
        a.enter_xmode()
        pump(a)
        assert "modo X" in a.status.cget("text")
    finally:
        clear_timers(a)
        a.destroy()


def test_closing_puts_it_back_on_x(u24, monkeypatch, fast):
    from ultimate2 import xmode
    sent = []
    monkeypatch.setattr(xmode, "leave", lambda dev: sent.append(dev.pid))
    a = new_app(monkeypatch)
    a.leave_xmode()                                       # did not open it: nothing to do
    assert sent == []
    a.xmode_open = True
    clear_timers(a)
    a.destroy()
    assert sent == [0x3012] and not a.xmode_open


def test_leaving_x_mode_when_the_pad_is_gone(monkeypatch, fast):
    from ultimate2 import device as dmod, xmode
    a = new_app(monkeypatch)
    a.xmode_open = True
    monkeypatch.setattr(dmod, "Device", lambda *x: (_ for _ in ()).throw(SystemExit("no device")))
    a.leave_xmode()
    assert not a.xmode_open

    class Dev:
        pid, closed = 0x3013, False

        def close(self):
            Dev.closed = True
    monkeypatch.setattr(dmod, "Device", lambda *x: Dev())

    def broken(dev):
        raise OSError(19, "gone")
    monkeypatch.setattr(xmode, "leave", broken)
    a.xmode_open = True
    a.leave_xmode()
    assert Dev.closed
    clear_timers(a)
    a.destroy()


def test_bluetooth_status_shows_the_battery(monkeypatch, fast):
    from ultimate2 import battery
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: False)
    monkeypatch.setattr(discovery, "bluetooth_u24g", lambda: True)
    monkeypatch.setattr(battery, "bluetooth", lambda: {"capacity": 91, "status": "Discharging", "name": "8BitDo"})
    a = new_app(monkeypatch)
    try:
        a.read_device()
        pump(a)
        assert "Bateria: 91%." in a.status.cget("text")
        assert "91%" in [a.pill.itemcget(i, "text") for i in a.pill.find_withtag("battery")]
        assert a.fw_label.cget("text") == ""                      # no firmware known over Bluetooth
    finally:
        clear_timers(a)
        a.destroy()

