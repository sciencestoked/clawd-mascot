# clawd-mascot 🟠

A floating transparent animated desktop mascot for [Claude Code](https://claude.ai/code) on macOS.

Clawd lives on your desktop and reacts to what Claude is doing in real time — bobbing when idle, spinning when running tools, bouncing when done.

![Clawd demo](demo.gif)

> **macOS only** — uses PyObjC (native macOS framework)

## States

| State | Animation |
|-------|-----------|
| Idle | Gentle bob up and down |
| Thinking | Bob + cycling dots `...` |
| Tool running | Fast shake left/right |
| Tool success | Green bounce |
| Tool failure | Red shake |
| Permission needed | Orange flash |

## Requirements

- macOS 12+
- Python 3.8+ (use `python3 --version` to check)
- [Claude Code](https://claude.ai/code) installed

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/sciencestoked/clawd-mascot.git
cd clawd-mascot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> If `pip` isn't found, try `pip3`. If you're on a fresh Mac, install Python via [Homebrew](https://brew.sh): `brew install python`

### 3. Make the hook executable

```bash
chmod +x hook.sh
```

### 4. Add Claude Code hooks

Open `~/.claude/settings.json` in any editor. If it doesn't exist, create it.

Add the `hooks` block below, replacing `/path/to/clawd-mascot` with the **absolute path** to where you cloned this repo (e.g. `/Users/yourname/clawd-mascot`):

```json
{
  "hooks": {
    "SessionStart":       [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }],
    "UserPromptSubmit":   [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }],
    "PreToolUse":         [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }],
    "PostToolUse":        [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }],
    "PostToolUseFailure": [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }],
    "PermissionRequest":  [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }],
    "Stop":               [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }],
    "SessionEnd":         [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd-mascot/hook.sh" }] }]
  }
}
```

> If your `settings.json` already has content, just add the `"hooks"` key alongside your existing keys — don't replace the whole file.

**Restart Claude Code** after saving settings.json for the hooks to take effect.

### 5. Run Clawd

**Option A — menu bar tray (recommended)**

```bash
python3 clawd_tray.py
```

An orange dot appears in your menu bar. Click it to start/stop the mascot or open Settings.

**Option B — widget only**

```bash
python3 clawd_widget.py
# or with debug mode to cycle through all animation states:
python3 clawd_widget.py --debug
```

## Controls

- **Drag** the title bar area (above the mascot) to move him anywhere on screen
- **Right-click** the mascot to close it
- **Menu bar dot** → Stop Mascot to hide him
- **Menu bar dot** → Settings… to tune animations live

## How it works

- `hook.sh` — registered as a Claude Code lifecycle hook, writes the current state to `/tmp/clawd_state` on every event (thinking, tool running, done, etc.)
- `clawd_widget.py` — native macOS PyObjC window (fully transparent, always on top) that polls `/tmp/clawd_state` and animates the mascot accordingly
- `clawd_tray.py` — menu bar tray app that launches the widget as a subprocess and provides a settings panel for `config.json`
- `config.json` — animation toggles and numeric params (intensity, scale, etc.) — edit directly or use the Settings panel

The mascot pixel art is derived from the official Claude Code startup screen pixel art, upscaled with the correct terminal character aspect ratio using Python + Pillow.

## Credits

Built with Claude Code + Claude Sonnet 4.6
