#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing claude-tools from $REPO_DIR"
echo

# Ensure ~/.claude directories exist
mkdir -p ~/.claude/hooks ~/.claude/commands

# Symlink hook
ln -sf "$REPO_DIR/hooks/token-tracker.py" ~/.claude/hooks/token-tracker.py
echo "  hooks/token-tracker.py -> ~/.claude/hooks/"

# Symlink statusline
ln -sf "$REPO_DIR/statusline/statusline.py" ~/.claude/statusline.py
echo "  statusline/statusline.py -> ~/.claude/statusline.py"

# Symlink slash commands
for cmd in "$REPO_DIR"/commands/*.md; do
    [ -f "$cmd" ] || continue
    name="$(basename "$cmd")"
    ln -sf "$cmd" ~/.claude/commands/"$name"
    echo "  commands/$name -> ~/.claude/commands/"
done

# Create default config if missing
if [ ! -f ~/.claude/token-tracker.json ]; then
    cat > ~/.claude/token-tracker.json << 'EOF'
{
  "window_hours": 5,
  "window_budget": 40000000,
  "manual_usage": []
}
EOF
    echo
    echo "  Created default config at ~/.claude/token-tracker.json"
fi

# Add Stop hook to settings.json if not present
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    if ! grep -q "token-tracker.py" "$SETTINGS" 2>/dev/null; then
        echo
        echo "  NOTE: Add the Stop hook to your Claude Code settings."
        echo "  In Claude Code, ask: 'add a Stop hook that runs python3 ~/.claude/hooks/token-tracker.py'"
    fi
    if ! grep -q "statusline.py" "$SETTINGS" 2>/dev/null; then
        echo
        echo "  NOTE: Add the statusLine to your Claude Code settings."
        echo "  Add to settings.json: \"statusLine\": {\"type\": \"command\", \"command\": \"python3 ~/.claude/statusline.py\"}"
    fi
else
    echo
    echo "  NOTE: No ~/.claude/settings.json found."
    echo "  Start Claude Code first, then re-run this script."
fi

echo
echo "Done! In Claude Code, use:"
echo "  /usage-calibrate 14 3h7m    Calibrate with data from claude.ai/settings/usage"
echo "  /usage-status               Show current usage"
