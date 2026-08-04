"""
backends/macos_widget.py — macOS PyObjC floating window backend.
Called by clawd_widget.py when sys.platform == 'darwin'.
"""

import os
import signal
import sys
import time

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

from clawd_core import (
    load_config, generate_frames, read_state,
    CANVAS_W, CANVAS_H, DELAYS, RELOAD_FILE,
    DEBUG_STATES, DEBUG_DURATION,
)


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
        sys.exit(0)

    def acceptsFirstMouse_(self, event):
        return True


class PassthroughImageView(NSImageView):
    def mouseDown_(self, event):
        self.superview().mouseDown_(event)

    def mouseDragged_(self, event):
        self.superview().mouseDragged_(event)

    def rightMouseDown_(self, event):
        self.superview().rightMouseDown_(event)

    def acceptsFirstMouse_(self, event):
        return True


def run(debug_mode=False):
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

    drag_view = DragView.alloc().initWithFrame_(NSMakeRect(0, 0, CANVAS_W, CANVAS_H))
    win.setContentView_(drag_view)

    image_view = PassthroughImageView.alloc().initWithFrame_(NSMakeRect(0, 0, CANVAS_W, CANVAS_H))
    image_view.setImageScaling_(AppKit.NSImageScaleNone)
    image_view.setEditable_(False)
    drag_view.addSubview_(image_view)
    win.setIgnoresMouseEvents_(False)
    image_view.setWantsLayer_(True)

    win.orderFrontRegardless()
    print(f"Window created at center screen ({sw//2}, {sh//2}), visible={win.isVisible()}")

    running = [True]
    def handle_sigint(sig, frame):
        running[0] = False
    signal.signal(signal.SIGINT, handle_sigint)

    image_view.setImage_(ns_frames["idle"][0])

    if debug_mode:
        print("DEBUG MODE — cycling through all states (1.5s each, looping)")
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

        if os.path.exists(RELOAD_FILE):
            try:
                os.remove(RELOAD_FILE)
            except OSError:
                pass
            print("[clawd] reloading config...")
            config = load_config()
            raw_frames = generate_frames(config)
            ns_frames = {k: [pil_to_nsimage(f) for f in v] for k, v in raw_frames.items()}
            idx = 0
            print("[clawd] reload done")

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
