"""Mixin: live input from the controller's joystick node (pressed buttons, triggers, sticks, d-pad)."""
import os
import struct
import time

from .. import discovery

JS_BUTTONS = ["A", "B", "X", "Y", "LB", "RB", "Select", "Start", "Home", "L3", "R3"]   # xpad js button order
# js numbering per model: buttons, analog trigger axes, stick axes. The Ultimate 2.4G (switch on D) is a generic HID
# pad: 16 buttons (Star and the paddles send none of their own) and axes LX LY RX RY RT LT hat-X hat-Y
JS_LAYOUTS = {
    "u2": dict(buttons=dict(enumerate(JS_BUTTONS)), triggers={2: "LT", 5: "RT"}, sticks={"L3": (0, 1), "R3": (3, 4)}),
    "u24g": dict(buttons={0: "A", 1: "B", 3: "X", 4: "Y", 6: "LB", 7: "RB", 8: "LT", 9: "RT", 10: "Select",
                          11: "Start", 12: "Home", 13: "L3", 14: "R3"},
                 triggers={5: "LT", 4: "RT"}, sticks={"L3": (0, 1), "R3": (2, 3)}),
}
JS_EVENT = "<IhBB"       # struct js_event: u32 time, s16 value, u8 type, u8 number
JS_BUTTON, JS_AXIS, JS_INIT = 1, 2, 0x80


class PadInput:
    def _read_pad(self):
        """Background thread: follow the real controller's buttons/axes; reconnects every second."""
        while not self._closing:
            node = None
            try:
                dev = next(discovery.find_devices(), None)
                node = dev and discovery.find_input_node(dev[2])
            except OSError:
                pass
            fd = None
            if node:
                try:
                    fd = os.open(node, os.O_RDONLY)
                except OSError:
                    fd = None
            if fd is None:
                time.sleep(1)
                continue
            try:
                while not self._closing:
                    ev = os.read(fd, 8)
                    if len(ev) < 8:
                        break
                    self.pad_event(*struct.unpack(JS_EVENT, ev)[1:])
            except OSError:
                pass
            finally:
                os.close(fd)
            self.pad_down.clear()
            self.pad_axes.clear()
            time.sleep(1)

    def pad_event(self, value, kind, number):
        """One js_event: kind 1 = button, 2 = axis; bit 0x80 marks the initial-state burst (no ripple).

        Axes (Ultimate 2, xpad): 0/1 left stick, 2 LT, 3/4 right stick, 5 RT, 6/7 d-pad; see :data:`JS_LAYOUTS`.
        """
        lay = JS_LAYOUTS[self.model.key]
        init = kind & JS_INIT
        kind &= ~JS_INIT & 0xFF
        if kind == JS_BUTTON and number in lay["buttons"]:
            self._pad_set(lay["buttons"][number], value != 0, init)
        elif kind == JS_AXIS:
            self.pad_axes[number] = value
            if number == 6:
                self._pad_set("Left", value < 0, init)
                self._pad_set("Right", value > 0, init)
            elif number == 7:
                self._pad_set("Up", value < 0, init)
                self._pad_set("Down", value > 0, init)
            elif number in lay["triggers"]:
                self._pad_set(lay["triggers"][number], value > 0, init)

    def _pad_set(self, name, down, init):
        if down and name not in self.pad_down and not init:
            self.press_t[name] = time.time()
        (self.pad_down.add if down else self.pad_down.discard)(name)
