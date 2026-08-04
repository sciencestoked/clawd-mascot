#!/usr/bin/env python3
"""
clawd_tray.py — macOS menu bar manager for the clawd mascot.

Runs as a persistent menu bar accessory (no Dock icon).
Launches / stops clawd_widget.py as a subprocess.
Opens a settings panel to tune config.json without editing JSON.
"""

import json
import os
import signal
import subprocess
import sys

import objc
import AppKit
from AppKit import (
    NSApplication, NSStatusBar, NSMenu, NSMenuItem,
    NSVariableStatusItemLength, NSImage, NSColor,
    NSPanel, NSTextField, NSButton, NSSlider,
    NSView, NSScrollView,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSBackingStoreBuffered,
    NSApplicationActivationPolicyAccessory,
    NSMakeRect, NSMakeSize, NSFont, NSAlert,
    NSBezelStyleRounded,
    NSBezierPath,
)
from Foundation import NSObject, NSTimer, NSRunLoop, NSDate

CONFIG_FILE  = os.path.expanduser("~/.config/claude-mascot/config.json")
WIDGET_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clawd_widget.py")
RELOAD_FILE  = "/tmp/clawd_reload"


# ---------------------------------------------------------------------------
# Config helpers
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


def get_nested(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def set_nested(d, keys, value):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


# ---------------------------------------------------------------------------
# Subprocess manager
# ---------------------------------------------------------------------------

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
# Settings panel
# ---------------------------------------------------------------------------

# Each entry: (label, tooltip, json_key_path_tuple, type, min, max)
# type = "bool" | "float" | "int"
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

PANEL_W = 430
ROW_H   = 26
PAD_L   = 16
PAD_R   = 16
SLIDER_W = 160
FIELD_W  = 52


class SettingsPanel(NSObject):

    def init(self):
        self = objc.super(SettingsPanel, self).init()
        self._panel = None
        self._controls = {}
        self._slider_meta = {}
        self._snapshot = None   # config snapshot taken on open
        self._saved = False     # did user hit Save?
        return self

    def show(self):
        if self._panel is None:
            self._build()
        else:
            self._reload_values()
        # Snapshot current config so we can revert on cancel
        self._snapshot = load_config()
        self._saved = False
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)

    def windowWillClose_(self, notification):
        if not self._saved and self._snapshot is not None:
            # User closed without saving — restore snapshot
            save_config(self._snapshot)
            open(RELOAD_FILE, "w").write("reload")
            print("[settings] cancelled — reverted to previous config")

    # ------------------------------------------------------------------
    def _build(self):
        cfg = load_config()

        # Calculate total content height
        total_h = PAD_L
        for label, tooltip, path, typ, *_ in SETTINGS_SPEC:
            total_h += ROW_H + (6 if typ == "section" else 2)
        total_h += 50   # save button

        PANEL_H = min(total_h, 560)

        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PANEL_W, PANEL_H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setTitle_("Clawd Settings")
        self._panel.center()
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setDelegate_(self)

        # Scrollable content view
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 40, PANEL_W, PANEL_H - 40)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)

        content_view = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_W - 16, total_h)
        )
        scroll.setDocumentView_(content_view)
        self._panel.contentView().addSubview_(scroll)

        # Build rows bottom-up (Cocoa coords: y=0 at bottom)
        y = total_h - PAD_L
        for label, tooltip, path, typ, mn, mx in SETTINGS_SPEC:
            y -= ROW_H
            if typ == "section":
                y -= 6
                lbl = NSTextField.labelWithString_(label)
                lbl.setFrame_(NSMakeRect(PAD_L, y, PANEL_W - PAD_L * 2, ROW_H))
                lbl.setFont_(NSFont.boldSystemFontOfSize_(12))
                if tooltip:
                    lbl.setToolTip_(tooltip)
                content_view.addSubview_(lbl)
            elif typ == "bool":
                cb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(PAD_L + 8, y, 300, ROW_H)
                )
                cb.setButtonType_(AppKit.NSButtonTypeSwitch)
                cb.setTitle_(label.strip())
                if tooltip:
                    cb.setToolTip_(tooltip)
                state = get_nested(cfg, *path, default=True)
                cb.setState_(1 if state else 0)
                cb.setTarget_(self)
                cb.setAction_("checkboxChanged:")
                content_view.addSubview_(cb)
                self._controls[path] = cb
            else:
                # Label
                lbl = NSTextField.labelWithString_(label.strip())
                lbl.setFrame_(NSMakeRect(PAD_L + 8, y + 4, 110, 18))
                lbl.setFont_(NSFont.systemFontOfSize_(12))
                if tooltip:
                    lbl.setToolTip_(tooltip)
                content_view.addSubview_(lbl)

                # Slider
                slider = NSSlider.alloc().initWithFrame_(
                    NSMakeRect(PAD_L + 125, y + 2, SLIDER_W, 22)
                )
                slider.setMinValue_(mn)
                slider.setMaxValue_(mx)
                val = get_nested(cfg, *path, default=mn)
                slider.setDoubleValue_(val)
                if tooltip:
                    slider.setToolTip_(tooltip)
                content_view.addSubview_(slider)

                # Value field
                field = NSTextField.alloc().initWithFrame_(
                    NSMakeRect(PAD_L + 125 + SLIDER_W + 8, y + 4, FIELD_W, 18)
                )
                fmt = ".0f" if typ == "int" else ".2f"
                field.setStringValue_(f"{val:{fmt}}")
                field.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
                content_view.addSubview_(field)

                # Wire slider -> live update + write config
                self._slider_meta[id(slider)] = (path, field, fmt)
                slider.setTarget_(self)
                slider.setAction_("sliderMoved:")

                self._controls[path] = (slider, field)
            y -= 2

        # Save button (pinned to bottom of panel, outside scroll)
        save_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(PANEL_W - 120, 8, 100, 28)
        )
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_("saveSettings:")
        self._panel.contentView().addSubview_(save_btn)

    def _write_live(self, path, value):
        """Write a single value to config and signal the widget to reload."""
        cfg = load_config()
        set_nested(cfg, list(path), value)
        save_config(cfg)
        open(RELOAD_FILE, "w").write("reload")

    def sliderMoved_(self, sender):
        meta = self._slider_meta.get(id(sender))
        if not meta:
            return
        path, field, fmt = meta
        val = sender.doubleValue()
        if fmt == ".0f":
            val = int(round(val))
        field.setStringValue_(f"{val:{fmt}}")
        self._write_live(path, val)

    def checkboxChanged_(self, sender):
        for path, ctrl in self._controls.items():
            if ctrl is sender:
                self._write_live(path, bool(sender.state()))
                return

    def _reload_values(self):
        cfg = load_config()
        for path, ctrl in self._controls.items():
            val = get_nested(cfg, *path)
            if val is None:
                continue
            if isinstance(ctrl, tuple):
                slider, field = ctrl
                meta = self._slider_meta.get(id(slider))
                fmt = meta[2] if meta else ".2f"
                slider.setDoubleValue_(val)
                field.setStringValue_(f"{val:{fmt}}")
            else:
                ctrl.setState_(1 if val else 0)

    def saveSettings_(self, sender):
        self._saved = True
        self._snapshot = load_config()  # update snapshot to current
        self._panel.orderOut_(None)
        print("[settings] saved")


# ---------------------------------------------------------------------------
# Tray app
# ---------------------------------------------------------------------------

def _make_dot_image(filled: bool) -> NSImage:
    img = NSImage.alloc().initWithSize_(NSMakeSize(18, 18))
    img.lockFocus()
    if filled:
        NSColor.colorWithRed_green_blue_alpha_(1.0, 0.55, 0.0, 1.0).setFill()
    else:
        NSColor.colorWithWhite_alpha_(0.55, 1.0).setFill()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(3, 3, 12, 12)).fill()
    img.unlockFocus()
    return img


class TrayApp(NSObject):

    def applicationDidFinishLaunching_(self, notification):
        self._mascot = MascotProcess()
        self._settings = SettingsPanel.alloc().init()

        # Status bar item
        sb = NSStatusBar.systemStatusBar()
        self._item = sb.statusItemWithLength_(NSVariableStatusItemLength)
        self._item.button().setImage_(_make_dot_image(False))

        # Menu
        menu = NSMenu.alloc().init()

        self._start_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Start Mascot", "startMascot:", "",
        )
        self._start_item.setTarget_(self)

        self._stop_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Stop Mascot", "stopMascot:", "",
        )
        self._stop_item.setTarget_(self)

        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings\u2026", "openSettings:", ",",
        )
        settings_item.setTarget_(self)

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quitApp:", "q",
        )
        quit_item.setTarget_(self)

        menu.addItem_(self._start_item)
        menu.addItem_(self._stop_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(settings_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(quit_item)

        self._item.setMenu_(menu)

        # Poll process status every 2s (widget can be right-click-closed)
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, self, "pollProcess:", None, True,
        )

        # Wake runloop every 0.5s so Python SIGINT handler can fire
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "noop:", None, True,
        )

        # Auto-start
        self._mascot.start()
        self._refresh_ui()

    def startMascot_(self, sender):
        print("[tray] startMascot clicked")
        self._mascot.start()
        self._refresh_ui()

    def stopMascot_(self, sender):
        print("[tray] stopMascot clicked")
        self._mascot.stop()
        self._refresh_ui()

    def openSettings_(self, sender):
        print("[tray] openSettings clicked")
        self._settings.show()

    def quitApp_(self, sender):
        print("[tray] quit clicked")
        self._mascot.stop()
        NSApplication.sharedApplication().terminate_(None)

    def pollProcess_(self, timer):
        self._refresh_ui()

    def noop_(self, timer):
        pass

    def _refresh_ui(self):
        running = self._mascot.running
        self._item.button().setImage_(_make_dot_image(running))
        self._start_item.setEnabled_(not running)
        self._stop_item.setEnabled_(running)

    def applicationWillTerminate_(self, notification):
        self._mascot.stop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    delegate = TrayApp.alloc().init()
    app.setDelegate_(delegate)

    def _sigint(sig, frame):
        delegate._mascot.stop()
        print("\nBye!")
        app.terminate_(None)

    signal.signal(signal.SIGINT, _sigint)

    app.run()


if __name__ == "__main__":
    main()
