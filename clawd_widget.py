#!/usr/bin/env python3
"""
Clawd - fully transparent floating mascot for macOS.
Drag to move. Ctrl+C to quit.
"""

import math
import signal
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

STATE_FILE = "/tmp/clawd_state"

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


def make_mascot_pil(color=ORANGE):
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
    return img.resize((pw * SCALE_X, ph * SCALE_Y), Image.NEAREST)


def place(mascot, x_off=0, y_off=0):
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    bx = (CANVAS_W - mascot.width) // 2 + x_off
    by = (CANVAS_H - mascot.height) // 2 + y_off
    canvas.paste(mascot, (bx, by), mascot)
    return canvas


def generate_frames():
    N = 8
    m_o = make_mascot_pil(ORANGE)
    m_g = make_mascot_pil(GREEN)
    m_r = make_mascot_pil(RED)

    def sy(i, a=5): return int(a * math.sin(2 * math.pi * i / N))

    frames = {}
    frames["idle"] = [place(m_o, y_off=sy(i)) for i in range(N)]

    thinking = []
    for i in range(N):
        base = place(m_o, y_off=sy(i, 3))
        draw = ImageDraw.Draw(base)
        for d in range(i % 4):
            cx = (CANVAS_W + m_o.width) // 2 + 4 + d * 10
            cy = CANVAS_H // 2 - 3
            draw.rectangle([cx, cy, cx+6, cy+6], fill=GREY)
        thinking.append(base)
    frames["thinking"] = thinking

    shakes = [0, 6, 0, -6, 0, 6, 0, -6]
    frames["tool_running"] = [place(m_o, x_off=shakes[i]) for i in range(N)]
    frames["tool_success"]  = [place(m_g, y_off=int(-10*math.sin(math.pi*i/N))) for i in range(N)]
    frames["tool_failure"]  = [place(m_r, x_off=6 if i%2==0 else -6) for i in range(N)]
    frames["permission"]    = [place(make_mascot_pil(ORANGE if i%2==0 else (180,90,0,255))) for i in range(4)]

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


def read_state():
    try:
        return open(STATE_FILE).read().strip()
    except Exception:
        return "idle"


def main():
    print("Generating frames...")
    raw_frames = generate_frames()
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

    print("Ctrl+C to quit.")
    print("─" * 40)
    rl = NSRunLoop.currentRunLoop()
    idx = 0
    last = time.time()
    last_state = None

    while running[0]:
        rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
        now = time.time()
        state = read_state()

        if state != last_state:
            print(f"[clawd] state: {last_state} → {state}")
            last_state = state
            idx = 0  # reset animation on state change

        delay = DELAYS.get(state, 0.1)
        if now - last >= delay:
            pool = ns_frames.get(state, ns_frames["idle"])
            image_view.setImage_(pool[idx % len(pool)])
            idx += 1
            last = now


if __name__ == "__main__":
    main()
