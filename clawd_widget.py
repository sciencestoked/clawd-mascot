#!/usr/bin/env python3
"""
Clawd - fully transparent floating mascot for macOS.
Drag to move. Ctrl+C to quit.
"""

import json
import math
import os
import signal
import sys
import threading
import time

from PIL import Image, ImageDraw

import objc
import AppKit
from AppKit import (
    NSApplication, NSWindow, NSImageView, NSImage,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSColor,
    NSBitmapImageRep, NSDeviceRGBColorSpace,
    NSApplicationActivationPolicyAccessory,
    NSMakeRect,
)
from Foundation import NSRunLoop, NSDate, NSObject, NSPoint
from AppKit import NSView, NSEvent

STATE_FILE  = "/tmp/clawd_state"
CONFIG_FILE = os.path.expanduser("~/.config/claude-mascot/config.json")

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def cfg(config, *keys, default=None):
    """Safe nested config access."""
    val = config
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val

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


def make_mascot_pil(color=ORANGE, scale_x=1.0, scale_y=1.0):
    """Render mascot pixel art, optionally squashed/stretched."""
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


def place(mascot, x_off=0, y_off=0):
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    bx = (CANVAS_W - mascot.width) // 2 + x_off
    by = (CANVAS_H - mascot.height) // 2 + y_off
    canvas.paste(mascot, (bx, by), mascot)
    return canvas


def add_particles(canvas, config, frame_i, total_frames):
    """Draw pixel particles flying outward from center on success."""
    count = cfg(config, "animations", "success_particles", "count", default=6)
    color = tuple(cfg(config, "animations", "success_particles", "color", default=[0,220,80]))
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
        draw.rectangle([px, py, px+size, py+size], fill=color + (alpha,))


def generate_frames(config=None):
    if config is None:
        config = {}
    N = 8

    # --- idle: breathing (scale pulse) or plain bob ---
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

    # --- thinking: bob + dots ---
    m_o = make_mascot_pil(ORANGE)
    thinking = []
    for i in range(N):
        bob = int(3 * math.sin(2 * math.pi * i / N))
        base = place(m_o, y_off=bob)
        draw = ImageDraw.Draw(base)
        for d in range(i % 4):
            cx = (CANVAS_W + m_o.width) // 2 + 4 + d * 10
            cy = CANVAS_H // 2 - 3
            draw.rectangle([cx, cy, cx+6, cy+6], fill=GREY)
        thinking.append(base)
    frames["thinking"] = thinking

    # --- tool_running: shake ---
    shakes = [0, 6, 0, -6, 0, 6, 0, -6]
    frames["tool_running"] = [place(m_o, x_off=shakes[i]) for i in range(N)]

    # --- tool_success: 3 bounces with squash/stretch + particles ---
    ss_on     = cfg(config, "animations", "squash_stretch", "enabled", default=True)
    ss_amount = cfg(config, "animations", "squash_stretch", "amount", default=0.25)
    pt_on     = cfg(config, "animations", "success_particles", "enabled", default=True)
    total     = 16
    success   = []
    for i in range(total):
        t        = i / total
        bounce   = abs(math.sin(3 * math.pi * t))  # 3 arcs
        y_off    = int(-14 * bounce)
        if ss_on:
            # at peak: stretch tall; at bottom: squash wide
            sy_s = 1.0 + ss_amount * bounce          # taller at peak
            sx_s = 1.0 - (ss_amount * 0.5) * bounce  # slightly narrower at peak
        else:
            sx_s = sy_s = 1.0
        m  = make_mascot_pil(GREEN, scale_x=sx_s, scale_y=sy_s)
        canvas = place(m, y_off=y_off)
        if pt_on:
            add_particles(canvas, config, i, total)
        success.append(canvas)
    frames["tool_success"] = success

    # --- tool_failure: shudder (decaying shake) ---
    shudder_on  = cfg(config, "animations", "failure_shudder", "enabled", default=True)
    intensity   = cfg(config, "animations", "failure_shudder", "intensity", default=8)
    decay       = cfg(config, "animations", "failure_shudder", "decay", default=0.75)
    m_r         = make_mascot_pil(RED)
    failure     = []
    for i in range(12):
        if shudder_on:
            amp   = intensity * (decay ** i)
            x_off = int(amp * (1 if i % 2 == 0 else -1))
        else:
            x_off = 6 if i % 2 == 0 else -6
        failure.append(place(m_r, x_off=x_off))
    frames["tool_failure"] = failure

    # --- permission: color flash + zoom pulse ---
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


def pil_to_nsimage(pil_img):
    rgba = pil_img.convert("RGBA")
    w, h = rgba.size
    data = rgba.tobytes()
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, w, h, 8, 4, True, False,
        NSDeviceRGBColorSpace, w * 4, 32
    )
    rep.bitmapData()[:len(data)] = data
    ns_img = NSImage.alloc().initWithSize_((w, h))
    ns_img.addRepresentation_(rep)
    return ns_img


class DragView(NSView):
    """Transparent NSView — click anywhere on mascot to drag."""
    def mouseDown_(self, event):
        self._start = event.locationInWindow()

    def mouseDragged_(self, event):
        loc = event.locationInWindow()
        win = self.window()
        frame = win.frame()
        dx = loc.x - self._start.x
        dy = loc.y - self._start.y
        win.setFrameOrigin_(NSPoint(frame.origin.x + dx, frame.origin.y + dy))

    def rightMouseDown_(self, event):
        import sys
        sys.exit(0)

    def acceptsFirstMouse_(self, event):
        return True


class PassthroughImageView(NSImageView):
    """NSImageView that passes ALL mouse events up to DragView."""
    def mouseDown_(self, event):
        self.superview().mouseDown_(event)

    def mouseDragged_(self, event):
        self.superview().mouseDragged_(event)

    def rightMouseDown_(self, event):
        self.superview().rightMouseDown_(event)

    def acceptsFirstMouse_(self, event):
        return True


DEBUG_STATES = ["idle", "thinking", "tool_running", "tool_success", "tool_failure", "permission"]
DEBUG_DURATION = 1.5  # seconds per state

def read_state(debug=False, debug_state=None):
    if debug:
        return debug_state
    try:
        return open(STATE_FILE).read().strip()
    except Exception:
        return "idle"


def main():
    print("Generating frames...")
    config = load_config()
    raw_frames = generate_frames(config)
    ns_frames = {k: [pil_to_nsimage(f) for f in v] for k, v in raw_frames.items()}
    print("Done!")

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    screen = AppKit.NSScreen.mainScreen().frame()
    sw, sh = screen.size.width, screen.size.height

    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(sw // 2 - CANVAS_W // 2, sh // 2 - CANVAS_H // 2, CANVAS_W, CANVAS_H),
        AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable | AppKit.NSWindowStyleMaskFullSizeContentView,
        NSBackingStoreBuffered,
        False,
    )
    win.setTitlebarAppearsTransparent_(True)
    win.setTitleVisibility_(AppKit.NSWindowTitleHidden)
    win.standardWindowButton_(AppKit.NSWindowMiniaturizeButton).setHidden_(True)
    win.standardWindowButton_(AppKit.NSWindowZoomButton).setHidden_(True)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setOpaque_(False)
    win.setHasShadow_(False)
    win.setLevel_(NSFloatingWindowLevel + 1)
    win.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
        AppKit.NSWindowCollectionBehaviorStationary
    )

    drag_view = DragView.alloc().initWithFrame_(
        NSMakeRect(0, 0, CANVAS_W, CANVAS_H)
    )
    win.setContentView_(drag_view)

    image_view = PassthroughImageView.alloc().initWithFrame_(
        NSMakeRect(0, 0, CANVAS_W, CANVAS_H)
    )
    image_view.setImageScaling_(AppKit.NSImageScaleNone)
    image_view.setEditable_(False)
    drag_view.addSubview_(image_view)
    # Let mouse events fall through image view to drag view
    win.setIgnoresMouseEvents_(False)
    image_view.setWantsLayer_(True)

    # CRITICAL: orderFrontRegardless for accessory-policy apps
    win.orderFrontRegardless()
    print(f"Window created at center screen ({sw//2}, {sh//2}), visible={win.isVisible()}")

    # Ctrl+C handler
    running = [True]
    def handle_sigint(sig, frame):
        running[0] = False
    signal.signal(signal.SIGINT, handle_sigint)

    # Set first frame immediately so window has content
    first = ns_frames["idle"][0]
    image_view.setImage_(first)

    debug_mode = "--debug" in sys.argv
    if debug_mode:
        print("🔧 DEBUG MODE — cycling through all states (1.5s each, looping)")
    print("Ctrl+C to quit.")
    print("─" * 40)

    rl = NSRunLoop.currentRunLoop()
    idx = 0
    last = time.time()
    last_state = None
    debug_idx = 0
    debug_last = time.time()

    while running[0]:
        rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
        now = time.time()

        if debug_mode:
            if now - debug_last >= DEBUG_DURATION:
                debug_idx = (debug_idx + 1) % len(DEBUG_STATES)
                debug_last = now
            state = DEBUG_STATES[debug_idx]
        else:
            state = read_state()

        if state != last_state:
            print(f"[clawd] state: {last_state} → {state}")
            last_state = state
            idx = 0

        delay = DELAYS.get(state, 0.1)
        if now - last >= delay:
            pool = ns_frames.get(state, ns_frames["idle"])
            image_view.setImage_(pool[idx % len(pool)])
            idx += 1
            last = now


if __name__ == "__main__":
    main()
