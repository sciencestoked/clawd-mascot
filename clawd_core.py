#!/usr/bin/env python3
"""
clawd_core.py — platform-neutral core for the clawd mascot.

All animation, config, and state logic lives here.
No OS-specific imports. Safe to import on macOS, Linux, and Windows.
"""

import json
import math
import os
import sys

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _state_dir() -> str:
    if sys.platform == "win32":
        return os.environ.get("TEMP", os.path.expanduser("~"))
    return "/tmp"

_DIR        = _state_dir()
STATE_FILE  = os.path.join(_DIR, "clawd_state")
RELOAD_FILE = os.path.join(_DIR, "clawd_reload")
CONFIG_FILE = os.path.expanduser("~/.config/claude-mascot/config.json")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def cfg(config, *keys, default=None):
    """Safe nested config read."""
    val = config
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val


def get_nested(d, *keys, default=None):
    return cfg(d, *keys, default=default)


def set_nested(d, keys, value):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value

# ---------------------------------------------------------------------------
# Pixel art constants
# ---------------------------------------------------------------------------

ORANGE = (255, 140, 0, 255)
GREEN  = (0, 220, 80, 255)
RED    = (220, 50, 50, 255)
GREY   = (180, 180, 180, 255)

CHAR_MAP = {
    ' ':  (0, 0, 0, 0),
    '█':  (1, 1, 1, 1),
    '▛':  (1, 1, 1, 0),
    '▜':  (1, 1, 0, 1),
    '▐':  (0, 1, 0, 1),
    '▌':  (1, 0, 1, 0),
    '▝':  (0, 1, 0, 0),
    '▘':  (1, 0, 0, 0),
}

MASCOT_ART = [
    " ▐▛███▜▌ ",
    "▝▜█████▛▘ ",
    "  ▘▘ ▝▝  ",
]

SCALE_X  = 7
SCALE_Y  = 14
CANVAS_W = 200
CANVAS_H = 160

DELAYS = {
    "idle": 0.08, "thinking": 0.15, "tool_running": 0.05,
    "tool_success": 0.08, "tool_failure": 0.06, "permission": 0.3,
}

DEBUG_STATES   = ["idle", "thinking", "tool_running", "tool_success", "tool_failure", "permission"]
DEBUG_DURATION = 1.5

# ---------------------------------------------------------------------------
# Frame generation (PIL only, no OS deps)
# ---------------------------------------------------------------------------

def make_mascot_pil(color=ORANGE, scale_x=1.0, scale_y=1.0) -> Image.Image:
    num_cols = max(len(r) for r in MASCOT_ART)
    num_rows = len(MASCOT_ART)
    pw, ph = num_cols * 2, num_rows * 2
    img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    pix = img.load()
    for r, row in enumerate(MASCOT_ART):
        for c, ch in enumerate(row):
            tl, tr, bl, br = CHAR_MAP.get(ch, (0, 0, 0, 0))
            x, y = c * 2, r * 2
            if tl: pix[x,   y]   = color
            if tr: pix[x+1, y]   = color
            if bl: pix[x,   y+1] = color
            if br: pix[x+1, y+1] = color
    fw = max(1, int(pw * SCALE_X * scale_x))
    fh = max(1, int(ph * SCALE_Y * scale_y))
    return img.resize((fw, fh), Image.NEAREST)


def place(mascot: Image.Image, x_off=0, y_off=0) -> Image.Image:
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    bx = (CANVAS_W - mascot.width) // 2 + x_off
    by = (CANVAS_H - mascot.height) // 2 + y_off
    canvas.paste(mascot, (bx, by), mascot)
    return canvas


def add_particles(canvas: Image.Image, config: dict, frame_i: int, total_frames: int):
    count = cfg(config, "animations", "success_particles", "count", default=6)
    color = tuple(cfg(config, "animations", "success_particles", "color", default=[0, 220, 80]))
    draw = ImageDraw.Draw(canvas)
    cx, cy = CANVAS_W // 2, CANVAS_H // 2
    progress = frame_i / total_frames
    for p in range(count):
        angle = (2 * math.pi * p / count) + progress * math.pi
        dist = int(progress * 35)
        px = cx + int(math.cos(angle) * dist)
        py = cy + int(math.sin(angle) * dist)
        size = max(1, int(5 * (1 - progress)))
        alpha = int(255 * (1 - progress))
        draw.rectangle([px, py, px + size, py + size], fill=color + (alpha,))


def generate_frames(config=None) -> dict:
    if config is None:
        config = {}
    N = 8

    # idle: breathing scale pulse + bob
    breathing_on = cfg(config, "animations", "idle_breathing", "enabled", default=True)
    scale_min    = cfg(config, "animations", "idle_breathing", "scale_min", default=1.0)
    scale_max    = cfg(config, "animations", "idle_breathing", "scale_max", default=1.06)
    idle_frames  = []
    for i in range(16):
        t = i / 16
        bob = int(5 * math.sin(2 * math.pi * t))
        if breathing_on:
            s = scale_min + (scale_max - scale_min) * (0.5 + 0.5 * math.sin(2 * math.pi * t))
            m = make_mascot_pil(ORANGE, scale_x=s, scale_y=s)
        else:
            m = make_mascot_pil(ORANGE)
        idle_frames.append(place(m, y_off=bob))
    frames = {"idle": idle_frames}

    # thinking: bob + dots
    m_o = make_mascot_pil(ORANGE)
    thinking = []
    for i in range(N):
        bob = int(3 * math.sin(2 * math.pi * i / N))
        base = place(m_o, y_off=bob)
        draw = ImageDraw.Draw(base)
        for d in range(i % 4):
            cx = (CANVAS_W + m_o.width) // 2 + 4 + d * 10
            cy = CANVAS_H // 2 - 3
            draw.rectangle([cx, cy, cx + 6, cy + 6], fill=GREY)
        thinking.append(base)
    frames["thinking"] = thinking

    # tool_running: shake
    shakes = [0, 6, 0, -6, 0, 6, 0, -6]
    frames["tool_running"] = [place(m_o, x_off=shakes[i]) for i in range(N)]

    # tool_success: 3 bounces + squash/stretch + particles
    ss_on     = cfg(config, "animations", "squash_stretch", "enabled", default=True)
    ss_amount = cfg(config, "animations", "squash_stretch", "amount", default=0.25)
    pt_on     = cfg(config, "animations", "success_particles", "enabled", default=True)
    total     = 16
    success   = []
    for i in range(total):
        t      = i / total
        bounce = abs(math.sin(3 * math.pi * t))
        y_off  = int(-14 * bounce)
        if ss_on:
            sy_s = 1.0 + ss_amount * bounce
            sx_s = 1.0 - (ss_amount * 0.5) * bounce
        else:
            sx_s = sy_s = 1.0
        m = make_mascot_pil(GREEN, scale_x=sx_s, scale_y=sy_s)
        canvas = place(m, y_off=y_off)
        if pt_on:
            add_particles(canvas, config, i, total)
        success.append(canvas)
    frames["tool_success"] = success

    # tool_failure: decaying shudder
    shudder_on = cfg(config, "animations", "failure_shudder", "enabled", default=True)
    intensity  = cfg(config, "animations", "failure_shudder", "intensity", default=8)
    decay      = cfg(config, "animations", "failure_shudder", "decay", default=0.75)
    m_r        = make_mascot_pil(RED)
    failure    = []
    for i in range(12):
        if shudder_on:
            amp   = intensity * (decay ** i)
            x_off = int(amp * (1 if i % 2 == 0 else -1))
        else:
            x_off = 6 if i % 2 == 0 else -6
        failure.append(place(m_r, x_off=x_off))
    frames["tool_failure"] = failure

    # permission: color flash + zoom pulse
    zoom_on    = cfg(config, "animations", "permission_zoom_pulse", "enabled", default=True)
    zoom_scale = cfg(config, "animations", "permission_zoom_pulse", "scale", default=1.12)
    permission = []
    for i in range(8):
        flash_color = ORANGE if i % 2 == 0 else (180, 90, 0, 255)
        if zoom_on:
            t = i / 8
            s = 1.0 + (zoom_scale - 1.0) * abs(math.sin(math.pi * t * 2))
        else:
            s = 1.0
        m = make_mascot_pil(flash_color, scale_x=s, scale_y=s)
        permission.append(place(m))
    frames["permission"] = permission

    return frames

# ---------------------------------------------------------------------------
# State reading
# ---------------------------------------------------------------------------

def read_state() -> str:
    try:
        return open(STATE_FILE).read().strip()
    except Exception:
        return "idle"

# ---------------------------------------------------------------------------
# Settings spec (shared by all tray backends)
# ---------------------------------------------------------------------------

SETTINGS_SPEC = [
    ("Idle Breathing", "Mascot gently pulses in size while waiting", None, "section", None, None),
    ("  On/Off",      "Enable or disable the breathing effect",
     ("animations", "idle_breathing", "enabled"),  "bool",  None, None),
    ("  Min size",    "How small the mascot shrinks at the bottom of the breath (1.0 = normal)",
     ("animations", "idle_breathing", "scale_min"), "float", 0.8, 1.0),
    ("  Max size",    "How large the mascot grows at the top of the breath (1.0 = normal)",
     ("animations", "idle_breathing", "scale_max"), "float", 1.0, 1.3),

    ("Squash & Stretch", "Mascot squishes on landing and stretches when jumping (tool success)", None, "section", None, None),
    ("  On/Off",      "Enable or disable squash & stretch",
     ("animations", "squash_stretch", "enabled"),  "bool",  None, None),
    ("  Amount",      "How extreme the squash/stretch is (0 = none, 1 = very exaggerated)",
     ("animations", "squash_stretch", "amount"),   "float", 0.0, 1.0),

    ("Failure Shudder", "Mascot shakes when a tool fails or errors out", None, "section", None, None),
    ("  On/Off",      "Enable or disable the failure shake",
     ("animations", "failure_shudder", "enabled"),  "bool",  None, None),
    ("  Intensity",   "How far left/right the mascot shakes (pixels)",
     ("animations", "failure_shudder", "intensity"), "int",  1, 30),
    ("  Decay",       "How quickly the shake dies down (0.1 = fast stop, 0.99 = long rattle)",
     ("animations", "failure_shudder", "decay"),    "float", 0.1, 0.99),

    ("Permission Flash", "Mascot flashes and pulses when Claude asks for your permission", None, "section", None, None),
    ("  On/Off",      "Enable or disable the permission zoom pulse",
     ("animations", "permission_zoom_pulse", "enabled"), "bool",  None, None),
    ("  Zoom",        "How big the mascot grows during the pulse (1.0 = no zoom, 1.5 = 50% bigger)",
     ("animations", "permission_zoom_pulse", "scale"),   "float", 1.0, 2.0),

    ("Success Particles", "Pixel confetti flies out when a tool succeeds", None, "section", None, None),
    ("  On/Off",      "Enable or disable the particle effect",
     ("animations", "success_particles", "enabled"), "bool",  None, None),
    ("  Count",       "How many particles shoot out (more = more festive)",
     ("animations", "success_particles", "count"),   "int",   1, 20),
]
