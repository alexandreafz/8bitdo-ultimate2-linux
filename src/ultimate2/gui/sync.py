"""Mixin: device I/O on a worker thread — initial read, auto-save, active-profile polling, LED theme, backups."""
import copy
import threading
import time
from tkinter import filedialog, messagebox

from .. import battery, config, device, protocol, xmode
from . import theme
from .i18n import _
from .theme import ACCENT, DANGER, DEFAULT_SKIN, EDITION_SKINS, MUTED, SKINS, THEME_NAMES
from .widgets import error_dialog


class DeviceSync:
    # ------------------------------------------------------------ status line / connection pill
    def set_status(self, text, error=False):
        self.status.configure(text=text, fg=DANGER if error else MUTED)

    def set_connected(self, state):
        """Connection badge (Wi-Fi and battery; the firmware goes to the footer's corner). ``state``: ``(firmware,
        battery %)`` when connected (battery may be ``None``), ``None`` when the controller does not answer (grey Wi-Fi
        with a red X), ``False`` while still looking (grey Wi-Fi)."""
        c, s = self.pill, self.s
        c.delete("all")
        col, w = ACCENT if state else MUTED, max(1, round(2 * s))
        x, y = 11 * s, 17 * s                                  # Wi-Fi: three arcs over a dot
        for r in (5, 9.5, 14):
            c.create_arc(x - r * s, y - r * s, x + r * s, y + r * s, start=50, extent=80, style="arc", outline=col, width=w)
        c.create_oval(x - 2 * s, y - 2 * s, x + 2 * s, y + 2 * s, fill=col, outline="")
        if state is None:                                      # red X over the bottom-right of the arcs
            c.create_line(15 * s, 10 * s, 22 * s, 17 * s, fill=DANGER, width=w, capstyle="round")
            c.create_line(15 * s, 17 * s, 22 * s, 10 * s, fill=DANGER, width=w, capstyle="round")
        self.fw_label.configure(text=f"firmware {state[0]}" if state and state[0] else "")
        if state and state[1] is not None:                   # battery outline, fill to the level, then the %
            battery, px, bw, bh, top = state[1], 32 * s, 22 * s, 11 * s, 6 * s
            c.create_rectangle(px, top, px + bw, top + bh, outline=col, width=max(1, round(1.5 * s)))
            c.create_rectangle(px + bw, top + 3 * s, px + bw + 2.5 * s, top + bh - 3 * s, fill=col, outline="")
            level = min(max(battery, 0), 100) / 100
            if level:
                c.create_rectangle(px + 2 * s, top + 2 * s, px + 2 * s + (bw - 4 * s) * level, top + bh - 2 * s,
                                   fill=DANGER if battery <= 15 else col, outline="")
            c.create_text(px + bw + 6 * s, 11.5 * s, text=f"{battery}%", anchor="w", fill=col, font=theme.font(9),
                          tags="battery")
        c.configure(width=c.bbox("all")[2] + 2)

    # ------------------------------------------------------------ worker
    def run(self, label, job, done, quiet=False, fail=None):
        """Run ``job(dev)`` on a worker thread; ``done(result)`` runs on the Tk thread.

        ``quiet`` (background polling): no status text and no error dialog, only the connection pill.
        ``fail(error, message)``, when given, handles errors instead (on the Tk thread).
        """
        if self.busy:
            return
        self.busy = True
        if not quiet:
            self.set_status(label)

        def work():
            dev = None
            try:
                dev = device.Device()
                res = job(dev)
                self.after(0, lambda: done(res))
            except BaseException as e:     # Device uses sys.exit for user-facing errors
                msg = str(e) or e.__class__.__name__
                if fail:
                    self.after(0, lambda e=e: fail(e, msg))     # `e` is unbound once the except block ends
                elif quiet:
                    self.after(0, lambda: self.set_connected(None))
                else:
                    self.after(0, lambda: (self.set_status(msg, True), self.set_connected(None),
                                           error_dialog(self, _("Erro"), msg, self.s)))
            finally:
                if dev:
                    dev.close()
                self.after(0, self._idle)
        threading.Thread(target=work, daemon=True).start()

    def _idle(self):
        self.busy = False

    # ------------------------------------------------------------ auto-save
    def changed(self, var=None):
        """A setting changed: an empty profile becomes a custom one, then save shortly (debounced)."""
        if self._loading or self.doc is None:
            return
        if var is not self.v["enabled"] and not self.v["enabled"].get():
            self.v["enabled"].set(True)       # re-enters changed(); the second call just reschedules
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(theme.AUTOSAVE_MS, self.autosave)
        self.set_status(_("Alterações pendentes…"))

    def autosave(self):
        """Write only the changed byte range (like the app's per-setting writes) and verify it."""
        self._save_job = None
        if self.busy:
            self._save_job = self.after(300, self.autosave)
            return
        self.gather()
        new = config.encode(copy.deepcopy(self.doc), self.base)[0]
        span = config.changed_span(self.base, new)
        if not span:
            self.set_status("")
            return

        def job(dev):
            dev.write_config(new, *span)
            got = dev.read_config()
            if self.model is protocol.U24G:      # whole record, minus the fields its firmware owns
                if not config.same(new, got):
                    raise IOError(_("verificação falhou: o controle não guardou o que foi enviado"))
                return got
            if got[span[0]:span[1]] != new[span[0]:span[1]]:
                raise IOError(_("verificação falhou: o controle não guardou o que foi enviado"))
            return new

        def done(saved):
            self.base = saved
            self.profile_note.configure(text="")
            self.set_status(_("✓ Salvo no controle ({} bytes).").format(span[1] - span[0]))
        self.run(_("Salvando no controle…"), job, done)

    # ------------------------------------------------------------ live state
    def poll(self):
        """Follow the controller's active profile (the user switches it with the profile button)."""
        if self.doc is not None and not self.busy and self._save_job is None:
            wireless = bool(self.conn and self.conn[1] is not None)    # battery only exists through the dongle

            def done(r):
                slot, pad = r
                bt = battery.bluetooth() if self.model is protocol.U24G and self.conn else None
                if pad or bt:
                    self.conn = (self.conn[0], pad["battery"] if pad else bt["capacity"])
                if slot is not None and self.conn:
                    self.set_connected(self.conn)          # recover the badge after a transient error
                if slot is not None and slot != self.active_slot:
                    self.active_slot = slot
                    self.refresh_slots()
            self.run("", lambda dev: (dev.current_slot(), dev.pad_status() if wireless else None), done, quiet=True)
        self.after(theme.POLL_MS, self.poll)

    def apply_theme(self):
        """Send the LED theme chosen in ``v["theme"]`` (applies at once, for every profile)."""
        t = self.v["theme"].get()
        if t == self.theme_dev or t not in protocol.THEMES or self.doc is None:
            return
        if self.busy:
            self.after(300, self.apply_theme)
            return

        def done(_r):
            self.theme_dev = t
            self.set_status(_("✓ Tema de LED aplicado: {}.").format(_(THEME_NAMES[t])))
        self.run(_("Aplicando tema de LED…"), lambda dev: dev.set_theme(t), done)

    def read_device(self, retry=False):
        """Read everything from the controller and show it (skin, theme, active slot, config).

        A controller that does not answer (switched off, out of the dongle's range, unplugged) is not an error: the
        status says so and the read is tried again until it answers. Only a permission problem opens a dialog.
        """
        if self._retry_job:                     # Reload while waiting for the controller
            self.after_cancel(self._retry_job)
            self._retry_job = None
        if retry and self.busy:
            self._retry_job = self.after(theme.RETRY_MS, lambda: self.read_device(True))
            return

        def fail(e, msg):
            self.set_connected(None)
            if isinstance(e, SystemExit) and "permission" in msg:
                self.set_status(msg, True)
                error_dialog(self, _("Erro"), msg, self.s)
                return
            if "X mode" in msg and not self.xmode_tried:
                self.xmode_tried = True
                return self.enter_xmode()
            bt = battery.bluetooth() if "Bluetooth" in msg else None
            if bt:                                       # the badge shows the battery even without a config channel
                self.set_connected((None, bt["capacity"]))
            self.set_status(_("Ultimate 2.4G no modo X: coloque a chave de trás do controle em D para configurá-lo.")
                            if "X mode" in msg else
                            _("Ultimate 2.4G conectado por Bluetooth, que não permite configurar: ligue o cabo USB "
                              "(chave em D). Os perfis gravados valem também no Bluetooth.")
                            + (" " + _("Bateria: {}%.").format(bt["capacity"]) if bt else "")
                            if "Bluetooth" in msg else
                            _("Controle desligado ou fora de alcance. Ligue-o: ele será lido automaticamente."))
            self._retry_job = self.after(theme.RETRY_MS, lambda: self.read_device(True))

        def job(dev):
            if dev.model is not self.model:
                return dev.model
            return dev.path, dev.pid, dev.info(), dev.read_config(), dev.get_theme(), dev.edition(), dev.pad_status()

        def done(r):
            if isinstance(r, protocol.Model):        # another controller model: rebuild the window for it
                self.restart = True
                self.after_idle(self.destroy)
                return
            path, pid, info, cfg, led_theme, edition, pad = r
            if pad:                         # through the dongle, info() is the dongle's: use the controller's own
                edition, info = pad["edition"], pad
            self.edition = edition
            want = self.skin_pref if self.skin_pref in SKINS else EDITION_SKINS.get(edition, DEFAULT_SKIN)
            if want != self.skin:
                self.apply_skin(want)
            self.theme_dev = led_theme
            self.v["theme"].set(led_theme if led_theme in protocol.THEMES else 0)
            self.base = cfg
            self.doc = config.decode(cfg)
            self.active_slot = self.doc["cur_slot"]
            fw = f"{info['firmware'] / 100:.2f}" if info else "?"
            bt = battery.bluetooth() if self.model is protocol.U24G else None   # pad on Bluetooth, configured via
            self.conn = (fw, pad["battery"] if pad else bt and bt["capacity"])  # the cable or the receiver
            self.set_connected(self.conn)
            modes = {0: "Switch", 1: "Android" if self.model.leds else "D-input", 3: "Windows (XInput)" if self.model.leds else "X-input"}
            mode = modes.get(self.doc["gamepad_mode"], self.doc["gamepad_mode"])
            self.info_label.configure(text=_("Dispositivo: {}\nModo: {}\nEdição: {} ({})").format(
                f"{path} · {protocol.describe(pid, hex(pid))}", mode, edition, _(SKINS[self.skin]["name"])))
            self.load()
            self.refresh_slots()
            self.set_status(_("Configuração lida do controle. As mudanças são salvas automaticamente."))
        self.run("" if retry else _("Lendo do controle…"), job, done, quiet=retry, fail=fail)

    # ------------------------------------------------------------ Ultimate 2.4G on X
    def enter_xmode(self):
        """Open the X configuration like the Windows app (the receiver only works on X); :meth:`leave_xmode` on close."""
        self.busy = True
        self.set_status(_("Abrindo a configuração do modo X…"))

        def work():
            try:
                ok, err = xmode.enter(), None
            except OSError as e:
                ok, err = False, e
            self.after(0, lambda: self._entered_xmode(ok, err))
        threading.Thread(target=work, daemon=True).start()

    def _entered_xmode(self, ok, err):
        self.busy = False
        if ok:
            self.xmode_open = True
            return self.read_device()
        self.set_connected(None)
        self._retry_job = self.after(theme.RETRY_MS, lambda: self.read_device(True))   # e.g. the switch moved to D
        if isinstance(err, PermissionError):
            self.set_status(_("Sem permissão para abrir o modo X: reinstale o pacote (regra udev) e reconecte o controle. "
                              "Ou coloque a chave em D."), True)
        else:
            self.set_status(_("Ultimate 2.4G no modo X: coloque a chave de trás do controle em D para configurá-lo."))

    def leave_xmode(self):
        """Put the controller back on X if this window opened its config mode."""
        if not self.xmode_open:
            return
        self.xmode_open = False
        try:
            dev = device.Device()
        except BaseException:      # already gone (unplugged, switched off)
            return
        try:
            xmode.leave(dev)
        except OSError:
            pass
        finally:
            dev.close()

    # ------------------------------------------------------------ backups
    def backup(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".bin",
                                            initialfile=f"u2-backup-{time.strftime('%Y%m%d-%H%M')}.bin")
        if path:
            def job(dev):
                with open(path, "wb") as f:
                    f.write(dev.read_config())
            self.run(_("Fazendo backup…"), job, lambda r: self.set_status(_("Backup salvo em {}").format(path)))

    def restore(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[(_("Backup"), "*.bin")])
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()
        if len(data) != self.model.cfg_size:
            return error_dialog(self, _("Erro"), _("Arquivo inválido ({} bytes, esperado {}).").format(len(data), self.model.cfg_size),
                                self.s)
        if not messagebox.askyesno(_("Restaurar"), _("Substituir toda a configuração do controle por este backup?"), parent=self):
            return

        def job(dev):
            dev.write_config(data)
            if not config.same(data, dev.read_config()):
                raise IOError(_("verificação falhou"))

        def done(_r):
            self.base = data
            self.doc = config.decode(data)
            self.load()
            self.set_status(_("Backup restaurado e verificado."))
        self.run(_("Restaurando…"), job, done)
