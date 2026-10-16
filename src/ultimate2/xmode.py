"""Ultimate 2.4G on X: enter its config mode and go back, like Ultimate Software V1 on Windows.

On X (switch on X, cable or 2.4G receiver) the pad is an XInput device (2dc8:3106) without a config channel. Windows
reaches the config with what a USBPcap capture shows: the xusb22 connect packets (``02 08 03`` among them, which xpad
never sends) and then the app's rumble "knock" three times. The pad then comes back as 2dc8:3013 (receiver) or
2dc8:3012 (cable) with the config channel; the record read there is the X one (``gamepad_mode`` 3). ``81 05 00 51 02``
on that channel puts it back on X (the app sends it when it closes).

Entering needs the USB device node (usbfs) to take the interface from xpad: write access comes from the udev rule.
"""
import ctypes
import fcntl
import glob
import os
import struct
import time

from . import discovery, protocol

USBDEVFS_BULK = 0xC0185502
USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE = 0x8004550F, 0x80045510
USBDEVFS_IOCTL, USBDEVFS_DISCONNECT, USBDEVFS_CONNECT = 0xC0105512, 0x5516, 0x5517
EP_OUT = 0x02
CONNECT = (b"\x01\x03\x02", b"\x02\x08\x03", b"\x01\x03\x02", b"\x01\x03\x06")
KNOCK = ((1, 0), (0, 1), (1, 1), (5, 1), (0, 0))      # rumble bytes as they reach the pad
BACK_TO_X = b"\x81\x05\x00\x51\x02"
DEV_BUS = "/dev/bus/usb"                               # overridable by tests
sleep = time.sleep


def find_xinput_node():
    """usbfs node (``/dev/bus/usb/BBB/DDD``) of an Ultimate 2.4G on X, or ``None``."""
    for d in sorted(glob.glob(discovery.SYS + "/bus/usb/devices/*")):
        ids = [discovery._read(f"{d}/{k}").decode().strip() for k in ("idVendor", "idProduct", "busnum", "devnum")]
        if ids[0] == f"{protocol.VID:04x}" and ids[1] and int(ids[1], 16) in protocol.U24G_XINPUT_PIDS:
            return f"{DEV_BUS}/{int(ids[2]):03d}/{int(ids[3]):03d}"
    return None


def _out(fd, data):
    buf = ctypes.create_string_buffer(data, len(data))
    fcntl.ioctl(fd, USBDEVFS_BULK, bytearray(struct.pack("III4xP", EP_OUT, len(data), 200, ctypes.addressof(buf))), True)


def _intf(fd, code):
    fcntl.ioctl(fd, USBDEVFS_IOCTL, bytearray(struct.pack("iiP", 0, code, 0)), True)


def enter(timeout=6.0):
    """Send the Windows sequence to the pad on X; ``True`` once a config interface shows up.

    Raises ``PermissionError`` when the USB node is not writable (udev rule missing), ``OSError`` on USB errors.
    """
    node = find_xinput_node()
    if not node:
        return False
    fd = os.open(node, os.O_RDWR)
    try:
        _intf(fd, USBDEVFS_DISCONNECT)                 # take the interface from xpad
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, bytearray(struct.pack("I", 0)), True)
        for pkt in CONNECT:
            _out(fd, pkt)
            sleep(0.002)
        sleep(1.0)
        for _ in range(3):
            for left, right in KNOCK:
                _out(fd, bytes([0, 8, 0, left, right, 0, 0, 0]))
                sleep(0.0155)
            sleep(0.34)
    finally:
        try:                                           # the pad usually re-enumerates first: nothing to give back
            fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, bytearray(struct.pack("I", 0)), True)
            _intf(fd, USBDEVFS_CONNECT)
        except OSError:
            pass
        os.close(fd)
    end = time.time() + timeout
    while time.time() < end:
        if any(pid in protocol.U24G_PIDS for _p, pid, _u in discovery.find_devices()):
            return True
        sleep(0.25)
    return False


def leave(dev):
    """Put an Ultimate 2.4G opened on its config channel back on X (it re-enumerates as 2dc8:3106)."""
    os.write(dev.fd, BACK_TO_X.ljust(protocol.REPORT_SIZE, b"\0"))
