"""Desktop shell: its own window, a tray icon, Windows toasts, a login item.

The window is Edge WebView2 (built into Windows 11) rather than a browser tab,
which is the point of the desktop build: GlitchGuard runs in its own process
and can no longer slow down the browser you use for everything else.

The poller and local server are exactly the ones `python -m glitchguard`
runs; this module only adds what a browser tab cannot do - close to the tray,
keep watching, and tell you through Windows when something lands.
"""

import ctypes
import errno
import json
import os
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

from . import __version__, config, poller, server, store, updates

APP_ID = "GlitchGuard.App"
APP_NAME = "GlitchGuard"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MUTEX_NAME = "Local\\GlitchGuard.SingleInstance"
INSTANCE_FILE = os.path.join(config.DATA_DIR, "instance.json")
LOG_FILE = os.path.join(config.DATA_DIR, "glitchguard.log")
ERROR_ALREADY_EXISTS = 183


# ---------------------------------------------------------------- utilities

def _open_log():
    """A windowed build has no console, so output needs somewhere to go.

    Trimmed at start once it passes a megabyte, which keeps a few weeks of
    errors without the file growing for the life of the install.
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)
    try:
        if os.path.getsize(LOG_FILE) > 1_000_000:
            os.remove(LOG_FILE)
    except OSError:
        pass
    log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    log.write(f"\n--- GlitchGuard {__version__} started {time.ctime()} ---\n")
    sys.stdout = sys.stderr = log


def _clear_download_marks():
    """Unblock the app's own bundled DLLs so .NET will load them.

    Unzipping a downloaded archive in Explorer tags every extracted file as
    "from the internet" (a Zone.Identifier stream, ZoneId=3). The .NET
    Framework refuses to load an assembly carrying that tag, so the window
    layer - pywebview on pythonnet - failed to start with "Failed to resolve
    Python.Runtime.Loader.Initialize" for anyone who downloaded the release,
    while a locally built copy, which has no tag, worked.

    This does what right-click -> Properties -> Unblock does, limited to .dll
    files inside the app's own bundle. The executable keeps its tag, so
    Windows still runs its SmartScreen check on it: by the time this code
    runs, the user has already chosen to trust this download.
    """
    if not config.FROZEN:
        return 0
    cleared = 0
    for folder, _dirs, files in os.walk(config.BUNDLE_DIR):
        for name in files:
            if name.lower().endswith(".dll"):
                try:
                    os.remove(os.path.join(folder, name) + ":Zone.Identifier")
                    cleared += 1
                except OSError:
                    pass        # no tag on this file - the normal case
    return cleared


def _fatal(message):
    """A readable dialog instead of a raw traceback, pointing at the log."""
    try:
        ctypes.windll.user32.MessageBoxW(
            None, f"{message}\n\nDetails were written to:\n{LOG_FILE}",
            "GlitchGuard could not start", 0x10)
    except Exception:
        pass


def _single_instance():
    """True if this is the only copy running.

    The mutex handle is deliberately kept for the life of the process: the
    moment it is closed another copy could start its own poller, and two
    pollers would double every request to every feed.
    """
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already = ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    _single_instance.handle = handle
    return not already


def _wake_running_copy():
    """Ask the copy that is already running to show its window."""
    try:
        with open(INSTANCE_FILE, encoding="utf-8") as fh:
            info = json.load(fh)
        # Windows only lets the process the user just interacted with take the
        # foreground. That is this launch, not the copy in the tray, so without
        # handing the right over, the window reappears behind whatever else is
        # open and the double-click looks like it did nothing.
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(int(info.get("pid") or -1))
        except Exception:
            pass
        req = urllib.request.Request(
            f"http://127.0.0.1:{info['port']}/api/show", data=b"{}", method="POST",
            headers={"X-PH-Token": info["token"], "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception:
        return False


def _set_app_id():
    """Group the taskbar button and toasts under GlitchGuard, not Python."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _register_toast_identity(icon_path):
    """Give toasts a name and icon. Per-user registry only; no admin needed.

    Unpackaged apps have no manifest, so Windows looks the AppUserModelID up
    here to know what to call the sender in the notification and in Action
    Center. Without it every toast would be attributed to "Python".
    """
    import winreg
    key = rf"Software\Classes\AppUserModelId\{APP_ID}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        if icon_path and os.path.exists(icon_path):
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, icon_path)


def set_autostart(enabled):
    """Add or remove the login item. Only the packaged app registers itself -
    from source there is no stable executable to point Windows at.

    Rewritten on every start while enabled, so moving the portable folder
    heals the entry the next time it is launched by hand.
    """
    if not config.FROZEN:
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ,
                              f'"{sys.executable}" --tray')
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass
    return True


# ------------------------------------------------------------------ the api

class Api:
    """What the page may call as window.pywebview.api.*.

    pywebview walks every public attribute of this object to expose it, so
    the shell is held under a private name - exposing the window itself would
    have it try to serialise the whole GUI object graph.
    """

    def __init__(self, shell):
        self._shell = shell

    def export_csv(self, section):
        import webview
        text, rows = server.export_rows(section or "feed")
        picked = self._shell.window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=f"glitchguard-{section or 'feed'}.csv",
            file_types=("CSV spreadsheet (*.csv)", "All files (*.*)"),
        )
        if not picked:
            return {"saved": False}
        path = picked if isinstance(picked, str) else picked[0]
        if not path.lower().endswith(".csv"):
            path += ".csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return {"saved": True, "rows": rows, "name": os.path.basename(path)}

    def focus_changed(self, focused):
        self._shell.page_focused = bool(focused)
        return True


# ---------------------------------------------------------------- the shell

class Shell:
    def __init__(self, start_hidden):
        self.window = None
        self.icon = None
        self.hidden = start_hidden
        self.page_focused = not start_hidden
        self.quitting = False
        self.toaster = None
        self.icon_path = os.path.join(config.ASSETS_DIR, "glitchguard.ico")
        self.png_path = os.path.join(config.ASSETS_DIR, "glitchguard.png")

    # -- read by the page through /api/status ------------------------------
    def info(self):
        return {"version": __version__, "packaged": config.FROZEN}

    # -- window ------------------------------------------------------------
    def show(self):
        if not self.window:
            return
        self.hidden = False
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            traceback.print_exc()

    def _on_closing(self):
        """Closing the window hides it to the tray; Quit in the tray exits."""
        if self.quitting:
            return True
        self.hidden = True
        self.page_focused = False
        threading.Thread(target=self.window.hide, daemon=True).start()
        if not getattr(self, "_told_about_tray", False):
            self._told_about_tray = True
            self._toast("Still watching", "GlitchGuard is running in the tray. "
                        "Right-click the icon to quit.", url=None)
        return False

    def _on_minimized(self):
        self.page_focused = False

    def _on_restored(self):
        self.hidden = False

    # -- tray --------------------------------------------------------------
    def _start_tray(self):
        import pystray
        from PIL import Image

        image = Image.open(self.png_path) if os.path.exists(self.png_path) \
            else Image.new("RGBA", (64, 64), (233, 162, 60, 255))

        def autostart_checked(_item):
            return bool(config.load().get("autostart", True))

        def toggle_autostart(_icon, _item):
            on = not config.load().get("autostart", True)
            config.update({"autostart": on})
            set_autostart(on)

        menu = pystray.Menu(
            pystray.MenuItem("Open GlitchGuard", lambda: self.show(), default=True),
            pystray.MenuItem("Start with Windows", toggle_autostart,
                             checked=autostart_checked,
                             visible=config.FROZEN),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.quit()),
        )
        self.icon = pystray.Icon(APP_ID, image, APP_NAME, menu)
        # pystray's Windows backend runs its own message loop in the calling
        # thread, so it lives on a daemon thread beside pywebview's main loop.
        threading.Thread(target=self.icon.run, daemon=True).start()

    def quit(self):
        self.quitting = True
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        if self.window:
            self.window.destroy()

    # -- toasts ------------------------------------------------------------
    def _start_toasts(self):
        try:
            from windows_toasts import InteractableWindowsToaster
            _register_toast_identity(self.icon_path)
            self.toaster = InteractableWindowsToaster(APP_NAME, APP_ID)
        except Exception:
            traceback.print_exc()
            self.toaster = None

    def _toast(self, headline, body, url):
        if not self.toaster:
            return
        try:
            from windows_toasts import Toast
            toast = Toast([headline, body])
            # Windows reports a refused toast through this event rather than an
            # exception, so without it a broken notification path is silent.
            toast.on_failed = lambda args: print(
                f"toast failed: {getattr(args, 'reason', args)!r}")
            toast.on_dismissed = lambda args: print(
                f"toast shown, then {getattr(args, 'reason', args)!r}")
            if url:
                safe = url if url.startswith(("http://", "https://")) else None
                if safe:
                    toast.on_activated = lambda _args: webbrowser.open(safe)
            self.toaster.show_toast(toast)
        except Exception:
            traceback.print_exc()

    def on_alert(self, payload, kind):
        """Raised by the poller. Toast only when the window cannot show it."""
        if not config.load().get("native_toasts", True):
            return
        if not (self.hidden or not self.page_focused):
            return      # the in-window card has it covered
        title = payload.get("title") or "New deal"
        if kind == "pinned":
            headline = "Pinned product"
        elif kind == "keyword":
            headline = f"Watching “{payload.get('keyword')}”"
        else:
            headline = f"Possible price error · {round(payload.get('score') or 0)}/100"
        bits = []
        if payload.get("retailer"):
            bits.append(payload["retailer"])
        if isinstance(payload.get("price"), (int, float)):
            bits.append(f"${payload['price']:,.2f}")
        if payload.get("discount_pct"):
            bits.append(f"{round(payload['discount_pct'])}% off")
        # Joined outside the f-string: a backslash escape inside an f-string
        # expression is a syntax error before Python 3.12.
        meta = " · ".join(bits)
        self._toast(headline, f"{title}\n{meta}", payload.get("url"))

    def test_toast(self):
        """A deal-shaped toast, shown whatever the focus state, so the whole
        path - identity, text, sound, click to open - can be checked on demand."""
        if not self.toaster:
            return {"ok": False, "note": "Windows notifications are unavailable"}
        self._toast("Possible price error \u00b7 92/100",
                    "GlitchGuard test notification\nClick to open the project page",
                    "https://github.com/Niick-pixel/price-error-hunter")
        return {"ok": True, "note": "Sent - check the corner of your screen"}

    def on_settings(self, cfg):
        set_autostart(bool(cfg.get("autostart", True)))

    # -- run ---------------------------------------------------------------
    def run(self):
        import webview

        cfg = config.load()
        engine = poller.Poller()
        port = cfg["port"]
        httpd = None
        for candidate in range(port, port + 20):
            try:
                httpd = server.serve(engine, candidate)
                port = candidate
                break
            except OSError as exc:
                if exc.errno not in (errno.EADDRINUSE, 10048):
                    raise
        if httpd is None:
            print("Could not bind a local port in 8765-8785.")
            return 1

        server.Handler.desktop = self
        server.Handler.on_settings = self.on_settings
        engine.on_alert = self.on_alert
        engine.start()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        # Lets a second launch find this copy and ask it to come forward.
        with open(INSTANCE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"port": port, "token": server.TOKEN, "pid": os.getpid()}, fh)

        if cfg.get("check_updates", True):
            updates.check_async()
        set_autostart(bool(cfg.get("autostart", True)))
        self._start_toasts()
        self._start_tray()

        self.window = webview.create_window(
            APP_NAME, f"http://127.0.0.1:{port}/?t={server.TOKEN}",
            js_api=Api(self), width=1380, height=900, min_size=(760, 560),
            hidden=self.hidden, background_color="#211d18",
        )
        self.window.events.closing += self._on_closing
        self.window.events.minimized += self._on_minimized
        self.window.events.restored += self._on_restored

        try:
            webview.start(
                gui="edgechromium",
                private_mode=False,
                storage_path=os.path.join(config.DATA_DIR, "webview"),
            )
        finally:
            self.quitting = True
            engine.stop()
            httpd.shutdown()
            try:
                os.remove(INSTANCE_FILE)
            except OSError:
                pass
            try:
                if self.icon:
                    self.icon.stop()
            except Exception:
                pass
        return 0


def main():
    start_hidden = "--tray" in sys.argv
    if config.FROZEN:
        _open_log()
    if not _single_instance():
        # Another copy owns the feeds. Bring it forward and bow out.
        _wake_running_copy()
        return 0
    cleared = _clear_download_marks()
    if cleared:
        print(f"Unblocked {cleared} bundled DLLs marked as downloaded.")
    _set_app_id()
    try:
        return Shell(start_hidden).run()
    except Exception as exc:
        traceback.print_exc()
        _fatal(f"The app window failed to open.\n\n{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
