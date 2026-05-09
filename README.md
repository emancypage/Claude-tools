# claude-tools

StatusLine script for Claude Code — shows real-time rate limit usage, context size, and session cost in the persistent bar at the bottom of the terminal.

## What you see

```
Sonnet 4.6 | ctx:26K(99%) | 5h:42% 0h07m ██████░░░░░░░░░ | $0.21
```

- **Model** — current model name
- **ctx** — context window tokens (color: green < 80K, yellow < 120K, red < 180K); percentage is cache hit rate
- **5h** — 5h rate limit utilization with progress bar and time until reset
- **7d** — 7d rate limit utilization (only shown when > 50%)
- **$cost** — session cost (only shown when > $0.01)

Colors on percentages: green < 50%, yellow < 70%, red < 90%, bold red ≥ 90%.

## How it works

Claude Code calls `statusline.py` on every message update (throttled to ~300ms). The script reads a JSON payload from stdin with `model`, `context_window`, `rate_limits`, and `cost` fields, then prints one line — Claude Code displays it as the status bar.

Rate limit data comes directly from Anthropic's servers via Claude Code — no separate API calls. The script also writes this data to `~/.claude/rate-limit-cache.json` so other tools can read it without extra requests.

Requires Claude Code >= 2.1.80.

## Installation

```bash
git clone <repo-url> ~/Dev/claude-tools
cd ~/Dev/claude-tools
./install.sh
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/statusline.py"
  }
}
```

## Slash commands

- `/usage-status` — show current 5h/7d usage breakdown from cache

## Structure

```
claude-tools/
├── statusline/statusline.py    # StatusLine script
├── commands/usage-status.md    # /usage-status slash command
├── install.sh                  # Setup symlinks
└── README.md
```

## Requirements

- Python 3.8+ (stdlib only)
- Claude Code >= 2.1.80
