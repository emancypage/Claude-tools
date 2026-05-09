#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing claude-tools from $REPO_DIR"
echo

mkdir -p ~/.claude/commands

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

# Check settings.json
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    if ! grep -q "statusline.py" "$SETTINGS" 2>/dev/null; then
        echo
        echo "  NOTE: Add statusLine to ~/.claude/settings.json:"
        echo '  "statusLine": {"type": "command", "command": "python3 ~/.claude/statusline.py"}'
    fi
else
    echo
    echo "  NOTE: No ~/.claude/settings.json found. Start Claude Code first."
fi

echo
echo "Done! In Claude Code, use:"
echo "  /usage-status    Show current 5h/7d rate limit usage"
