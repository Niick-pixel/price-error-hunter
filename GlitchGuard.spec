# PyInstaller spec for the portable build. Run tools\build.ps1 rather than
# this directly - it also carries your settings over and zips the result.
#
# One-folder, not one-file: a one-file build unpacks itself to a temp folder on
# every launch, which is slower to start and far more often flagged by
# antivirus as a false positive. The folder is still fully portable.

from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("winrt")          # windows-toasts' WinRT projections
    + collect_submodules("windows_toasts")
    + ["pystray._win32", "clr", "webview.platforms.edgechromium",
       "webview.platforms.winforms"]
)

a = Analysis(
    ["GlitchGuard.pyw"],
    pathex=[],
    binaries=[],
    datas=[("web", "web"), ("assets", "assets")],
    hiddenimports=hidden,
    excludes=["tkinter", "unittest", "pydoc", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GlitchGuard",
    icon="assets/glitchguard.ico",
    console=False,                       # a window app, not a terminal
    upx=False,                           # UPX-packed exes trip antivirus
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="GlitchGuard",
)
