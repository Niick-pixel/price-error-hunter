#!/bin/bash
# Price Error Hunter launcher for macOS and Linux.
#
# The .command extension makes this double-clickable in Finder. If macOS
# refuses to run it, the file has lost its executable bit - restore it with:
#     chmod +x run-mac.command
set -e

# Finder launches scripts from the user's home directory, not the script's
# folder, so the working directory has to be set explicitly.
cd "$(dirname "$0")"

PY_BIN=".venv/bin/python"

find_python() {
    # macOS ships "python3"; "python" is often absent or still Python 2.
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

if [ ! -x "$PY_BIN" ]; then
    echo "First run - setting up a local Python environment..."
    SYS_PY="$(find_python)" || {
        echo
        echo "Setup failed: Python 3.9 or newer was not found."
        echo "Install it with:  brew install python3"
        echo "or download it from https://www.python.org/downloads/"
        read -r -p "Press Return to close."
        exit 1
    }
    "$SYS_PY" -m venv .venv
    "$PY_BIN" -m pip install --quiet --upgrade pip
    "$PY_BIN" -m pip install --quiet -r requirements.txt
fi

"$PY_BIN" -m pricehunter
