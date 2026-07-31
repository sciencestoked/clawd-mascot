# Clawd 🟠

A floating transparent animated desktop mascot for [Claude Code](https://claude.ai/code) on macOS.

Clawd lives on your desktop and reacts to what Claude is doing in real time — bobbing when idle, spinning when running tools, bouncing when done.

![Clawd floating over desktop](screenshot.png)

## What it looks like

- Fully transparent window — just the orange pixel mascot floating over everything
- Reacts to Claude's state: idle → thinking → working → done/error
- Draggable, always on top, close with the red dot

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

- macOS
- Python 3 with PyObjC and Pillow:
  ```
  pip install pyobjc pillow
  ```

## Setup

### 1. Add Claude Code hooks

Add this to your `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart":       [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }],
    "UserPromptSubmit":   [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }],
    "PreToolUse":         [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }],
    "PostToolUse":        [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }],
    "PostToolUseFailure": [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }],
    "PermissionRequest":  [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }],
    "Stop":               [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }],
    "SessionEnd":         [{ "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/clawd/hook.sh" }] }]
  }
}
```

### 2. Make hook executable

```bash
chmod +x hook.sh
```

### 3. Run Clawd

```bash
python3 clawd_widget.py
```

## How it works

- `hook.sh` — called by Claude Code on every lifecycle event, writes current state to `/tmp/clawd_state`
- `clawd_widget.py` — PyObjC app that reads `/tmp/clawd_state` every frame and animates accordingly

The mascot is rendered from the official Claude Code pixel art characters (`▐▛███▜▌`) upscaled with correct terminal aspect ratio.

## Controls

- **Drag** the title bar area to move
- **Red dot** to close
- **Ctrl+C** in terminal to quit

## Credits

Built with Claude Code + Claude Sonnet 4.6
