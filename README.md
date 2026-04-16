# claude-tools

Token usage tracker for Claude Code with real-time rate limit monitoring.

## What it does

Two-part system that tracks your Claude Code usage against the 5h and 7d rate limit windows:

- **StatusLine** — persistent bar always visible in Claude Code, including during responses
- **Stop hook** — detailed usage breakdown printed after every response

Both use **real server-side utilization data** from Claude Code's stdin JSON (requires Claude Code >= 2.1.80) — no API calls, no cost.

## Installation

```bash
git clone <repo-url> ~/Dev/claude-tools
cd ~/Dev/claude-tools
./install.sh
```

`install.sh` creates symlinks to `~/.claude/`:
- `statusline.py` — statusLine script (persistent bar + cache writer)
- `hooks/token-tracker.py` — Stop hook + CLI
- `commands/usage-calibrate.md` — `/usage-calibrate` slash command
- `commands/usage-status.md` — `/usage-status` slash command

Then add both hooks to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/statusline.py"
  },
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/token-tracker.py"
          }
        ]
      }
    ]
  }
}
```

## How it works

### Dual-hook architecture

```
Claude Code stdin JSON
  │
  ├─► statusLine script
  │     ├─ reads rate_limits from stdin (free, real-time)
  │     ├─ writes to ~/.claude/rate-limit-cache.json
  │     └─ displays persistent status bar
  │
  └─► Stop hook (after each response)
        ├─ reads rate-limit-cache.json (no API call needed)
        ├─ parses all .jsonl transcripts in the 5h window
        ├─ computes weighted token usage across sessions/models
        ├─ auto-calibrates window_budget from server utilization
        └─ prints detailed usage line
```

The statusLine script acts as the data source — it receives `rate_limits.five_hour.used_percentage` and `rate_limits.seven_day.used_percentage` from Claude Code's stdin JSON and writes them to a shared cache file. The Stop hook reads this cache instead of making its own API calls.

### What you see

**StatusLine** (always visible):

```
Opus 4.6 | ctx:16K(45%) | 5h:46% 0h36m ███████░░░░░░░░ | $0.15
```

- Model name
- Context window size (color-coded: green < 80K, yellow < 120K, red < 180K, bold red >= 180K)
- 5h rate limit with progress bar and time until reset
- 7d rate limit (only shown if > 50%)
- Session cost

**Stop hook** (after each response):

```
[usage] ctx: 125K (cache: 87%) | session: 12.8% | 1h25m left: 47.0%S ████████████████████░░░░░░░░░░
```

- `ctx` — current context window size with cache hit rate
- `session` — this session's share of the 5h budget (weighted local estimate)
- `47.0%S` — total 5h window usage from server (`S` = server, `L` = local fallback)
- Progress bar

Use `/usage-status` for a detailed breakdown:

```
5h window: 47.0% used  (allowed)
  Resets:  1h 26m until reset (13:00)
7d window: 14.0% used  (allowed)
  Resets:  Apr 19
Source:    server (fetched 11:33:22)
Budget:    81.5M weighted
Auto-cal:  2026-04-13T11:33
```

## Key features

### Weighted token math

Not all tokens cost the same against your rate limit:

- **Model multipliers**: Opus 5x, Sonnet 1x, Haiku 0.2x
- **Token weights**: input 1x, cache_create 1.25x, cache_read 0.1x, output 5x

An Opus session burns through your budget 5x faster than Sonnet — this tool reflects that.

### Cross-session aggregation

Scans all `.jsonl` transcript files within the 5h window, not just the current session. If you ran 3 sessions in the last hour, all of them count.

### Auto-calibration

Automatically adjusts `window_budget` using the formula:

```
window_budget = local_weighted_tokens / server_utilization
```

Triggers when drift exceeds 5%. Also auto-updates `window_reset_at` from server data.

### Manual calibration (optional)

If server data is unavailable or you want to override:

1. Go to [claude.ai/settings/usage](https://claude.ai/settings/usage)
2. Note the **usage %** and **time until reset**
3. In Claude Code: `/usage-calibrate 14 3h7m`

## CLI usage

The Stop hook script also works standalone:

```bash
# Show detailed status
python3 ~/.claude/hooks/token-tracker.py status

# Read cached server data as JSON
python3 ~/.claude/hooks/token-tracker.py refresh

# Manual calibration
python3 ~/.claude/hooks/token-tracker.py calibrate 14 3h7m
```

## What it doesn't track

Browser sessions (claude.ai), other machines, desktop app — but the server-side % includes all of these, so the window total is accurate regardless.

## Configuration

`~/.claude/token-tracker.json` (created automatically):

```json
{
  "window_hours": 5,
  "window_budget": 82674925,
  "manual_usage": [],
  "window_reset_at": "2026-04-16T01:00:00",
  "_auto_calibrated": "2026-04-16T00:33:14"
}
```

- `window_budget` — auto-calibrated from server data, or set manually via `/usage-calibrate`
- `window_reset_at` — auto-updated from server data
- `manual_usage` — optional entries for usage outside Claude Code CLI:
  ```json
  [{"ts": "2026-04-13T16:00:00", "weighted": 5000000, "note": "webUI session"}]
  ```

## Caveats

- The `rate_limits` field in Claude Code's statusLine stdin JSON is not a public API — it may change without notice. If unavailable, the Stop hook falls back to local estimates.
- Requires Python 3.8+ (stdlib only, no external dependencies).
- Requires Claude Code >= 2.1.80 for rate limit data in statusLine stdin.

## Structure

```
claude-tools/
├── statusline/statusline.py           # StatusLine script (persistent bar + cache writer)
├── hooks/token-tracker.py             # Stop hook + CLI (status, refresh, calibrate)
├── commands/usage-calibrate.md        # /usage-calibrate slash command
├── commands/usage-status.md           # /usage-status slash command
├── install.sh                         # Setup (symlinks to ~/.claude/)
├── COMPARISON.md                      # Competitive comparison with GitHub alternatives
└── README.md
```
