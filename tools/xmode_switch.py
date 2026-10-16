#!/usr/bin/env python3
"""Switch an Ultimate 2.4G receiver/pad on X (2dc8:3106) to its config mode (2dc8:3013/3012), replaying byte for
byte what Windows sent in a USBPcap capture (8bitdo_dongle4.pcapng) when Ultimate Software V1 did it:

  connect : 01 03 02 | 02 08 03 | 01 03 02 | 01 03 06        (xusb22 LED and the 02 08 03 command xpad never sends)
  knock x3: 00 08 00 L R 00 00 00 with (1,0) (0,1) (1,1) (5,1) (0,0), ~15 ms apart, repeats ~400 ms apart

Needs write access to the USB device node (root). Usage: xmode_switch.py [/dev/bus/usb/BBB/DDD]
"""
import ctypes
import fcntl
import glob
import os
import struct
import sys
import time

USBDEVFS_BULK = 0xC0185502
USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE = 0x8004550F, 0x80045510
USBDEVFS_IOCTL, USBDEVFS_DISCONNECT, USBDEVFS_CONNECT = 0xC0105512, 0x5516, 0x5517
EP_OUT = 0x02
CONNECT = [bytes.fromhex(h) for h in ("010302", "020803", "010302", "010306")]
KNOCK = [(1, 0), (0, 1), (1, 1), (5, 1), (0, 0)]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def find():
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            vid, pid = (open(f"{d}/{k}").read().strip() for k in ("idVendor", "idProduct"))
            bus, dev = (int(open(f"{d}/{k}").read()) for k in ("busnum", "devnum"))
        except OSError:
            continue
        if vid == "2dc8":
            return f"/dev/bus/usb/{bus:03d}/{dev:03d}", pid
    return None, None


def out(fd, data):
    buf = ctypes.create_string_buffer(data, len(data))
    arg = bytearray(struct.pack("III4xP", EP_OUT, len(data), 200, ctypes.addressof(buf)))
    try:
        return fcntl.ioctl(fd, USBDEVFS_BULK, arg, True)
    except OSError as e:
        return f"erro {e.strerror}"


def intf(fd, code):
    try:
        fcntl.ioctl(fd, USBDEVFS_IOCTL, bytearray(struct.pack("iiP", 0, code, 0)), True)
        return "ok"
    except OSError as e:
        return f"erro {e.strerror}"


def main():
    node, pid = (sys.argv[1], "?") if len(sys.argv) > 1 else find()
    if not node:
        sys.exit("nenhum 8BitDo conectado")
    log("dispositivo", node, "pid", pid)
    fd = os.open(node, os.O_RDWR)
    claimed = False
    try:
        log("desligando xpad:", intf(fd, USBDEVFS_DISCONNECT))
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, bytearray(struct.pack("I", 0)), True)
        claimed = True
        for pkt in CONNECT:
            log("conexão", pkt.hex(" "), "->", out(fd, pkt))
            time.sleep(0.002)
        time.sleep(1.0)
        for rep in range(3):
            for left, right in KNOCK:
                r = out(fd, bytes([0, 8, 0, left, right, 0, 0, 0]))
                if isinstance(r, str):
                    log("vibração", left, right, r)
                time.sleep(0.0155)
            log(f"senha {rep + 1} enviada")
            time.sleep(0.34)
    finally:
        if claimed:
            try:
                fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, bytearray(struct.pack("I", 0)), True)
            except OSError:
                pass
            log("devolvendo ao xpad:", intf(fd, USBDEVFS_CONNECT))
        try:
            os.close(fd)
        except OSError:
            pass
    for _ in range(20):
        time.sleep(0.5)
        n, p = find()
        if p != pid:
            log("MUDOU:", n, "pid", p)
            break
    log("final:", find())


if __name__ == "__main__":
    main()
