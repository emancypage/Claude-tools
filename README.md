# claude-tools

Shared tools for working with Claude Code.

## Token Usage Tracker

Track token usage against the 5h and 7d rate limit windows. Shows status after every Claude response with **real server-side utilization data** from API response headers — no manual calibration needed.

### Installation

```bash
git clone <repo-url> ~/claude-tools
cd ~/claude-tools
./install.sh
```

`install.sh` creates symlinks to `~/.claude/`:
- `hooks/token-tracker.py` — Stop hook (usage info after every response)
- `commands/usage-calibrate.md` — `/usage-calibrate` slash command
- `commands/usage-status.md` — `/usage-status` slash command

You also need to add the Stop hook to your Claude Code settings. In a Claude Code conversation, ask:

> "Add a Stop hook that runs `python3 ~/.claude/hooks/token-tracker.py`"

### How it works

After every Claude response, the Stop hook:

1. Parses the current session transcript for weighted token usage
2. Checks `~/.claude/rate-limit-cache.json` for server-side utilization data
3. If the cache is stale (>5 min), makes a minimal API call (~1s, ~0 cost) to fetch fresh `anthropic-ratelimit-unified-5h-utilization` and `7d-utilization` headers
4. Auto-updates `window_reset_at` and `window_budget` in the config
5. Displays a compact status line

The API probe uses haiku with `max_tokens=1` through the OAuth token stored by Claude Code. Cost per probe is negligible (<0.001% of the 5h budget).

### What you get

The Stop hook shows a compact status after every response:

```
[usage] ctx: 125K (cache: 87%) | session: 12.8% | 1h25m left: 47.0%S ████████████████████░░░░░░░░░░
```

- `ctx` — current context window size (input tokens in last API call)
- `cache` — % of context served from prompt cache
- `session` — this session's share of the 5h budget (local estimate)
- `47.0%S` — total 5h window usage from server (`S` = server, `L` = local fallback)
- progress bar — visual representation of 5h window usage

Use `/usage-status` for a detailed view:

```
5h window: 47.0% used  (allowed)
  Resets:  1h 26m until reset (13:00)
7d window: 14.0% used  (allowed)
  Resets:  Apr 19
Overage:   rejected (org_level_disabled)
Source:    server (fetched 11:33:22)
Budget:    81.5M weighted
Auto-cal:  2026-04-13T11:33
```

### Auto-calibration

The tracker automatically calibrates itself using server-side data:

- **`window_reset_at`** — set from the `5h-reset` API header (exact server time)
- **`window_budget`** — computed as `local_weighted_tokens / server_utilization`

This replaces the old manual workflow of checking claude.ai/settings/usage. Calibration happens silently every time the cache refreshes.

### Manual calibration (optional)

If you don't have an active OAuth session or want to override, manual calibration still works:

1. Go to [claude.ai/settings/usage](https://claude.ai/settings/usage)
2. Note the **usage %** and **time until reset**
3. In Claude Code: `/usage-calibrate 14 3h7m`

### CLI usage

The hook script also works standalone:

```bash
# Show status (fetches fresh server data)
python3 ~/.claude/hooks/token-tracker.py status

# Force-refresh server data and print JSON
python3 ~/.claude/hooks/token-tracker.py refresh

# Manual calibration
python3 ~/.claude/hooks/token-tracker.py calibrate 14 3h7m
```

### What it tracks

- **Server-side**: real utilization % for 5h and 7d windows, reset times, overage status
- **Locally**: per-session token breakdown, context window size, cache hit rate
- Token weights: input x1, cache_create x1.25, cache_read x0.1, output x5
- Model multipliers: Opus x5, Sonnet x1, Haiku x0.2

### What it doesn't track

- Browser sessions (claude.ai), other machines, desktop app — but the server-side % includes all of these, so the window total is accurate regardless

### Configuration

`~/.claude/token-tracker.json` (created automatically):

```json
{
  "window_hours": 5,
  "window_budget": 81537390,
  "manual_usage": [],
  "window_reset_at": "2026-04-13T13:00:00",
  "_auto_calibrated": "2026-04-13T11:33:14"
}
```

- `window_budget` — auto-calibrated from server data, or set by `/usage-calibrate`
- `window_reset_at` — auto-updated from server, or set by `/usage-calibrate`
- `manual_usage` — optional manual entries for edge cases:
  ```json
  [{"ts": "2026-04-13T16:00:00", "weighted": 5000000, "note": "webUI"}]
  ```

### Caveats

- The OAuth token (`~/.claude/.credentials.json`) and the `utilization` response headers are internal to Claude Code — not a public API. They may change without notice. If they break, the hook falls back to local estimates silently.
- The API probe adds ~1s latency once every 5 minutes. The rest of the time it reads from cache.
- Requires Python 3.8+ (uses `urllib.request`, no external dependencies).

## Structure

```
claude-tools/
├── hooks/token-tracker.py             # Stop hook + CLI (status, refresh, calibrate)
├── commands/usage-calibrate.md        # /usage-calibrate slash command
├── commands/usage-status.md           # /usage-status slash command
├── install.sh                         # Setup (symlinks to ~/.claude/)
└── README.md
```
