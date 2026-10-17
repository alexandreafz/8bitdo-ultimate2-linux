# 8BitDo Ultimate 2 Wireless — configuration protocol

This was reverse-engineered from *8BitDo Ultimate Software V2* (v1.37) for interoperability. The sources were
`8BitDoAdvance.dll` (native, analysed with objdump and Ghidra through REA) and the app's .NET assemblies
(decompiled with ILSpy). Everything below was verified against a real controller, firmware 1.10.

## Devices

| USB ID | What | Config interface |
|---|---|---|
| `2dc8:310b` | controller over USB (XInput mode) | HID interface 2, usage page `0xFF7A` |
| `2dc8:6013` | 2.4G dongle (`Ultimate2RR`) | HID interface 0, usage page `0xFFA0` |
| `0x6012` | PID the controller reports internally (`PID_Ultimate2`) | — |

The config channel is a vendor HID collection with output report `0x81` and input report `0x02`, 63 bytes
each (64 including the report ID). On Linux it shows up as a `/dev/hidrawN` node.

> **Linux quirk.** The firmware only services the config endpoint while the host keeps draining the controller's
> XInput reports. Windows' XInput driver always does that. On Linux, `xpad` only polls while a program has the
> joystick open, so a tool must keep `/dev/input/jsN` (or `eventN`) of the same device open during config I/O.
> Otherwise writes stall with `ETIMEDOUT` and only a replug recovers the endpoint.

## Frames

All numbers are little endian.

```
request : 81 04 | u16 cmd | u16 sub | u16 len | u16 crc | u32 total | u32 offset | data[len]   (≤ 45 bytes)
answer  : 02 04 | u16 4   | u16 cmd | u16 len | u16 crc | u32 total | u32 offset | data[len]
```

* `crc` is CRC-16/MODBUS (reflected polynomial `0xA001`, init `0xFFFF`) of `data`. Header-only commands send `0`.
* Reads send `len` = the requested chunk size with zero-filled data.
* There are also fixed short queries (`81 05 …`) whose answers start with `02 05` or `02 22`.

## Commands

| cmd | sub | Meaning | Answer |
|---|---|---|---|
| `0x0001` (bytes `00 01`) | — | device info | data: `u16 firmware×100`, `u8 beta`, `…`, `u16 pid` at data offset 4 |
| `2` | 0 | read `len` bytes of the config record at `offset` (`total` = 1592) | the bytes |
| `1` | 0 | write `data` at `offset` | header echo; `len` = accepted bytes |
| `6` | `0x123` | commit the record to flash | header echo, within ~3 s |
| `7` | 0/1 | input reports off/on (the app wraps writes with it) | header echo |
| `0x40` | theme | set active LED theme: 2 dynamic, 3 hotwheel, 4 custom, 5 off | header echo |
| `0x41` | — | get active LED theme | data[0] = theme |
| `0x0120` (dongle) | — | is a controller connected? | data[0] = 1 if yes |
| `81 05 00 21 01` | fixed query | version and edition | `02 22`, `u16 fw`, `u8 beta`, …, byte 6 = **edition** (`m_ControllerColor`) |
| `81 04 21 01 00 00 06` | fixed query | the controller behind the 2.4G dongle | `02 04 04 00 21 01`, byte 18 = **battery %**, 19-20 = controller firmware ×100, 21 = beta, 23 = edition. The app sends it when the dongle reports PID `0x6013` and reads firmware and edition from it (byte 18 is not used by the app; it falls as the battery drains). No answer when wired or switched off. |

The active profile ("current slot") is `cur_slot` in the record header. The app reads it with a 20-byte read at
offset 0.

The app writes one setting by sending only that setting's bytes (for example `writeUltimate2dynamic` writes 12
bytes at `0x4b8 + 12·slot`) followed by a commit. It never refreshes `crc_value` on those partial writes, so the
firmware does not validate it.

## Config record (1592 bytes)

`custom_config_record_t_u2`, MSVC natural alignment, three profile slots (`s` = 0..2):

| Offset | Size | Field |
|---|---|---|
| `0 + 4s` | 4 | slot flag: `0x20200911` enabled, `0x20190000` disabled, `0` deleted, `0xffffffff` erased |
| 12 | 4 | `crc_value` (CRC-16/MODBUS of the record) |
| 16 | 2 | `gamepad_mode`: 0 Switch, 1 Android, 3 Windows/XInput |
| 18 | 2 | `cur_slot`: active profile (3 = default, no custom profile) |
| `20 + 32s` | 32 | profile name, UTF-16BE, max 16 chars |
| `116 + 12s` | 12 | rumble: flag, `float left`, `float right` (0..1) |
| `152 + 8s` | 8 | sticks: flag, left start/end, right start/end (0..128) |
| `176 + 8s` | 8 | triggers: flag, LT start/end, RT start/end (0..255) |
| `200 + 8s` | 8 | special: flag, feature bits |
| `224 + 92s` | 92 | mapping: flag, 22 × u32 key codes |
| `500 + 216s` | 216 | macros: flag, count, 4 × 52-byte records (name, mode, steps, offset, trigger key, cycles, interval) |
| `1148 + 8s` | 8 | trigger rumble range (percent) |
| `1172 + 12s` | 12 | six-axis: flag, activation key, trigger mode, sensitivity, dead compensation, mapping type |
| `1208 + 12s` | 12 | LED dynamic: flag, colour, background (`0x00RRGGBB`) |
| `1244 + 16s` | 16 | LED hotwheel: flag, colour, background, speed (1..15) |
| `1292 + 100s` | 100 | LED custom: flag, 24 colours |

Every section has its own flag; a section is used only when its flag is `0x20200911`.

### Button order of `mapping` (physical buttons)

`A B X Y LB RB LT RT L3 R3 Select Start Star Home Up Down Left Right P1 P2 P3 P4`. On the Ultimate 2 Wireless (names from
the app's mapping images and its `getUltimate2` layout): `P1` = PR and `P2` = PL, the back paddles (right and left);
`P3` = L4 and `P4` = R4, the small shoulder buttons beside LB/RB. A new profile maps all four to `None`. In XInput mode
they have no code of their own: they report the function they are mapped to.

### Key codes (function assigned to a button)

| Code | Fn | Code | Fn | Code | Fn |
|---|---|---|---|---|---|
| `0x1` | Start | `0x200` | Up | `0x100000` | P5 |
| `0x2` | L3 | `0x400` | LB | `0x200000` | P3 |
| `0x4` | R3 | `0x800` | RB | `0x400000` | Screenshot |
| `0x8` | Select | `0x1000` | B | `0x800000` | Turbo (single) |
| `0x10` | X | `0x2000` | A | `0x1000000` | Turbo (auto) |
| `0x20` | Y | `0x4000` | LT | `0x2000000` | P1 |
| `0x40` | Right | `0x8000` | RT | `0x4000000` | P2 |
| `0x80` | Left | `0x10000` | Menu | `0x40000000` | P4 |
| `0x100` | Down | `0x20000` | Home | `0x080000xx` | stick directions |

`0` means disabled. Stick directions: RS Up/Down/Left/Right = `0x08000001/02/04/08`, LS = `0x08000010/20/40/80`.

### Feature bits

`0x1` invert LS X, `0x2` invert LS Y, `0x4` invert RS X, `0x8` invert RS Y, `0x10` swap sticks, `0x80` swap
triggers, `0x100` swap LS/d-pad, `0x8000` trigger rumble. Other bits are not fully understood; tools must preserve them.

## Live input

With `xpad`, `/dev/input/jsN` reports 11 buttons (`A B X Y LB RB Select Start Home L3 R3`) and 8 axes (LX, LY, LT, RX,
RY, RT, d-pad X, d-pad Y). Star, L4/R4 and the PL/PR back buttons are not reported as separate inputs.

## 8BitDo Ultimate 2.4G

The first Ultimate (*Ultimate 2.4G Wireless*, `PID_Ultimate2_4` in *8BitDo Ultimate Software V1*, build of
2024-07-31) uses the same command numbers with a different frame, record and save key. It was reverse-engineered
from the V1 app (`8BitDoAdvance.dll`: `readUltimate2_4`, `writeUltimate2_4`, `getUltimate2_4CurrentSlot`,
`ANSI_CRC_16_Ultimate2_4`, decompiled with Ghidra through REA; the .NET assembly with ILSpy) and verified on a
controller with firmware 2.04 over USB.

### Mode switch

| Switch | USB ID | What Linux sees |
|---|---|---|
| X | `2dc8:3106` | XInput pad (`xpad`), one vendor-specific interface, **no config channel** |
| D | `2dc8:3012` | one HID interface (generic gamepad) that also carries the config reports |
| D, through the dongle | `2dc8:3013` (`PID_Ultimate2_4RR`) | not tested |
| D, Bluetooth (firmware 2.00+; pair with ★ held 3 s) | `0005:2dc8:3012` | gamepad + rumble reports only, **no config channel**; uses the D-mode profiles |
| no controller, receiver only | `2dc8:3109` "8BitDo IDLE" | HID interface (not examined) |

The V1 app tries to move XInput pads to D by playing a rumble "knock" (`Xinput.subXinput_C`: motor values
0, 0, .006/0, 0/.006, .006/.006, .022/.006, 0 → bytes `(0,0) (0,0) (1,0) (0,1) (1,1) (5,1) (0,0)`, 10 ms apart)
and sends `81 05 00 51 02` on exit to go back to XInput. Sent through `xpad` force feedback the knock reaches the
controller byte for byte (checked with usbmon), but firmware 2.04 ignores it: use the switch.

The configuration is **per mode**: with the switch on X the controller uses another record than the one read on D
(`gamepad_mode` 3 instead of 1). Linux cannot reach the X one. `tools/xmode_handshake.py` (root) replays what Windows
does before the knock: the MS OS 1.0 descriptor is there (string `0xEE` = `MSFT100`, vendor code `0x90`, compat ID
`XUSB10`), the xusb22 vendor requests (`C1 01 0100`, `C0 01 0000`) are stalled, the player LED is accepted, and the
knock sent straight on endpoint `0x02` is accepted and ignored, both wired and through the receiver (which only
connects on X). The V1 app itself only calls `XInputSetState` of `xinput1_3.dll`.

### Frames

```
request : 81 | n | 04 | u16 cmd | u16 sub | u32 len | u32 total | u32 offset | data[len]   (n = 17 + len, len ≤ 45)
answer  : 02 04 | u16 4 | u16 cmd | u32 len | u32 total | u32 offset | data[len]
```

Answers echo `total` and `offset`; a late answer to a request that timed out must be told apart by its offset. Byte 1 is the size of what follows (the DLL's packet writer), there is no CRC in the header, and only output
reports of 64 bytes are sent (report ID `0x81`). The version query `81 05 00 21 01` answers
`02 22 | u16 firmware×100 | u8 beta | 0 | u16 pid` (byte 6 is the PID, not an edition). There is no `CMD_INFO`, no LED
theme and no report on/off.

| cmd | sub | Meaning |
|---|---|---|
| 2 | 0 | read `len` bytes at `offset` (`total` = 1652; a 20-byte read at 0 gives `cur_slot`) |
| 1 | 0 | write; the app always writes the whole record |
| 6 | `0x15` | save to flash; the answer comes within ~3 s |

### Config record (1652 bytes)

`custom_config_record_t` of `Ultimate2_4Advance`, three slots `s`:

| Offset | Size | Field |
|---|---|---|
| `0 + 4s` | 4 | slot flag (`0x20200911` enabled, `0` deleted, `0xffffffff` erased) |
| 12 | 4 | `crc_value`: the app stores `ANSI_CRC_16_Ultimate2_4` (reflected `0x8408`, init `0xFFFF`, result byte-swapped, over the 1652 bytes as they stand); **the firmware overwrites it with its own save counter** (1, 2, …) |
| 16 | 2 | `gamepad_mode` (1 with the switch on D) |
| 18 | 2 | `cur_slot` (4 = no custom profile); **the firmware keeps its own value** on writes, so the app reads it first (`getUltimate2_4CurrentSlot`) |
| `20 + 32s` | 32 | name, **UTF-16LE** (`Encoding.Unicode`), 16 chars |
| `116 + 12s` | 12 | rumble: flag, `float left`, `float right` |
| `152 + 8s` | 8 | sticks: flag, left start/end, right start/end (0..128) |
| `176 + 8s` | 8 | triggers: flag, LT start/end, RT start/end (0..255) |
| `200 + 8s` | 8 | special: flag, feature bits (same bits as above) |
| `224 + 84s` | 84 | mapping: flag, 20 × u32: `A B X Y LB RB LT RT L3 R3 Select Start Star Home Up Down Left Right P1 P2` |
| `476 + 392s` | 392 | macros: flag, `u8 total_cnt`, 4 × 96-byte records (`key_map`, 18 × u16 interval, 18 × u16 key, 18 × u8 d-pad, `max_index`) |

Key codes are those of the table above for `A B X Y LB RB LT RT L3 R3 Select Start Up Down Left Right` (RT `0x8000`,
Home `0x20000`: the app's `AutoR2AndHome` → `changeKey`), plus Menu `0x10000`, Screenshot `0x400000`, Turbo
`0x800000`/`0x1000000`, P1 `0x2000000`, P2 `0x4000000` and Swap `0x8000000`; there are no stick directions.

A new profile (the app's `clear*` functions, then `enableFlagWithrecord`): identity mapping with Star = Menu
(Screenshot in mode 0) and P1/P2 = none, rumble 1.0/1.0, sticks 0..128, triggers 0..255, features 0, macro count 0
and the four macro records zeroed; the slot flag and every section flag are set to `0x20200911`.

### Live input (switch on D)

`/dev/input/jsN` has 16 buttons — A 0, B 1, X 3, Y 4, LB 6, RB 7, LT 8, RT 9, Select 10, Start 11, Home 12, L3 13,
R3 14 (Star sends nothing) — and 8 axes: LX 0, LY 1, RX 2, RY 3, RT 4, LT 5, d-pad hat 6/7.

### Opening the X configuration (verified 2026-10-16, receiver fw 1.10, controller fw 2.04)

A USBPcap capture of Ultimate Software V1 on Windows (receiver on X) shows the whole sequence. At connect, xusb22
sends `01 03 02`, `02 08 03`, `01 03 02`, `01 03 06` on endpoint `0x02`; xpad never sends `02 08 03`. When the app
starts it sends the knock `00 08 00 L R 00 00 00` with (1,0) (0,1) (1,1) (5,1) (0,0), ~15 ms apart, three times
~400 ms apart; half a second later the receiver re-enumerates as `2dc8:3013` with the config channel, and the record
read there has `gamepad_mode` 3 (the X configuration). `81 05 00 51 02` on that channel brings it back to `3106`.
Replayed over usbfs (`ultimate2/xmode.py`, after detaching xpad) the same bytes work on Linux.

### Staying connected on X

On X, a profile switch makes the receiver re-enumerate (`3106` → `3109` → `3106`). Windows polls the pad's interrupt
endpoint all the time; Linux' xpad only does while a program has the input node open. Without a reader the receiver
drops the controller again ~5 s after each reconnection and finally switches it off. Keeping the joystick node open
(`u2ctl keepalive`) fixes it.

### Battery

Only over Bluetooth: that descriptor has the HID Battery Strength usage (`05 06 09 20`, 0..100) in the gamepad
report, which the kernel exposes as `/sys/class/power_supply/hid-<mac>-battery` (`ultimate2/battery.py`). The
receiver's descriptor (`3013`) has no such field and it does not answer the Ultimate 2's `81 04 21 01 00 00 06`.

