"""Desktop entry point: GlitchGuard in its own window, with a tray icon.

This is the file PyInstaller builds into GlitchGuard.exe. Double-clicking it
from source works too (.pyw runs without a console). For the plain browser
version, use `python -m glitchguard` or the run-windows.bat launcher.
"""
import sys

from glitchguard.desktop import main

if __name__ == "__main__":
    sys.exit(main())
