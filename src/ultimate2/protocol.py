"""Wire protocol of the controller's vendor HID channel (reverse-engineered from 8BitDoAdvance.dll).

Every report is 64 bytes. Requests start with ``81 04`` followed by a 16-byte header and up to
:data:`CHUNK` data bytes; answers start with ``02 04`` and echo the request command:

    header = u16 cmd, u16 sub, u16 len, u16 crc16(data), u32 total, u32 offset

See ``docs/PROTOCOL.md`` for the full description.
"""
import struct

VID = 0x2DC8
PIDS = {0x310B: "wired (XInput)", 0x6012: "Ultimate 2", 0x6013: "2.4G dongle"}
CFG_SIZE = 1592          # sizeof(custom_config_record_t_u2)
CHUNK = 45               # max payload per packet (61-byte frame - 16-byte header)
REPORT_SIZE = 64

CMD_WRITE, CMD_READ, CMD_COMMIT, CMD_REPORT = 1, 2, 6, 7
CMD_SET_THEME, CMD_GET_THEME = 0x40, 0x41
CMD_INFO = 0x0100
COMMIT_KEY = 0x123       # sub-command of CMD_COMMIT that persists the record to flash
THEMES = {2: "dynamic", 3: "hotwheel", 4: "custom", 5: "off"}   # active LED theme (global, not per slot)

QUERY_VERSION = b"\x81\x05\x00\x21\x01"   # answer starts 02 22; byte 6 = colorway (edition)
ANSWER_VERSION = b"\x02\x22"
# through the 2.4G dongle (it reports PID 0x6013), the controller itself: the app's getControllerVersion_CMD.
# Answer: byte 18 battery %, 19-20 firmware x100, 21 beta, 23 colorway; no answer when wired or switched off
QUERY_PAD = b"\x81\x04\x21\x01\x00\x00\x06"
ANSWER_PAD = b"\x02\x04\x04\x00\x21\x01"


def crc16(data):
    """CRC-16/MODBUS (reflected 0xA001, init 0xFFFF) — used for packets and the config record."""
    c = 0xFFFF
    for b in data:
        for _ in range(8):
            c = (c >> 1) ^ (0xA001 if (c ^ b) & 1 else 0)
            b >>= 1
    return c


# ---------------------------------------------------------------- 8BitDo Ultimate 2.4G (the first Ultimate)
# Reverse-engineered from 8BitDo Ultimate Software V1 (8BitDoAdvance.dll: readUltimate2_4/writeUltimate2_4,
# PID_Ultimate2_4). The config interface only exists with the mode switch on the back set to D; on X the controller
# is an XInput pad (2dc8:3106, xpad) without it.
U24G_PIDS = {0x3012: "Ultimate 2.4G (cable, config)", 0x3013: "Ultimate 2.4G receiver (config)"}
U24G_XINPUT_PIDS = {0x3106: "Ultimate 2.4G (X)"}
U24G_CFG_SIZE = 1652     # sizeof(custom_config_record_t) of Ultimate2_4Advance
U24G_COMMIT_KEY = 0x15   # sub-command of CMD_COMMIT (the DLL's FUN_103c63b0(6, 0x15))


def build_request_u24g(cmd, sub=0, data=b"", total=0, offset=0, length=None):
    """64-byte request of the Ultimate 2.4G: byte 1 is the size of what follows (the DLL's FUN_103c6d60), and the
    header has a 32-bit length and no CRC: ``81 n 04 | u16 cmd | u16 sub | u32 len | u32 total | u32 offset | data``."""
    length = len(data) if length is None else length
    body = b"\x04" + struct.pack("<HHIII", cmd, sub, length, total, offset) + data.ljust(length, b"\0")
    return (bytes([0x81, len(body)]) + body).ljust(REPORT_SIZE, b"\0")


def crc16_u24g(data):
    """The app's ``ANSI_CRC_16_Ultimate2_4``: reflected 0x8408, init 0xFFFF, result byte-swapped."""
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return (c >> 8) | (c & 0xFF) << 8


def parse_version_u24g(report):
    """Answer of :data:`QUERY_VERSION` on the Ultimate 2.4G: firmware (x100), beta and the PID it reports."""
    return {"firmware": report[2] | report[3] << 8, "beta": report[4], "device_pid": report[6] | report[7] << 8}



def build_request(cmd, sub=0, data=b"", total=0, offset=0, length=None, with_crc=True):
    """64-byte request report. ``length`` pads ``data`` (reads send an empty, zero-padded payload)."""
    length = len(data) if length is None else length
    data = data.ljust(length, b"\0")
    c = crc16(data) if with_crc else 0
    pkt = b"\x81\x04" + struct.pack("<HHHHII", cmd, sub, length, c, total, offset) + data
    return pkt.ljust(REPORT_SIZE, b"\0")


def parse_reply(report, cmd):
    """``(length, data)`` if ``report`` is the answer to ``cmd``, else ``None``.

    Answer layout: ``02 04 | u16 4 | u16 cmd | u16 len | u16 crc | u32 | u32 | data``.
    """
    if len(report) >= 18 and report[0] == 2 and report[1] == 4 and struct.unpack_from("<HH", report, 2) == (4, cmd):
        n = struct.unpack_from("<H", report, 6)[0]
        return n, report[18:18 + n]
    return None


def parse_info(report):
    """Decode the CMD_INFO answer: firmware (x100), beta flag and the PID the controller reports."""
    return {"firmware": report[18] | report[19] << 8, "beta": report[20], "device_pid": report[22] | report[23] << 8}


class Model:
    """What differs between the supported controllers."""

    def __init__(self, key, name, pids, cfg_size, commit_key, build, crc, toggles_reports, leds, gyro):
        self.key, self.name, self.pids, self.cfg_size, self.commit_key = key, name, pids, cfg_size, commit_key
        self.build, self.crc, self.toggles_reports, self.leds, self.gyro = build, crc, toggles_reports, leds, gyro


U2 = Model("u2", "Ultimate 2 Wireless", PIDS, CFG_SIZE, COMMIT_KEY, build_request, crc16, True, True, True)
U24G = Model("u24g", "Ultimate 2.4G", U24G_PIDS, U24G_CFG_SIZE, U24G_COMMIT_KEY, build_request_u24g, crc16_u24g,
             False, False, False)
MODELS = (U2, U24G)


def model_for_pid(pid):
    return U24G if pid in U24G_PIDS else U2


def model_for_size(size):
    """Model whose config record has ``size`` bytes, or ``None``."""
    return next((m for m in MODELS if m.cfg_size == size), None)


def describe(pid, default="?"):
    return {**PIDS, **U24G_PIDS, **U24G_XINPUT_PIDS}.get(pid, default)
