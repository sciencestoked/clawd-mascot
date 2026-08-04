"""
backends/macos_tray.py — macOS PyObjC menu bar tray + settings panel backend.
Called by clawd_tray.py when sys.platform == 'darwin'.
"""

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
from Foundation import NSObject, NSTimer

from clawd_core import (
    load_config, save_config, get_nested, set_nested,
    SETTINGS_SPEC, RELOAD_FILE,
)

PANEL_W  = 430
ROW_H    = 26
PAD_L    = 16
SLIDER_W = 160
FIELD_W  = 52


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


class SettingsPanel(NSObject):

    def init(self):
        self = objc.super(SettingsPanel, self).init()
        self._panel = None
        self._controls = {}
        self._slider_meta = {}
        self._snapshot = None
        self._saved = False
        return self

    def show(self):
        if self._panel is None:
            self._build()
        else:
            self._reload_values()
        self._snapshot = load_config()
        self._saved = False
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)

    def windowWillClose_(self, notification):
        if not self._saved and self._snapshot is not None:
            save_config(self._snapshot)
            open(RELOAD_FILE, "w").write("reload")
            print("[settings] cancelled — reverted to previous config")

    def _build(self):
        cfg = load_config()
        total_h = PAD_L
        for label, tooltip, path, typ, *_ in SETTINGS_SPEC:
            total_h += ROW_H + (6 if typ == "section" else 2)
        total_h += 50

        PANEL_H = min(total_h, 560)
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PANEL_W, PANEL_H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False,
        )
        self._panel.setTitle_("Clawd Settings")
        self._panel.center()
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setDelegate_(self)

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 40, PANEL_W, PANEL_H - 40))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)

        content_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_W - 16, total_h))
        scroll.setDocumentView_(content_view)
        self._panel.contentView().addSubview_(scroll)

        y = total_h - PAD_L
        for label, tooltip, path, typ, mn, mx in SETTINGS_SPEC:
            y -= ROW_H
            if typ == "section":
                y -= 6
                lbl = NSTextField.labelWithString_(label)
                lbl.setFrame_(NSMakeRect(PAD_L, y, PANEL_W - PAD_L * 2, ROW_H))
                lbl.setFont_(NSFont.boldSystemFontOfSize_(12))
                if tooltip: lbl.setToolTip_(tooltip)
                content_view.addSubview_(lbl)
            elif typ == "bool":
                cb = NSButton.alloc().initWithFrame_(NSMakeRect(PAD_L + 8, y, 300, ROW_H))
                cb.setButtonType_(AppKit.NSButtonTypeSwitch)
                cb.setTitle_(label.strip())
                if tooltip: cb.setToolTip_(tooltip)
                cb.setState_(1 if get_nested(cfg, *path, default=True) else 0)
                cb.setTarget_(self)
                cb.setAction_("checkboxChanged:")
                content_view.addSubview_(cb)
                self._controls[path] = cb
            else:
                lbl = NSTextField.labelWithString_(label.strip())
                lbl.setFrame_(NSMakeRect(PAD_L + 8, y + 4, 110, 18))
                lbl.setFont_(NSFont.systemFontOfSize_(12))
                if tooltip: lbl.setToolTip_(tooltip)
                content_view.addSubview_(lbl)

                slider = NSSlider.alloc().initWithFrame_(NSMakeRect(PAD_L + 125, y + 2, SLIDER_W, 22))
                slider.setMinValue_(mn)
                slider.setMaxValue_(mx)
                val = get_nested(cfg, *path, default=mn)
                slider.setDoubleValue_(val)
                if tooltip: slider.setToolTip_(tooltip)
                content_view.addSubview_(slider)

                field = NSTextField.alloc().initWithFrame_(
                    NSMakeRect(PAD_L + 125 + SLIDER_W + 8, y + 4, FIELD_W, 18))
                fmt = ".0f" if typ == "int" else ".2f"
                field.setStringValue_(f"{val:{fmt}}")
                field.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
                content_view.addSubview_(field)

                self._slider_meta[id(slider)] = (path, field, fmt)
                slider.setTarget_(self)
                slider.setAction_("sliderMoved:")
                self._controls[path] = (slider, field)
            y -= 2

        save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(PANEL_W - 120, 8, 100, 28))
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(NSBezelStyleRounded)
        save_btn.setTarget_(self)
        save_btn.setAction_("saveSettings:")
        self._panel.contentView().addSubview_(save_btn)

    def _write_live(self, path, value):
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
        self._snapshot = load_config()
        self._panel.orderOut_(None)
        print("[settings] saved")


class TrayApp(NSObject):

    def applicationDidFinishLaunching_(self, notification):
        self._settings = SettingsPanel.alloc().init()

        sb = NSStatusBar.systemStatusBar()
        self._item = sb.statusItemWithLength_(NSVariableStatusItemLength)
        self._item.button().setImage_(_make_dot_image(False))

        menu = NSMenu.alloc().init()

        self._start_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Start Mascot", "startMascot:", "")
        self._start_item.setTarget_(self)

        self._stop_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Stop Mascot", "stopMascot:", "")
        self._stop_item.setTarget_(self)

        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings\u2026", "openSettings:", ",")
        settings_item.setTarget_(self)

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quitApp:", "q")
        quit_item.setTarget_(self)

        menu.addItem_(self._start_item)
        menu.addItem_(self._stop_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(settings_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(quit_item)
        self._item.setMenu_(menu)

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, self, "pollProcess:", None, True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "noop:", None, True)

        self._mascot.start()
        self._refresh_ui()

    def startMascot_(self, sender):
        self._mascot.start()
        self._refresh_ui()

    def stopMascot_(self, sender):
        self._mascot.stop()
        self._refresh_ui()

    def openSettings_(self, sender):
        self._settings.show()

    def quitApp_(self, sender):
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


def run(mascot_process):
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    delegate = TrayApp.alloc().init()
    delegate._mascot = mascot_process  # set BEFORE app.run() / finishLaunching
    app.setDelegate_(delegate)
    # Manually trigger launch so _mascot is set before the delegate fires
    app.finishLaunching()
    delegate.applicationDidFinishLaunching_(None)

    def _sigint(sig, frame):
        try:
            mascot_process.stop()
        except Exception:
            pass
        print("\nBye!")
        app.terminate_(None)

    signal.signal(signal.SIGINT, _sigint)
    app.run()
