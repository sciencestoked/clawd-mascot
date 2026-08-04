#!/usr/bin/env python3
"""
clawd_tray.py — menu bar tray entry point.
Detects OS and delegates to the appropriate backend.
"""

import os
import subprocess
import sys

from clawd_core import CONFIG_FILE, RELOAD_FILE

# ---------------------------------------------------------------------------
# Subprocess manager (platform-neutral, shared by all backends)
# ---------------------------------------------------------------------------

WIDGET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clawd_widget.py")


class MascotProcess:
    def __init__(self):
        self._proc = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        if self.running:
            return
        self._proc = subprocess.Popen(
            [sys.executable, WIDGET_PATH],
            start_new_session=True,
        )

    def stop(self):
        if not self.running:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None


# ---------------------------------------------------------------------------
# Dispatch to OS backend
# ---------------------------------------------------------------------------

if sys.platform == "darwin":
    from backends.macos_tray import run
else:
    print(f"[clawd] Platform '{sys.platform}' — no tray backend yet. Contributions welcome!")
    print("  See backends/ to add support for your OS.")
    sys.exit(1)

run(MascotProcess())
