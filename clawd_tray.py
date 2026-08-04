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

CONFIG_FILE = os.path.expanduser("~/.config/claude-mascot/config.json")
WIDGET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clawd_widget.py")


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

# Each entry: (label, json_key_path_tuple, type, min, max, step)
# type = "bool" | "float" | "int"
SETTINGS_SPEC = [
    ("Idle Breathing", None, "section", None, None, None),
    ("  enabled",           ("animations", "idle_breathing", "enabled"),  "bool",  None, None, None),
    ("  scale_min",         ("animations", "idle_breathing", "scale_min"), "float", 0.5, 1.5, 0.01),
    ("  scale_max",         ("animations", "idle_breathing", "scale_max"), "float", 0.5, 1.5, 0.01),

    ("Squash & Stretch", None, "section", None, None, None),
    ("  enabled",           ("animations", "squash_stretch", "enabled"),  "bool",  None, None, None),
    ("  amount",            ("animations", "squash_stretch", "amount"),   "float", 0.0, 1.0, 0.01),

    ("Failure Shudder", None, "section", None, None, None),
    ("  enabled",           ("animations", "failure_shudder", "enabled"),  "bool",  None, None, None),
    ("  intensity",         ("animations", "failure_shudder", "intensity"), "int",  1, 30, 1),
    ("  decay",             ("animations", "failure_shudder", "decay"),    "float", 0.1, 0.99, 0.01),

    ("Permission Zoom Pulse", None, "section", None, None, None),
    ("  enabled",           ("animations", "permission_zoom_pulse", "enabled"), "bool",  None, None, None),
    ("  scale",             ("animations", "permission_zoom_pulse", "scale"),   "float", 1.0, 2.0, 0.01),

    ("Success Particles", None, "section", None, None, None),
    ("  enabled",           ("animations", "success_particles", "enabled"), "bool",  None, None, None),
    ("  count",             ("animations", "success_particles", "count"),   "int",   1, 20, 1),
]

PANEL_W = 430
ROW_H   = 26
PAD_L   = 16
PAD_R   = 16
SLIDER_W = 160
FIELD_W  = 52


class SettingsPanel(NSObject):

    def init(self):
        self = super().init()
        self._panel = None
        self._controls = {}   # path_tuple -> (slider, field) or checkbox NSButton
        return self

    def show(self):
        if self._panel is None:
            self._build()
        else:
            self._reload_values()
        self._panel.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    # ------------------------------------------------------------------
    def _build(self):
        cfg = load_config()

        # Calculate total content height
        total_h = PAD_L
        for label, path, typ, *_ in SETTINGS_SPEC:
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
        for label, path, typ, mn, mx, step in SETTINGS_SPEC:
            y -= ROW_H
            if typ == "section":
                y -= 6
                lbl = NSTextField.labelWithString_(label)
                lbl.setFrame_(NSMakeRect(PAD_L, y, PANEL_W - PAD_L * 2, ROW_H))
                lbl.setFont_(NSFont.boldSystemFontOfSize_(12))
                content_view.addSubview_(lbl)
            elif typ == "bool":
                cb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(PAD_L + 8, y, 300, ROW_H)
                )
                cb.setButtonType_(AppKit.NSButtonTypeSwitch)
                cb.setTitle_(label.strip())
                state = get_nested(cfg, *path, default=True)
                cb.setState_(1 if state else 0)
                content_view.addSubview_(cb)
                self._controls[path] = cb
            else:
                # Label
                lbl = NSTextField.labelWithString_(label.strip())
                lbl.setFrame_(NSMakeRect(PAD_L + 8, y + 4, 110, 18))
                lbl.setFont_(NSFont.systemFontOfSize_(12))
                content_view.addSubview_(lbl)

                # Slider
                slider = NSSlider.alloc().initWithFrame_(
                    NSMakeRect(PAD_L + 125, y + 2, SLIDER_W, 22)
                )
                slider.setMinValue_(mn)
                slider.setMaxValue_(mx)
                val = get_nested(cfg, *path, default=mn)
                slider.setDoubleValue_(val)
                content_view.addSubview_(slider)

                # Value field
                field = NSTextField.alloc().initWithFrame_(
                    NSMakeRect(PAD_L + 125 + SLIDER_W + 8, y + 4, FIELD_W, 18)
                )
                fmt = ".0f" if typ == "int" else ".2f"
                field.setStringValue_(f"{val:{fmt}}")
                field.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
                content_view.addSubview_(field)

                # Wire slider -> field live update
                slider._field = field
                slider._fmt = fmt
                slider.setTarget_(self)
                slider.setAction_(objc.selector(
                    self._sliderMoved_,
                    signature=b'v@:@'
                ))

                self._controls[path] = (slider, field)
            y -= 2

        # Save button (pinned to bottom of panel, outside scroll)
        save_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(PANEL_W - 120, 8, 100, 28)
        )
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_(objc.selector(self._save_, signature=b'v@:@'))
        self._panel.contentView().addSubview_(save_btn)

    def _sliderMoved_(self, sender):
        val = sender.doubleValue()
        field = sender._field
        fmt = sender._fmt
        field.setStringValue_(f"{val:{fmt}}")

    def _reload_values(self):
        cfg = load_config()
        for path, ctrl in self._controls.items():
            val = get_nested(cfg, *path)
            if val is None:
                continue
            if isinstance(ctrl, tuple):
                slider, field = ctrl
                slider.setDoubleValue_(val)
                field.setStringValue_(f"{val:{slider._fmt}}")
            else:
                ctrl.setState_(1 if val else 0)

    def _save_(self, sender):
        cfg = load_config()
        for path, ctrl in self._controls.items():
            if isinstance(ctrl, tuple):
                slider, field = ctrl
                # prefer typed field value if it differs
                try:
                    typed = float(field.stringValue())
                    # clamp to slider range
                    typed = max(slider.minValue(), min(slider.maxValue(), typed))
                except ValueError:
                    typed = slider.doubleValue()
                # keep int for int fields
                if slider._fmt == ".0f":
                    typed = int(round(typed))
                set_nested(cfg, list(path), typed)
            else:
                set_nested(cfg, list(path), bool(ctrl.state()))

        save_config(cfg)

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Settings saved.")
        alert.setInformativeText_("Changes take effect next time the mascot starts.")
        alert.runModal()


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
            "Start Mascot",
            objc.selector(self._startMascot_, signature=b'v@:@'),
            "",
        )
        self._start_item.setTarget_(self)

        self._stop_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Stop Mascot",
            objc.selector(self._stopMascot_, signature=b'v@:@'),
            "",
        )
        self._stop_item.setTarget_(self)

        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings\u2026",
            objc.selector(self._openSettings_, signature=b'v@:@'),
            ",",
        )
        settings_item.setTarget_(self)

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit",
            objc.selector(self._quit_, signature=b'v@:@'),
            "q",
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
            2.0,
            self,
            objc.selector(self._poll_, signature=b'v@:@'),
            None,
            True,
        )

        # Auto-start
        self._mascot.start()
        self._refresh_ui()

    def _startMascot_(self, sender):
        self._mascot.start()
        self._refresh_ui()

    def _stopMascot_(self, sender):
        self._mascot.stop()
        self._refresh_ui()

    def _openSettings_(self, sender):
        self._settings.show()

    def _quit_(self, sender):
        self._mascot.stop()
        NSApplication.sharedApplication().terminate_(None)

    def _poll_(self, timer):
        self._refresh_ui()

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
    signal.signal(signal.SIGTERM, lambda *_: NSApplication.sharedApplication().terminate_(None))

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    delegate = TrayApp.alloc().init()
    app.setDelegate_(delegate)

    app.run()


if __name__ == "__main__":
    main()
