#!/usr/bin/env python3
"""Experiment (run as root): make an Ultimate 2.4G on X (2dc8:3106) open its config channel like on Windows.

Ultimate Software V1 reaches the X-mode configuration with a rumble "knock" sent through XInput
(Xinput.subXinput_C). Sent through xpad it is ignored, so this replays what Windows does first: the MS OS
descriptor request (string 0xEE) that firmwares use to detect Windows, the xusb22 vendor requests, the player
LED, then the knock straight on the interrupt endpoint. Read-only for the controller's flash. Logs everything and
gives the interface back to xpad. Usage: xmode_handshake.py [/dev/bus/usb/BBB/DDD]
"""
import ctypes
import fcntl
import glob
import os
import struct
import sys
import time

USBDEVFS_CONTROL, USBDEVFS_BULK = 0xC0185500, 0xC0185502
USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE = 0x8004550F, 0x80045510
USBDEVFS_IOCTL, USBDEVFS_DISCONNECT, USBDEVFS_CONNECT = 0xC0105512, 0x5516, 0x5517
EP_IN, EP_OUT = 0x81, 0x02
KNOCK = [(0, 0), (0, 0), (.006, 0), (0, .006), (.006, .006), (.022, .006), (0, 0)]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def find_node():
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            vid, pid = (open(f"{d}/{k}").read().strip() for k in ("idVendor", "idProduct"))
        except OSError:
            continue
        if vid == "2dc8":
            bus, dev = (int(open(f"{d}/{k}").read()) for k in ("busnum", "devnum"))
            return f"/dev/bus/usb/{bus:03d}/{dev:03d}", pid
    return None, None


def ctrl(fd, rtype, req, value, index, length=0, data=b"", timeout=500):
    buf = ctypes.create_string_buffer(data, max(length, len(data), 1))
    arg = struct.pack("BBHHHI4xP", rtype, req, value, index, length or len(data), timeout, ctypes.addressof(buf))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_CONTROL, bytearray(arg), True)     # mutable buffer: returns the byte count
    except OSError as e:
        return f"erro {e.strerror}"
    return buf.raw[:n] if rtype & 0x80 else n


def xfer(fd, ep, data=b"", length=32, timeout=100):
    buf = ctypes.create_string_buffer(data, max(length, len(data)))
    arg = struct.pack("III4xP", ep, length if ep & 0x80 else len(data), timeout, ctypes.addressof(buf))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_BULK, bytearray(arg), True)
    except OSError as e:
        return f"erro {e.strerror}"
    return buf.raw[:n] if ep & 0x80 else n


def intf_ioctl(fd, code):
    try:
        fcntl.ioctl(fd, USBDEVFS_IOCTL, bytearray(struct.pack("iiP", 0, code, 0)), True)
        return "ok"
    except OSError as e:
        return f"erro {e.strerror}"


def main():
    node, pid = (sys.argv[1], "?") if len(sys.argv) > 1 else find_node()
    if not node:
        sys.exit("nenhum 8BitDo conectado")
    log("dispositivo", node, "pid", pid)
    fd = os.open(node, os.O_RDWR)
    claimed = False
    try:
        # 1. MS OS 1.0 descriptor: string 0xEE ("MSFT100" + vendor code) — how firmwares spot Windows
        r = ctrl(fd, 0x80, 6, 0x03EE, 0x0000, 18)
        log("string 0xEE:", r if isinstance(r, str) else r.hex(" "))
        if isinstance(r, bytes) and len(r) >= 18 and r[2:16].decode("utf-16-le", "replace") == "MSFT100":
            vc = r[16]
            for idx, name in ((4, "compat ID"), (5, "ext props")):
                h = ctrl(fd, 0xC0, vc, 0x0000, idx, 16)
                log(f"MS OS {name} (cabeçalho):", h if isinstance(h, str) else h.hex(" "))
                if isinstance(h, bytes) and len(h) >= 4:
                    full = ctrl(fd, 0xC0, vc, 0x0000, idx, min(struct.unpack_from("<I", h)[0], 4096))
                    log(f"MS OS {name}:", full if isinstance(full, str) else full.hex(" "))
        # 2. take the interface from xpad
        log("desligando xpad:", intf_ioctl(fd, USBDEVFS_DISCONNECT))
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, struct.pack("I", 0))
        claimed = True
        # 3. xusb22 vendor requests (capabilities / identification)
        for rtype, req, val, idx, n in ((0xC1, 0x01, 0x0100, 0x0000, 20), (0xC0, 0x01, 0x0000, 0x0000, 4),
                                        (0xC1, 0x01, 0x0000, 0x0000, 8)):
            r = ctrl(fd, rtype, req, val, idx, n)
            log(f"pedido {rtype:02x} {req:02x} {val:04x} {idx:04x} {n}:", r if isinstance(r, str) else r.hex(" "))
        for _ in range(3):                                       # whatever the pad sends back
            r = xfer(fd, EP_IN, length=32, timeout=50)
            if isinstance(r, bytes):
                log("entrada:", r.hex(" "))
        # 4. player 1 LED, as xusb22 does
        log("LED jogador 1:", xfer(fd, EP_OUT, bytes([0x01, 0x03, 0x06])))
        time.sleep(0.2)
        # 5. the knock, three times (the app's XInputChange x3), 16 ms apart (Windows Sleep(10))
        for rep in range(3):
            time.sleep(0.2)
            for left, right in KNOCK:
                pkt = bytes([0x00, 0x08, 0x00, int(left * 65535) >> 8, int(right * 65535) >> 8, 0, 0, 0])
                r = xfer(fd, EP_OUT, pkt)
                if isinstance(r, str):
                    log("vibração:", pkt.hex(" "), r)
                time.sleep(0.016)
            log(f"senha {rep + 1} enviada")
    finally:
        if claimed:
            try:
                fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, struct.pack("I", 0))
            except OSError:
                pass
            log("devolvendo ao xpad:", intf_ioctl(fd, USBDEVFS_CONNECT))
        os.close(fd)
    # 6. did it come back with another PID?
    for i in range(16):
        time.sleep(0.5)
        n, p = find_node()
        if p != pid:
            log("mudou!", n, "pid", p)
            break
    log("final:", find_node())


if __name__ == "__main__":
    main()
