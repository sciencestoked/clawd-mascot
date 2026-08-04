#!/usr/bin/env python3
"""
clawd_widget.py — floating mascot entry point.
Detects OS and delegates to the appropriate backend.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

debug_mode = "--debug" in sys.argv

if sys.platform == "darwin":
    from backends.macos_widget import run
else:
    print(f"[clawd] Platform '{sys.platform}' — no backend yet. Contributions welcome!")
    print("  See backends/ to add support for your OS.")
    sys.exit(1)

run(debug_mode=debug_mode)
