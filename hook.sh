#!/bin/bash
# Claude Code hook - writes current state to a temp file
# Called by Claude Code on every lifecycle event

STATE_FILE="/tmp/clawd_state"

# Read JSON from stdin
INPUT=$(cat)
EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4)

case "$EVENT" in
  "UserPromptSubmit")
    echo "thinking" > "$STATE_FILE"
    ;;
  "PreToolUse")
    echo "tool_running" > "$STATE_FILE"
    ;;
  "PostToolUse")
    echo "tool_success" > "$STATE_FILE"
    ;;
  "PostToolUseFailure")
    echo "tool_failure" > "$STATE_FILE"
    ;;
  "PermissionRequest")
    echo "permission" > "$STATE_FILE"
    ;;
  "Stop"|"SessionEnd")
    echo "idle" > "$STATE_FILE"
    ;;
  "SessionStart")
    echo "idle" > "$STATE_FILE"
    ;;
esac

exit 0
