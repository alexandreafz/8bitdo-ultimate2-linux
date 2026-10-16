#!/usr/bin/env python3
"""Read-only probe for the 8BitDo Ultimate 2.4G (2dc8:3012 wired, 2dc8:3013 dongle).

Sends only the version query and config reads (cmd 2), never a write or commit. Saves the record to
``u24g-record.bin`` in the current directory and prints the raw frames, so the protocol found in
8BitDo Ultimate Software V1 (8BitDoAdvance.dll: readUltimate2_4) can be checked against the hardware.
"""
import glob
import os
import select
import struct
import sys
import time

VID, PIDS, SIZE, CHUNK = 0x2DC8, (0x3012, 0x3013), 1652, 45


def find():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        ue = open(d + "/device/uevent").read()
        hid = next((l.split("=")[1] for l in ue.splitlines() if l.startswith("HID_ID=")), "0:0:0")
        _, vid, pid = (int(x, 16) for x in hid.split(":"))
        if vid == VID and pid in PIDS:
            usb = os.path.dirname(os.path.dirname(os.path.realpath(d + "/device")))
            js = next((n for n in sorted(glob.glob("/sys/class/input/js*") + glob.glob("/sys/class/input/event*"))
                       if os.path.realpath(n + "/device").startswith(usb + "/")), None)
            return "/dev/" + os.path.basename(d), pid, js and "/dev/input/" + os.path.basename(js)
    sys.exit("controller 2dc8:3012/3013 not found")


def frame(cmd, sub=0, length=0, total=0, offset=0, data=b""):
    body = b"\x04" + struct.pack("<HHIII", cmd, sub, length, total, offset) + data.ljust(length, b"\0")
    return (bytes([0x81, len(body)]) + body).ljust(64, b"\0")


def crc_8408(buf):
    c = 0xFFFF
    for b in buf:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return ((c >> 8) | (c << 8)) & 0xFFFF


def main():
    path, pid, js = find()
    print(f"{path} pid=0x{pid:04x} joystick={js}")
    keep = os.open(js, os.O_RDONLY | os.O_NONBLOCK) if js else None
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def xfer(pkt, want, timeout=0.5, show=False):
        while select.select([fd], [], [], 0.02)[0]:
            os.read(fd, 64)
        os.write(fd, pkt)
        end = time.time() + timeout
        while (left := end - time.time()) > 0 and select.select([fd], [], [], left)[0]:
            r = os.read(fd, 64)
            if show:
                print("  <-", r[:32].hex(" "))
            if r.startswith(want):
                return r
        return None

    r = xfer(b"\x81\x05\x00\x21\x01".ljust(64, b"\0"), b"\x02\x22")
    print("version:", r[:12].hex(" ") if r else "no answer")

    print("header read (20 bytes):")
    pkt = frame(2, length=20, total=20)
    print("  ->", pkt[:24].hex(" "))
    r = xfer(pkt, b"\x02\x04\x04\x00\x02\x00", show=True)
    if not r:
        sys.exit("no answer to the read: protocol guess is wrong, stopping")
    n = struct.unpack_from("<I", r, 6)[0]
    hdr = r[18:18 + 20]
    print(f"  len={n} flags={[hex(x) for x in struct.unpack_from('<3I', hdr)]} crc=0x{struct.unpack_from('<I', hdr, 12)[0]:x}"
          f" mode={struct.unpack_from('<H', hdr, 16)[0]} cur_slot={struct.unpack_from('<H', hdr, 18)[0]}")

    buf, tries = bytearray(), 0
    while len(buf) < SIZE and tries < 30:
        want = min(CHUNK, SIZE - len(buf))
        r = xfer(frame(2, length=want, total=SIZE, offset=len(buf)), b"\x02\x04\x04\x00\x02\x00")
        n = struct.unpack_from("<H", r, 6)[0] if r else 0
        if not n:
            tries += 1
            continue
        buf += r[18:18 + n]
    print(f"record: {len(buf)} of {SIZE} bytes")
    if len(buf) >= SIZE:
        buf = bytes(buf[:SIZE])
        open("u24g-record.bin", "wb").write(buf)
        stored = struct.unpack_from("<I", buf, 12)[0]
        zeroed = buf[:12] + b"\0" * 4 + buf[16:]
        print(f"crc stored=0x{stored:04x} over-record=0x{crc_8408(buf):04x} with-field-zeroed=0x{crc_8408(zeroed):04x}")
        print("saved u24g-record.bin")
    os.close(fd)
    if keep is not None:
        os.close(keep)


if __name__ == "__main__":
    main()
