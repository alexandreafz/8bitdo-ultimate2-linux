"""8BitDo Ultimate 2.4G (Ultimate Software V1's PID_Ultimate2_4): protocol, record, transport, CLI and discovery.

The expected bytes come from the hardware (2dc8:3012, firmware 2.04, mode switch on D) and from 8BitDoAdvance.dll.
"""
import json
import os
import struct

import pytest

from fake_device import FakeController
from ultimate2 import cli, config, discovery, protocol as p
from ultimate2.device import Device

SIZE = p.U24G_CFG_SIZE
# the record of a controller that never had a custom profile: erased flash, gamepad_mode 1 (D), cur_slot 4
BLANK = b"\xff" * 16 + bytes([1, 0, 4, 0]) + b"\xff" * (SIZE - 20)


@pytest.fixture
def u24(monkeypatch):
    f = FakeController(cfg=BLANK, firmware=204, usb_pid=0x3012).install(monkeypatch)
    yield f
    f.close()


@pytest.fixture
def fast(monkeypatch):
    orig = Device.recv
    monkeypatch.setattr(Device, "recv", lambda self, cmd, timeout=0.5, **kw: orig(self, cmd, min(timeout, 0.2), **kw))


def run(*args):
    cli.main(list(args))


# ------------------------------------------------------------ protocol
def test_constants_and_models():
    assert (p.U24G_CFG_SIZE, p.U24G_COMMIT_KEY) == (1652, 0x15)
    assert set(p.U24G_PIDS) == {0x3012, 0x3013} and set(p.U24G_XINPUT_PIDS) == {0x3106}
    assert p.model_for_pid(0x3012) is p.model_for_pid(0x3013) is p.U24G
    assert p.model_for_pid(0x310B) is p.model_for_pid(0) is p.U2
    assert p.model_for_size(1652) is p.U24G and p.model_for_size(1592) is p.U2 and p.model_for_size(3) is None
    assert (p.U2.leds, p.U2.gyro, p.U2.toggles_reports) == (True, True, True)
    assert (p.U24G.leds, p.U24G.gyro, p.U24G.toggles_reports) == (False, False, False)
    assert p.describe(0x3106) == "Ultimate 2.4G (X)" and p.describe(0x6013) == "2.4G dongle"
    assert p.describe(0x1234) == "?" and p.describe(0x1234, "0x1234") == "0x1234"


def test_build_request_u24g_matches_the_wire():
    # the header read that the controller answered
    assert p.build_request_u24g(p.CMD_READ, total=20, length=20)[:24].hex(" ") == \
        "81 25 04 02 00 00 00 14 00 00 00 14 00 00 00 00 00 00 00 00 00 00 00 00"
    pkt = p.build_request_u24g(p.CMD_COMMIT, sub=0x15)
    assert len(pkt) == 64 and pkt[:19] == bytes([0x81, 17, 4, 6, 0, 0x15, 0]) + bytes(12)
    pkt = p.build_request_u24g(p.CMD_WRITE, data=b"abc", total=SIZE, offset=45)
    assert pkt[1] == 20 and struct.unpack_from("<HHIII", pkt, 3) == (1, 0, 3, SIZE, 45) and pkt[19:22] == b"abc"


def test_crc16_u24g():
    assert p.crc16_u24g(BLANK) == 0x10FE                 # value computed for the controller's own record
    assert p.crc16_u24g(b"") == 0xFFFF


def test_parse_version_u24g():
    assert p.parse_version_u24g(bytes.fromhex("0222cc0000001230")) == {"firmware": 204, "beta": 0, "device_pid": 0x3012}


# ------------------------------------------------------------ record
def test_decode_blank():
    d = config.decode(BLANK)
    assert (d["model"], d["gamepad_mode"], d["cur_slot"], d["crc_value"]) == ("u24g", 1, 4, 0xFFFFFFFF)
    s = d["slots"][0]
    assert s["flag"] == "0xffffffff" and s["name"] == "" and s["rumble"]["left"] is None
    assert s["macros"] == {"flag": "0xffffffff", "total_cnt": 255, "records": "erased"}
    assert list(s["mapping"])[1:] == config.BUTTONS_U24G and s["mapping"]["A"] == "0xffffffff"
    assert "sixaxis" not in s and "led_dynamic" not in s and "xinput_rumble" not in s
    assert "model" not in config.decode(b"\xff" * p.CFG_SIZE)


def test_default_slot_like_the_app():
    doc = config.default_slot(config.decode(BLANK), 1, "Linux")
    s = doc["slots"][1]
    assert s["flag"] == s["mapping"]["flag"] == s["macros"]["flag"] == "enabled"
    assert [s["mapping"][b] for b in config.BUTTONS_U24G] == ["A", "B", "X", "Y", "LB", "RB", "LT", "RT", "L3", "R3",
        "Select", "Start", "Menu", "Home", "Up", "Down", "Left", "Right", "None", "None"]
    assert s["sticks"] == dict(flag="enabled", left_start=0, left_end=128, right_start=0, right_end=128)
    assert s["triggers"] == dict(flag="enabled", left_start=0, left_end=255, right_start=0, right_end=255)
    assert s["rumble"] == dict(flag="enabled", left=1.0, right=1.0) and s["macros"]["records"] == "empty"
    sw = config.decode(BLANK)
    sw["gamepad_mode"] = 0
    assert config.default_slot(sw, 0, "x")["slots"][0]["mapping"]["Star"] == "Screenshot"


def test_encode_layout_codes_name_and_crc():
    doc = config.default_slot(config.decode(BLANK), 0, "Perfil ação")
    doc["slots"][0]["mapping"].update(A="B", B="A", P1="Home", P2="RT")
    new, changed = config.encode(doc, BLANK)
    o = 224 + 4
    assert struct.unpack_from("<20I", new, o)[:2] == (0x1000, 0x2000)
    assert struct.unpack_from("<I", new, o + 4 * 18)[0] == 0x20000 and struct.unpack_from("<I", new, o + 4 * 19)[0] == 0x8000
    assert new[20:52] == "Perfil ação".encode("utf-16-le").ljust(32, b"\0")       # UTF-16LE, not BE
    assert new[476:480] == struct.pack("<I", 0x20200911) and new[480] == 0 and new[484:868] == bytes(384)
    assert new[868:1652] == BLANK[868:]                                           # other slots untouched
    crc_in = bytearray(new)
    crc_in[12:16] = BLANK[12:16]
    assert struct.unpack_from("<I", new, 12)[0] == p.crc16_u24g(crc_in)          # over the record as it stood
    assert "slots/0/macros/records" in changed and config.decode(new)["slots"][0]["name"] == "Perfil ação"


def test_macro_records_and_unknown_codes():
    buf = bytearray(BLANK)
    buf[484 + 10] = 7                                       # something written by the app
    struct.pack_into("<I", buf, 228, 0x40000)               # a code the table does not know
    d = config.decode(bytes(buf))
    assert d["slots"][0]["macros"]["records"] == "custom" and d["slots"][0]["mapping"]["A"] == "0x00040000"
    d["slots"][0]["macros"]["records"] = "erased"
    d["slots"][0]["mapping"]["A"] = "0x00000010"
    new = config.encode(d, bytes(buf))[0]
    assert new[484:868] == b"\xff" * 384 and struct.unpack_from("<I", new, 228)[0] == 0x10
    d = config.decode(new)
    d["slots"][0]["name"] = "a" * 20                        # cut to 16 characters
    d["slots"][1]["mapping"]["Home"] = "Swap"
    new = config.encode(d, new)[0]
    assert config.decode(new)["slots"][0]["name"] == "a" * 16
    assert struct.unpack_from("<I", new, 224 + 84 + 4 + 4 * 13)[0] == 0x8000000
    named = bytearray(new)
    named[20:52] = "ab".encode("utf-16-le").ljust(32, b"\0")
    assert config.decode(bytes(named))["slots"][0]["name"] == "ab"
    named[20:52] = ("x" * 16).encode("utf-16-le")           # no terminator
    assert config.decode(bytes(named))["slots"][0]["name"] == "x" * 16


def test_changed_span_and_same():
    new = config.encode(config.default_slot(config.decode(BLANK), 2, "z"), BLANK)[0]
    a, b = config.changed_span(BLANK, new)
    assert (a, b) == (8, SIZE)                                # slot 2 flag .. its macro records, last in the record
    other = bytearray(new)
    other[12:16] = b"\x05\0\0\0"                             # the firmware's save counter
    other[18:20] = b"\x01\0"                                 # and its own active profile
    assert config.same(new, bytes(other)) and not config.same(new, BLANK)
    other[16] = 0
    assert not config.same(new, bytes(other))
    u2 = b"\xff" * p.CFG_SIZE
    assert config.same(u2, u2) and not config.same(u2, b"\0" + u2[1:]) and not config.same(new, u2)


# ------------------------------------------------------------ transport
def test_device_status(u24):
    d = Device()
    try:
        assert d.model is p.U24G and d.pid == 0x3012
        assert d.info() == {"firmware": 204, "beta": 0, "device_pid": 0x3012}
        assert d.edition() is None and d.pad_status() is None and d.get_theme() is None
        with pytest.raises(IOError, match="no LED themes"):
            d.set_theme(2)
        assert d.current_slot() == 4
        assert d.read_config() == BLANK
        d.report(False)                                      # nothing sent: the app never toggles reports here
        assert all(e[0] == p.CMD_READ for e in u24.log)
    finally:
        d.close()


def test_device_info_no_answer(u24, monkeypatch):
    monkeypatch.setattr(Device, "query", lambda self, raw, want=None, timeout=.5: None)
    d = Device()
    try:
        assert d.info() is None
    finally:
        d.close()


def test_write_is_always_the_whole_record_and_commit_0x15(u24):
    new = config.encode(config.default_slot(config.decode(BLANK), 0, "x"), BLANK)[0]
    d = Device()
    try:
        d.write_config(new, 300, 310)                         # a range is ignored: writeUltimate2_4 sends it all
        writes = [e for e in u24.log if e[0] == p.CMD_WRITE]
        assert writes[0][3] == 0 and sum(e[2] for e in writes) == SIZE and max(e[2] for e in writes) == p.CHUNK
        assert u24.log[-1][:2] == (p.CMD_COMMIT, 0x15)
        got = d.read_config()
        assert struct.unpack_from("<I", got, 12)[0] == 1 and config.same(new, got)
    finally:
        d.close()


def test_write_without_commit_answer(u24, fast):
    u24.silent.add(p.CMD_COMMIT)
    d = Device()
    try:
        with pytest.raises(IOError, match="did not confirm the save"):
            d.write_config(BLANK)
    finally:
        d.close()


def test_x_mode_hint(monkeypatch):
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: True)
    with pytest.raises(SystemExit, match="run `u2ctl xmode enter`"):
        Device()


# ------------------------------------------------------------ CLI
def test_cli_list_info_dump(u24, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: True)
    run("list")
    out = capsys.readouterr().out
    assert "2dc8:3012  Ultimate 2.4G (cable, config)" in out and "`u2ctl xmode enter` opens its X configuration" in out
    run("info")
    out = capsys.readouterr().out
    assert "Ultimate 2.4G (cable, config), Ultimate 2.4G" in out and "firmware    2.04" in out and "cur_slot=4" in out
    run("dump")
    assert json.loads(capsys.readouterr().out)["model"] == "u24g"


def test_cli_new_slot_apply_and_theme(u24, capsys, tmp_path):
    run("new-slot", "0", "--name", "Linux")
    assert "saved and verified" in capsys.readouterr().out
    assert config.decode(bytes(u24.cfg))["slots"][0]["name"] == "Linux" and u24.saves == 1
    doc = config.decode(bytes(u24.cfg))
    doc["slots"][0]["mapping"]["A"] = "B"
    f = tmp_path / "e.json"
    f.write_text(json.dumps(doc))
    run("apply", str(f))
    assert "saved and verified" in capsys.readouterr().out and config.decode(bytes(u24.cfg))["slots"][0]["mapping"]["A"] == "B"
    with pytest.raises(SystemExit, match="no LED themes"):
        run("theme")


def test_cli_backup_restore(u24, capsys, tmp_path):
    f = tmp_path / "b.bin"
    run("backup", str(f))
    assert f.read_bytes() == BLANK and f"saved {SIZE} bytes" in capsys.readouterr().out
    run("restore", str(f))
    assert "restored" in capsys.readouterr().out and u24.saves == 1
    short = tmp_path / "s.bin"
    short.write_bytes(b"\xff" * p.CFG_SIZE)
    with pytest.raises(SystemExit, match="expected 1652 bytes for the Ultimate 2.4G, got 1592"):
        run("restore", str(short))


# ------------------------------------------------------------ discovery
USB_DESC = b"\x05\x01\x09\x05\xa1\x01\x85\x03\x85\x02\x09\x02\x85\x81\x09\x03\xc0"   # gamepad + config reports 0x02/0x81
BT_DESC = b"\x05\x01\x09\x05\xa1\x01\x85\x03\x85\x05\x09\x70\xc0"    # the same pad over Bluetooth: gamepad + rumble only


def _hidraw(sys_, idx, pid, desc, bus=3):
    usb = sys_ / "devices" / f"usb{idx}" / "3-3"
    hid = usb / "3-3:1.0" / f"{bus:04X}:2DC8:{pid:04X}.000{idx}"
    hid.mkdir(parents=True)
    (hid / "uevent").write_text(f"HID_ID={bus:04X}:00002DC8:0000{pid:04X}\n")
    (hid / "report_descriptor").write_bytes(desc)
    cls = sys_ / "class" / "hidraw" / f"hidraw{idx}"
    cls.mkdir(parents=True)
    (cls / "device").symlink_to(hid)


def _event(sys_, idx, product):
    dev = sys_ / "devices" / "input" / f"input{idx}"
    dev.mkdir(parents=True)
    (dev / "uevent").write_text(f"PRODUCT={product}\nNAME=\"x\"\n")
    ev = sys_ / "class" / "input" / f"event{idx}"
    ev.mkdir(parents=True)
    (ev / "device").symlink_to(dev)


def test_discovery_u24g_by_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    monkeypatch.setattr(discovery, "DEV", "/devx")
    assert discovery.connected_model() is p.U2 and not discovery.xinput_u24g()
    _event(tmp_path, 1, "3/2dc8/3106/114")
    assert discovery.xinput_u24g() and discovery.connected_model() is p.U24G
    _hidraw(tmp_path, 2, 0x3012, USB_DESC)                  # gamepad that also carries the config reports
    _hidraw(tmp_path, 3, 0x3105, b"\x05\x01\x09\x05")      # another 8BitDo pad: no config channel
    assert [(x[0], x[1]) for x in discovery.find_devices()] == [("/devx/hidraw2", 0x3012)]
    assert discovery.connected_model() is p.U24G
    _hidraw(tmp_path, 1, 0x310B, b"\x06\x7a\xff")
    assert discovery.connected_model() is p.U2               # the first one found


def test_xinput_ignores_other_pads(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    _event(tmp_path, 4, "3/045e/0b13/1")
    assert not discovery.xinput_u24g()
    assert os.path.isdir(tmp_path / "class" / "input")


def test_late_answers_with_another_offset_are_skipped(u24):
    u24.stale = 6                                            # answers echoing a wrong offset arrive first
    d = Device()
    try:
        assert d.read_config() == BLANK
        new = config.encode(config.default_slot(config.decode(BLANK), 0, "x"), BLANK)[0]
        u24.stale = 6
        d.write_config(new)
        assert config.same(new, d.read_config()) and u24.stale == 0
    finally:
        d.close()


def test_write_keeps_the_controllers_active_profile(u24):
    u24.cfg[18:20] = u24.pending[18:20] = b"\x01\0"           # the profile button was pressed after the read
    new = config.encode(config.default_slot(config.decode(BLANK), 0, "x"), BLANK)[0]   # still says cur_slot 4
    d = Device()
    try:
        d.write_config(new)
        assert struct.unpack_from("<H", bytes(u24.cfg), 18)[0] == 1 and config.same(new, d.read_config())
        u24.silent.add(p.CMD_READ)                           # no answer to the slot read: the record goes as is
        u24.pending[18:20] = b"\x02\0"
        d.write_config(new)
        assert struct.unpack_from("<H", bytes(u24.cfg), 18)[0] == 4
    finally:
        d.close()


def test_bluetooth_is_not_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    _hidraw(tmp_path, 1, 0x3012, BT_DESC, bus=5)
    assert list(discovery.find_devices()) == [] and discovery.bluetooth_u24g()
    assert discovery.connected_model() is p.U24G
    with pytest.raises(SystemExit, match="over Bluetooth, which has no configuration channel"):
        Device()
    _hidraw(tmp_path, 2, 0x3012, USB_DESC)                  # the cable plugged in too: that one is used
    assert [x[1] for x in discovery.find_devices()] == [0x3012]


def test_bluetooth_detection_ignores_others(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    _hidraw(tmp_path, 1, 0x3012, USB_DESC)                  # USB
    _hidraw(tmp_path, 2, 0x6012, BT_DESC, bus=5)            # another model over Bluetooth
    assert not discovery.bluetooth_u24g()


def test_cli_list_bluetooth_hint(monkeypatch, capsys):
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: False)
    monkeypatch.setattr(discovery, "bluetooth_u24g", lambda: True)
    run("list")
    assert "over Bluetooth: no configuration channel there" in capsys.readouterr().out


# ------------------------------------------------------------ X mode (Windows sequence over usbfs)
from ultimate2 import xmode  # noqa: E402


def _usbdev(sys_, name, vid, pid, bus, dev):
    d = sys_ / "bus" / "usb" / "devices" / name
    d.mkdir(parents=True)
    for k, v in (("idVendor", vid), ("idProduct", pid), ("busnum", bus), ("devnum", dev)):
        (d / k).write_text(f"{v}\n")


@pytest.fixture
def usbfs(tmp_path, monkeypatch):
    """Fake sysfs with a 2dc8:3106 pad, fake usbfs ioctls (recorded) and no sleeping."""
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    _usbdev(tmp_path, "3-1", "046d", "c52b", 3, 2)
    _usbdev(tmp_path, "3-3", "2dc8", "3106", 3, 9)
    _usbdev(tmp_path, "usb3", "", "", "", "")
    calls, opened = [], []
    real_open = os.open
    monkeypatch.setattr(xmode.os, "open", lambda path, flags: opened.append(path) or real_open(os.devnull, os.O_RDWR))

    def ioctl(fd, req, arg, mutate=False):
        if req == xmode.USBDEVFS_BULK:
            ptr = struct.unpack_from("III4xP", arg)
            calls.append(("out", ctypes.string_at(ptr[3], ptr[1])))
        else:
            calls.append((req, struct.unpack_from("i", arg)[0] if req != xmode.USBDEVFS_IOCTL else struct.unpack_from("ii", arg)[1]))
        return 0
    import ctypes
    monkeypatch.setattr(xmode.fcntl, "ioctl", ioctl)
    monkeypatch.setattr(xmode, "sleep", lambda s: None)
    monkeypatch.setattr(xmode, "DEV_BUS", "/devx/bus/usb")
    return calls, opened


def test_xmode_finds_the_pad_on_x(usbfs):
    assert xmode.find_xinput_node() == "/devx/bus/usb/003/009"


def test_xmode_enter_sends_the_windows_sequence(usbfs, monkeypatch):
    calls, opened = usbfs
    seen = iter([[], [("/dev/hidraw9", 0x3013, "/x")]])
    monkeypatch.setattr(discovery, "find_devices", lambda: iter(next(seen)))
    assert xmode.enter() is True and opened == ["/devx/bus/usb/003/009"]
    outs = [c[1] for c in calls if c[0] == "out"]
    assert outs[:4] == [bytes.fromhex(h) for h in ("010302", "020803", "010302", "010306")]
    knock = [bytes([0, 8, 0, l, r, 0, 0, 0]) for l, r in ((1, 0), (0, 1), (1, 1), (5, 1), (0, 0))]
    assert outs[4:] == knock * 3
    assert calls[0] == (xmode.USBDEVFS_IOCTL, xmode.USBDEVFS_DISCONNECT) and calls[-1] == (xmode.USBDEVFS_IOCTL, xmode.USBDEVFS_CONNECT)


def test_xmode_enter_without_pad_timeout_and_gone(usbfs, monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    assert xmode.enter(timeout=0.01) is False                  # never re-enumerated with a config channel

    def gone(fd, req, arg, mutate=False):                      # re-enumerated already: release/connect fail
        if req in (xmode.USBDEVFS_RELEASEINTERFACE,):
            raise OSError(19, "No such device")
        return 0
    monkeypatch.setattr(xmode.fcntl, "ioctl", gone)
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([("/dev/hidraw9", 0x3012, "/x")]))
    assert xmode.enter() is True
    monkeypatch.setattr(discovery, "SYS", str(tmp_path / "empty"))
    assert xmode.enter() is False and xmode.find_xinput_node() is None


def test_xmode_enter_without_permission(usbfs, monkeypatch):
    def denied(path, flags):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(xmode.os, "open", denied)
    with pytest.raises(PermissionError):
        xmode.enter()


def test_xmode_leave_writes_back_to_x():
    r, w = os.pipe()
    try:
        xmode.leave(type("D", (), {"fd": w})())
        assert os.read(r, 64) == b"\x81\x05\x00\x51\x02".ljust(64, b"\0")
    finally:
        os.close(r)
        os.close(w)


def test_cli_xmode(monkeypatch, capsys):
    monkeypatch.setattr(xmode, "enter", lambda: True)
    run("xmode", "enter")
    assert "config mode open (X configuration)" in capsys.readouterr().out
    monkeypatch.setattr(xmode, "enter", lambda: False)
    with pytest.raises(SystemExit, match="did not open its config mode"):
        run("xmode", "enter")

    def denied():
        raise PermissionError
    monkeypatch.setattr(xmode, "enter", denied)
    with pytest.raises(SystemExit, match="reinstall the package"):
        run("xmode", "enter")


def test_cli_xmode_leave(u24, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(xmode, "leave", lambda dev: sent.append(dev.pid))
    run("xmode", "leave")
    assert sent == [0x3012] and "back to X" in capsys.readouterr().out


def test_cli_xmode_leave_other_model(fake):
    with pytest.raises(SystemExit, match="has no X/D modes"):
        run("xmode", "leave")



# ------------------------------------------------------------ keepalive (xpad only polls while someone reads)
from ultimate2 import keepalive  # noqa: E402


def _js(sys_, idx, product):
    dev = sys_ / "devices" / "input" / f"js-input{idx}"
    dev.mkdir(parents=True)
    (dev / "uevent").write_text(f"PRODUCT={product}\n")
    js = sys_ / "class" / "input" / f"js{idx}"
    js.mkdir(parents=True)
    (js / "device").symlink_to(dev)


def test_keepalive_finds_only_8bitdo_pads_on_x(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(keepalive, "DEV", "/devx/input")
    _js(tmp_path / "sys", 0, "3/2dc8/3106/114")
    _js(tmp_path / "sys", 1, "3/045e/028e/114")
    _js(tmp_path / "sys", 2, "3/2dc8/3012/200")
    assert keepalive.find_nodes() == ["/devx/input/js0"]


def test_keepalive_holds_drains_and_reopens(tmp_path, monkeypatch):
    sys_, dev = tmp_path / "sys", tmp_path / "dev"
    dev.mkdir()
    monkeypatch.setattr(discovery, "SYS", str(sys_))
    monkeypatch.setattr(keepalive, "DEV", str(dev))
    for i in range(4):
        _js(sys_, i, "3/2dc8/3106/114")
    (dev / "js0").write_bytes(b"\x01" * 16)            # events, then EOF: the pad went away -> reopened later
    (dev / "js1").mkdir()                              # read error -> closed
    (dev / "js2").write_bytes(b"")
    os.chmod(dev / "js2", 0)                           # not readable yet -> skipped
    os.mkfifo(dev / "js3")                             # a quiet pad: open, nothing to read -> kept
    writer = os.open(dev / "js3", os.O_RDWR)
    opened, closed = [], []
    real_open, real_close = os.open, os.close

    def track_open(path, flags):
        fd = real_open(path, flags)                    # raises for js2 (no permission) and js3 (missing)
        opened.append((os.path.basename(path), fd))
        return fd
    monkeypatch.setattr(keepalive.os, "open", track_open)
    monkeypatch.setattr(keepalive.os, "close", lambda fd: closed.append(fd) or real_close(fd))
    keepalive.run(rounds=3, scan=0.01)
    os.close(writer)
    names = [n for n, _fd in opened]
    assert names.count("js3") == 1                     # quiet but there: held the whole time
    assert names.count("js0") == 2                     # held in round 1, EOF in round 2, reopened in round 3
    assert names.count("js1") == 3                     # read error: closed and retried every round
    assert "js2" not in names or os.getuid() == 0      # unreadable: skipped
    closed.remove(writer)                              # the test's own writer end
    assert sorted(fd for _n, fd in opened) == sorted(closed)   # everything closed in the end


def test_keepalive_without_pads_just_waits(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    slept = []
    monkeypatch.setattr(keepalive.time, "sleep", slept.append)
    keepalive.run(rounds=2, scan=0.5)
    assert slept == [0.5, 0.5]


def test_cli_keepalive(monkeypatch):
    calls = []
    monkeypatch.setattr(keepalive, "run", lambda: calls.append(1))
    run("keepalive")
    assert calls == [1]


def test_keepalive_runs_until_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    ticks = []

    def sleep(s):
        ticks.append(s)
        if len(ticks) == 3:
            raise KeyboardInterrupt                    # how the service is stopped
    monkeypatch.setattr(keepalive.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        keepalive.run()
    assert ticks == [1.0, 1.0, 1.0]



# ------------------------------------------------------------ battery (Bluetooth only)
from ultimate2 import battery  # noqa: E402


def _supply(sys_, name, hid_dir, uevent):
    dev = sys_ / "devices" / "virtual" / "misc" / "uhid" / hid_dir
    dev.mkdir(parents=True, exist_ok=True)
    ps = sys_ / "class" / "power_supply" / name
    ps.mkdir(parents=True)
    (ps / "device").symlink_to(dev)
    (ps / "uevent").write_text(uevent)


def test_battery_over_bluetooth(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SYS", str(tmp_path))
    assert battery.bluetooth() is None
    _supply(tmp_path, "hid-00:11:22:33:44:55-battery", "0005:054C:09CC.0001",          # another vendor's pad
            "POWER_SUPPLY_CAPACITY=50\nPOWER_SUPPLY_STATUS=Discharging\n")
    _supply(tmp_path, "hid-e4:17:d8:00:00:00-battery", "0005:2DC8:3012.0009",          # no report yet
            "POWER_SUPPLY_STATUS=Unknown\n")
    assert battery.bluetooth() is None
    _supply(tmp_path, "hid-e4:17:d8:00:00:01-battery", "0005:2DC8:3012.000A",
            "POWER_SUPPLY_NAME=hid-e4:17:d8:00:00:01-battery\nPOWER_SUPPLY_CAPACITY=92\n"
            "POWER_SUPPLY_STATUS=Discharging\nPOWER_SUPPLY_MODEL_NAME=8BitDo Ultimate wireless\nnoise\n")
    assert battery.bluetooth() == {"capacity": 92, "status": "Discharging", "name": "8BitDo Ultimate wireless"}


def test_cli_battery(monkeypatch, capsys):
    monkeypatch.setattr(battery, "bluetooth", lambda: {"capacity": 91, "status": "Discharging", "name": "8BitDo X"})
    run("battery")
    assert "8BitDo X: 91% (discharging)" in capsys.readouterr().out
    monkeypatch.setattr(discovery, "find_devices", lambda: iter([]))
    monkeypatch.setattr(discovery, "xinput_u24g", lambda: False)
    monkeypatch.setattr(discovery, "bluetooth_u24g", lambda: True)
    run("list")
    assert "battery     91% (discharging)" in capsys.readouterr().out
    monkeypatch.setattr(battery, "bluetooth", lambda: None)
    run("list")
    assert "battery" not in capsys.readouterr().out
    with pytest.raises(SystemExit, match="only known over Bluetooth"):
        run("battery")
