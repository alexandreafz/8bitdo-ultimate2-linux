"""Transport to the controller over ``/dev/hidraw``: read, write and save the config, LED theme, status."""
import os
import select
import struct
import sys
import time

from . import discovery, protocol
from .protocol import (CHUNK, CMD_COMMIT, CMD_GET_THEME, CMD_READ, CMD_REPORT, CMD_SET_THEME,
                       CMD_WRITE, QUERY_VERSION, ANSWER_VERSION, QUERY_PAD, ANSWER_PAD, REPORT_SIZE,
                       build_request, parse_info, parse_reply)

RETRIES = 30             # the app's retry count per chunk


class Device:
    """One open controller. ``path`` selects a specific hidraw node (default: the first one found).

    Opening also opens the matching joystick node (see :func:`ultimate2.discovery.find_input_node`),
    without which the firmware ignores the config endpoint. Exits with a message (``SystemExit``)
    when there is no controller or no permission. ``model`` (:class:`ultimate2.protocol.Model`) follows the PID.
    """

    def __init__(self, path=None):
        devs = list(discovery.find_devices())
        if path:
            devs = [d for d in devs if d[0] == path] or [(path, 0, "")]
        if not devs:
            if discovery.xinput_u24g():
                sys.exit("8BitDo Ultimate 2.4G found in X mode: run `u2ctl xmode enter` to open its X configuration "
                         "(or set the switch on its back to D)")
            if discovery.bluetooth_u24g():
                sys.exit("8BitDo Ultimate 2.4G connected over Bluetooth, which has no configuration channel: "
                         "connect the USB cable (switch on D) to configure it")
            sys.exit("no 8BitDo config interface found (is the controller plugged in / paired?)")
        self.path, self.pid, usb_dir = devs[0]
        self.model = protocol.model_for_pid(self.pid)
        self.poll_fd = None
        node = discovery.find_input_node(usb_dir) if usb_dir else None
        if node:
            try:
                self.poll_fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                print(f"warning: cannot open {node} ({e}); controller may not answer", file=sys.stderr)
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            sys.exit(f"permission denied on {self.path}: install udev/70-8bitdo-u2.rules (see README)")
        self._drain()

    def close(self):
        for fd in (self.fd, self.poll_fd):
            if fd is not None:
                os.close(fd)

    # ------------------------------------------------------------ raw I/O
    def _drain(self):
        while select.select([self.fd], [], [], 0.02)[0]:
            os.read(self.fd, REPORT_SIZE)

    def send(self, cmd, sub=0, data=b"", total=0, offset=0, length=None, with_crc=True):
        if self.model is protocol.U24G:
            os.write(self.fd, protocol.build_request_u24g(cmd, sub, data, total, offset, length))
        else:
            os.write(self.fd, build_request(cmd, sub, data, total, offset, length, with_crc))

    def recv(self, cmd, timeout=0.5, offset=None):
        """Wait for the answer to ``cmd``; returns ``(length, data)`` or ``None`` on timeout.

        With ``offset``, answers echoing another offset (late answers to a request that timed out) are skipped.
        """
        end = time.time() + timeout
        while (left := end - time.time()) > 0:
            if not select.select([self.fd], [], [], left)[0]:
                break
            report = os.read(self.fd, REPORT_SIZE)
            r = parse_reply(report, cmd)
            if r and (offset is None or struct.unpack_from("<I", report, 14)[0] == offset):
                return r
        return None

    def query(self, raw, want=None, timeout=0.5):
        """Send a fixed 64-byte command and return the first response (optionally matching a prefix)."""
        self._drain()
        os.write(self.fd, bytes(raw).ljust(REPORT_SIZE, b"\0"))
        end = time.time() + timeout
        while (left := end - time.time()) > 0:
            if not select.select([self.fd], [], [], left)[0]:
                break
            r = os.read(self.fd, REPORT_SIZE)
            if want is None or r.startswith(want):
                return r
        return None

    # ------------------------------------------------------------ status
    def info(self):
        """``{"firmware", "beta", "device_pid"}`` or ``None``."""
        if self.model is protocol.U24G:                   # no CMD_INFO: the version query carries the same
            r = self.query(QUERY_VERSION, want=ANSWER_VERSION)
            return protocol.parse_version_u24g(r) if r else None
        r = self.query(b"\x81\x04\x00\x01", want=b"\x02\x04\x04\x00\x00\x01")
        return parse_info(r) if r else None

    def edition(self):
        """Colorway of the controller (the app's ``m_ControllerColor``), or ``None``."""
        if self.model is protocol.U24G:                   # byte 6 of its version answer is the PID
            return None
        r = self.query(QUERY_VERSION, want=ANSWER_VERSION)
        return r[6] if r else None

    def pad_status(self):
        """Through the dongle: ``{"battery", "firmware", "edition"}`` of the controller itself, or ``None`` (wired,
        or the controller does not answer). The app reads firmware and colour here; byte 18 is the battery %."""
        if self.model is protocol.U24G:
            return None
        r = self.query(QUERY_PAD, want=ANSWER_PAD, timeout=.25)      # wired: nobody answers, keep it short
        return {"battery": r[18], "firmware": r[19] | r[20] << 8, "edition": r[23]} if r else None

    def report(self, on):
        """Turn the controller's input reports off/on around config writes (like the app)."""
        if not self.model.toggles_reports:
            return
        self.send(CMD_REPORT, sub=1 if on else 0, with_crc=False)
        self.recv(CMD_REPORT)

    def get_theme(self):
        """Active LED theme (see :data:`ultimate2.protocol.THEMES`), or ``None``."""
        if not self.model.leds:
            return None
        self.send(CMD_GET_THEME)
        r = self.recv(CMD_GET_THEME)
        return r[1][0] if r and r[0] else None

    def set_theme(self, theme):
        if not self.model.leds:
            raise IOError(f"the {self.model.name} has no LED themes")
        self.send(CMD_SET_THEME, sub=theme)
        if self.recv(CMD_SET_THEME) is None:
            raise IOError("controller did not confirm the LED theme")

    def current_slot(self):
        """Active profile (0-2; 3 = default, no custom profile). Reads only the 20-byte header,
        like the app's ``getUltimate2CurrentSlot``."""
        self.send(CMD_READ, total=20, offset=0, length=20)
        r = self.recv(CMD_READ, **self._echo(0))
        return struct.unpack_from("<H", r[1], 18)[0] if r and r[0] >= 20 else None

    # ------------------------------------------------------------ config record
    def _echo(self, offset):
        """``recv`` arguments: the Ultimate 2.4G echoes the offset (checked), the Ultimate 2 is matched by command."""
        return {"offset": offset} if self.model is protocol.U24G else {}

    def read_config(self):
        """The whole config record (1592 bytes on the Ultimate 2, 1652 on the Ultimate 2.4G)."""
        size = self.model.cfg_size
        buf = bytearray()
        tries = 0
        while len(buf) < size:
            self.send(CMD_READ, total=size, offset=len(buf), length=min(CHUNK, size - len(buf)))
            r = self.recv(CMD_READ, **self._echo(len(buf)))
            if not r or r[0] == 0:
                tries += 1
                if tries >= RETRIES:
                    raise IOError(f"read failed at offset {len(buf)}")
                continue
            tries = 0
            buf += r[1]
        return bytes(buf[:size])

    def write_config(self, data, start=0, end=None):
        """Write ``data[start:end]`` of the record and save it to flash.

        A sub-range is how the app updates one setting on the Ultimate 2 (``writeUltimate2dynamic`` writes 12
        bytes at ``0x4b8 + 12*slot``). The Ultimate 2.4G app always writes the whole record (``writeUltimate2_4``),
        so the range is ignored there. Raises ``IOError`` if a chunk or the save is not acknowledged.
        """
        size = self.model.cfg_size
        if self.model is protocol.U24G:
            start, end = 0, size
            slot = self.current_slot()           # the app refreshes cur_slot first (getUltimate2_4CurrentSlot):
            if slot is not None:                 # the profile button may have changed it since the record was read
                data = data[:18] + struct.pack("<H", slot) + data[20:]
        elif end is None:
            end = size
        assert len(data) == size and 0 <= start < end <= size
        self.report(False)
        off, tries = start, 0
        while off < end:
            self.send(CMD_WRITE, data=data[off:min(off + CHUNK, end)], total=size, offset=off)
            r = self.recv(CMD_WRITE, **self._echo(off))
            if not r or r[0] == 0:
                tries += 1
                if tries >= RETRIES:
                    raise IOError(f"write failed at offset {off}")
                continue
            tries = 0
            off += r[0]
        time.sleep(0.1)
        self.send(CMD_COMMIT, sub=self.model.commit_key, with_crc=False)
        ok = self.recv(CMD_COMMIT, timeout=4.0 if self.model is protocol.U24G else 3.0) is not None
        self.report(True)
        if not ok:
            raise IOError("controller did not confirm the save")
