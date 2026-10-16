"""Find the controller in sysfs: its vendor config ``hidraw`` node and the joystick node of the same device."""
import glob
import os

from . import protocol

SYS, DEV = "/sys", "/dev"   # roots, overridable by tests
# report descriptors of the config channel: usage page 0xFF7A (controller) / 0xFFA0 (2.4G dongle)
CONFIG_DESCRIPTORS = (b"\x06\x7a\xff", b"\x06\xa0\xff")
# Ultimate 2.4G: its gamepad interface carries the config channel only over USB (output report 0x81); over
# Bluetooth it has the same PID and no such report
U24G_CONFIG_REPORT = b"\x85\x81"


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


def find_devices():
    """Yield ``(hidraw_path, pid, usb_dir)`` for every 8BitDo vendor config interface.

    The Ultimate 2.4G (mode switch on D) has a single HID interface, the gamepad, which also carries the config
    reports: it is recognised by its PID instead of a vendor usage page.
    """
    for d in sorted(glob.glob(SYS + "/class/hidraw/hidraw*")):
        ue = _read(d + "/device/uevent").decode(errors="replace")
        hid_id = next((l.split("=")[1] for l in ue.splitlines() if l.startswith("HID_ID=")), "")
        try:
            _, vid, pid = (int(x, 16) for x in hid_id.split(":"))
        except ValueError:
            continue
        desc = _read(d + "/device/report_descriptor")
        if vid != protocol.VID or not (U24G_CONFIG_REPORT in desc if pid in protocol.U24G_PIDS
                                       else desc[:3] in CONFIG_DESCRIPTORS):
            continue
        usb_dir = os.path.dirname(os.path.dirname(os.path.realpath(d + "/device")))
        yield DEV + "/" + os.path.basename(d), pid, usb_dir


def find_input_node(usb_dir):
    """Joystick node (``js*``, else ``event*``) of the same USB device.

    The firmware only services the config endpoint while the host keeps draining its XInput
    reports, so this node must stay open during config I/O.
    """
    for pat in (SYS + "/class/input/js*", SYS + "/class/input/event*"):
        for n in sorted(glob.glob(pat)):
            if os.path.realpath(n + "/device").startswith(usb_dir + "/"):
                return DEV + "/input/" + os.path.basename(n)
    return None


def xinput_u24g():
    """``True`` if an Ultimate 2.4G is plugged in with its mode switch on X (no config interface)."""
    want = {f"product=3/{protocol.VID:04x}/{p:04x}/" for p in protocol.U24G_XINPUT_PIDS}
    return any(any(w in _read(e + "/device/uevent").decode(errors="replace").lower() for w in want)
               for e in sorted(glob.glob(SYS + "/class/input/event*")))


def bluetooth_u24g():
    """``True`` if an Ultimate 2.4G is connected over Bluetooth (HID bus 0005), where it cannot be configured."""
    for d in sorted(glob.glob(SYS + "/class/hidraw/hidraw*")):
        ue = _read(d + "/device/uevent").decode(errors="replace")
        if any(l.upper().startswith(f"HID_ID=0005:0000{protocol.VID:04X}:0000{p:04X}") for l in ue.splitlines()
               for p in protocol.U24G_PIDS):
            return True
    return False


def connected_model():
    """Model of the first controller found (sysfs only, no I/O); the Ultimate 2 when nothing is plugged in."""
    dev = next(find_devices(), None)
    if dev:
        return protocol.model_for_pid(dev[1])
    return protocol.U24G if xinput_u24g() or bluetooth_u24g() else protocol.U2
