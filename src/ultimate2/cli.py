"""``u2ctl`` — command line interface: inspect, back up, edit and restore the controller config."""
import argparse
import json
import struct
import sys

from . import battery, config, device, discovery, keepalive, xmode
from . import protocol
from .protocol import THEMES, VID, describe


def parser():
    ap = argparse.ArgumentParser(prog="u2ctl", description="Configure the 8BitDo Ultimate 2 Wireless and the Ultimate 2.4G "
                                                          "(mode switch on D) on Linux.")
    ap.add_argument("-d", "--device", help="hidraw node (default: auto-detect)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list detected devices")
    sub.add_parser("info", help="firmware version and active slot")
    p = sub.add_parser("dump", help="read config as JSON")
    p.add_argument("-o", "--output")
    p = sub.add_parser("apply", help="write edited JSON back")
    p.add_argument("file")
    p.add_argument("-n", "--dry-run", action="store_true")
    p = sub.add_parser("new-slot", help="turn slot 0-2 into a custom profile with app defaults")
    p.add_argument("slot", type=int, choices=range(3))
    p.add_argument("--name", default="Linux")
    p.add_argument("-n", "--dry-run", action="store_true")
    p = sub.add_parser("theme", help="show or set the active LED theme (Ultimate 2 only)")
    p.add_argument("name", nargs="?", choices=list(THEMES.values()))
    p = sub.add_parser("xmode", help="Ultimate 2.4G on X: open its config channel (enter) or go back to X (leave)")
    p.add_argument("action", choices=("enter", "leave"))
    sub.add_parser("battery", help="battery of the controller over Bluetooth (Ultimate 2.4G)")
    sub.add_parser("keepalive", help="keep Ultimate 2.4G pads on X read so they stay connected (systemd user service)")
    p = sub.add_parser("backup", help="save raw config record")
    p.add_argument("file")
    p = sub.add_parser("restore", help="write raw config record")
    p.add_argument("file")
    return ap


def main(argv=None):
    a = parser().parse_args(argv)

    if a.cmd == "list":
        for path, pid, usb in discovery.find_devices():
            print(f"{path}  {VID:04x}:{pid:04x}  {describe(pid)}  poll={discovery.find_input_node(usb)}")
        if discovery.xinput_u24g():
            print("Ultimate 2.4G in X mode: `u2ctl xmode enter` opens its X configuration (or set the switch to D)")
        if discovery.bluetooth_u24g():
            print("Ultimate 2.4G over Bluetooth: no configuration channel there, use the USB cable (switch on D)")
            b = battery.bluetooth()
            if b:
                print(f"battery     {b['capacity']}% ({b['status'].lower()})")
        return

    if a.cmd == "battery":
        b = battery.bluetooth()
        if not b:
            sys.exit("no 8BitDo controller reporting its battery: it is only known over Bluetooth "
                     "(the 2.4G receiver does not report it)")
        print(f"{b['name']}: {b['capacity']}% ({b['status'].lower()})")
        return

    if a.cmd == "keepalive":
        keepalive.run()
        return

    if a.cmd == "xmode" and a.action == "enter":
        try:
            ok = xmode.enter()
        except PermissionError:
            sys.exit("no write access to the controller's USB node: reinstall the package (udev rule) and replug it")
        if not ok:
            sys.exit("no Ultimate 2.4G on X found, or it did not open its config mode")
        print("config mode open (X configuration); `u2ctl xmode leave` goes back to X")
        return

    dev = device.Device(a.device)
    if a.cmd == "info":
        i = dev.info() or sys.exit("no answer from controller")
        cfg = dev.read_config()
        mode, slot = struct.unpack_from("<HH", cfg, 16)
        print(f"device      {dev.path} ({VID:04x}:{dev.pid:04x} {describe(dev.pid)}, {dev.model.name})")
        print(f"firmware    {i['firmware'] / 100:.2f}" + (f" beta {i['beta']}" if i["beta"] else ""))
        print(f"report pid  0x{i['device_pid']:04x} ({describe(i['device_pid'])})")
        print(f"mode/slot   gamepad_mode={mode} cur_slot={slot}")
        pad = dev.pad_status()
        if pad:                                    # 2.4G: the controller behind the dongle
            print(f"controller  firmware {pad['firmware'] / 100:.2f}, battery {pad['battery']}%, colorway {pad['edition']}")
    elif a.cmd == "dump":
        text = json.dumps(config.decode(dev.read_config()), indent=2, ensure_ascii=False)
        if a.output:
            with open(a.output, "w") as f:
                f.write(text + "\n")
        else:
            print(text)
    elif a.cmd in ("apply", "new-slot"):
        cur = dev.read_config()
        if a.cmd == "apply":
            with open(a.file) as f:
                doc = json.load(f)
        else:
            doc = config.default_slot(config.decode(cur), a.slot, a.name)
        new, changed = config.encode(doc, cur)
        print("changed:", *changed or ["(nothing)"], sep="\n  ")
        if changed and not a.dry_run:
            dev.write_config(new)
            if not config.same(new, dev.read_config()):
                sys.exit("verify failed: controller config differs from what was written")
            print("saved and verified")
    elif a.cmd == "xmode":
        if dev.model is not protocol.U24G:
            sys.exit(f"the {dev.model.name} has no X/D modes")
        xmode.leave(dev)
        print("back to X")
    elif a.cmd == "theme":
        if not dev.model.leds:
            sys.exit(f"the {dev.model.name} has no LED themes")
        if a.name:
            dev.set_theme(next(k for k, v in THEMES.items() if v == a.name))
        t = dev.get_theme()
        print(THEMES.get(t, f"unknown ({t})"))
    elif a.cmd == "backup":
        with open(a.file, "wb") as f:
            f.write(dev.read_config())
        print(f"saved {dev.model.cfg_size} bytes to {a.file}")
    elif a.cmd == "restore":
        with open(a.file, "rb") as f:
            data = f.read()
        if len(data) != dev.model.cfg_size:
            sys.exit(f"{a.file}: expected {dev.model.cfg_size} bytes for the {dev.model.name}, got {len(data)}")
        dev.write_config(data)
        if not config.same(data, dev.read_config()):
            sys.exit("verify failed: controller config differs from the backup")
        print("restored")
