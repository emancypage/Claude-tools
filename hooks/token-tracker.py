#!/usr/bin/env python3
"""Claude Code Stop hook: shows token usage as % of 5h rate limit after every response.

Uses real server-side utilization data from API response headers
(anthropic-ratelimit-unified-5h-utilization, 7d-utilization) cached locally.
Falls back to local weighted token estimates when server data is unavailable.
"""

import json
import sys
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta

CONFIG_PATH = Path.home() / ".claude" / "token-tracker.json"
CACHE_PATH = Path.home() / ".claude" / "token-tracker-cache.json"
RATELIMIT_CACHE_PATH = Path.home() / ".claude" / "rate-limit-cache.json"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
PROJECTS_DIR = Path.home() / ".claude" / "projects"

DEFAULT_WINDOW_HOURS = 5
DEFAULT_WINDOW_BUDGET = 40_000_000
RATELIMIT_CACHE_TTL = 300  # refresh server data every 5 minutes

# Cost weights (proportional to API pricing ratios, consistent across models)
WEIGHT_INPUT = 1.0
WEIGHT_CACHE_CREATE = 1.25
WEIGHT_CACHE_READ = 0.1
WEIGHT_OUTPUT = 5.0

# Model multipliers (relative to Sonnet = 1x)
MODEL_MULTIPLIERS = {
    "claude-opus-4-6": 5.0,
    "claude-sonnet-4-6": 1.0,
    "claude-haiku-4-5-20251001": 0.2,
}


def get_model_multiplier(model_id):
    if not model_id:
        return 1.0
    for key, mult in MODEL_MULTIPLIERS.items():
        if key in model_id:
            return mult
    if "opus" in model_id:
        return 5.0
    if "haiku" in model_id:
        return 0.2
    return 1.0


def weighted_usage(usage, model_id):
    mult = get_model_multiplier(model_id)
    return mult * (
        usage.get("input_tokens", 0) * WEIGHT_INPUT
        + usage.get("cache_creation_input_tokens", 0) * WEIGHT_CACHE_CREATE
        + usage.get("cache_read_input_tokens", 0) * WEIGHT_CACHE_READ
        + usage.get("output_tokens", 0) * WEIGHT_OUTPUT
    )


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(int(n))


def parse_transcript(filepath):
    total = 0.0
    last_input_tokens = (0, 0, 0)  # (total, cache_read, cache_create)
    try:
        with open(filepath) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("type") == "assistant" and "message" in data:
                        msg = data["message"]
                        usage = msg.get("usage", {})
                        model_id = msg.get("model", "")
                        total += weighted_usage(usage, model_id)
                        # Track last message's input tokens = current context size
                        raw = usage.get("input_tokens", 0)
                        cache_read = usage.get("cache_read_input_tokens", 0)
                        cache_create = usage.get("cache_creation_input_tokens", 0)
                        it = raw + cache_read + cache_create
                        if it > 0:
                            last_input_tokens = (it, cache_read, cache_create)
                except (json.JSONDecodeError, KeyError):
                    pass
    except OSError:
        pass
    return total, last_input_tokens


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}
    return {
        "window_hours": cfg.get("window_hours", DEFAULT_WINDOW_HOURS),
        "window_budget": cfg.get("window_budget", DEFAULT_WINDOW_BUDGET),
        "manual_usage": cfg.get("manual_usage", []),
        "window_reset_at": cfg.get("window_reset_at"),
    }


def get_window_cutoff(cfg):
    """Return the cutoff timestamp for the current usage window."""
    now = time.time()
    reset_at = cfg.get("window_reset_at")
    if reset_at:
        try:
            reset_ts = datetime.fromisoformat(reset_at).timestamp()
            if reset_ts > now:
                return reset_ts - cfg["window_hours"] * 3600
        except (ValueError, TypeError):
            pass
    return now - cfg["window_hours"] * 3600


def load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache):
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass


def find_recent_transcripts(cutoff_ts, current_transcript):
    current_path = str(Path(current_transcript).resolve()) if current_transcript else ""
    results = []
    try:
        for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
            path_str = str(jsonl.resolve())
            if path_str == current_path:
                continue  # handle current session separately
            try:
                mtime = jsonl.stat().st_mtime
                if mtime >= cutoff_ts:
                    results.append((path_str, mtime))
            except OSError:
                pass
    except OSError:
        pass
    return results


def progress_bar(pct, width=20):
    filled = int(round(pct / 100 * width))
    filled = max(0, min(width, filled))
    return "\u2588" * filled + "\u2591" * (width - filled)


# --- Server-side rate limit data ---


def _get_access_token():
    """Read OAuth access token from credentials file."""
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def fetch_server_ratelimit():
    """Make a minimal API call and return rate limit headers.

    Uses haiku with max_tokens=1 to minimize cost (~$0.001).
    Returns dict with 5h/7d utilization data, or None on failure.
    """
    token = _get_access_token()
    if not token:
        return None

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "x"}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "X-Api-Key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            headers = resp.headers
            result = {"ts": time.time()}

            for key, prefix in [("5h", "5h"), ("7d", "7d")]:
                util = headers.get(f"anthropic-ratelimit-unified-{prefix}-utilization")
                reset = headers.get(f"anthropic-ratelimit-unified-{prefix}-reset")
                status = headers.get(f"anthropic-ratelimit-unified-{prefix}-status")
                if util is not None and reset is not None:
                    result[key] = {
                        "utilization": float(util),
                        "reset": int(reset),
                        "status": status or "unknown",
                    }

            result["representative_claim"] = headers.get(
                "anthropic-ratelimit-unified-representative-claim", ""
            )
            result["overage_status"] = headers.get(
                "anthropic-ratelimit-unified-overage-status", ""
            )
            result["overage_reason"] = headers.get(
                "anthropic-ratelimit-unified-overage-disabled-reason", ""
            )
            result["fallback_pct"] = headers.get(
                "anthropic-ratelimit-unified-fallback-percentage", ""
            )
            result["status"] = headers.get(
                "anthropic-ratelimit-unified-status", ""
            )
            return result
    except (urllib.error.URLError, OSError, ValueError):
        return None


def load_ratelimit_cache():
    """Load cached rate limit data. Returns dict or None."""
    try:
        with open(RATELIMIT_CACHE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_ratelimit_cache(data):
    try:
        with open(RATELIMIT_CACHE_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def get_server_ratelimit(force_refresh=False):
    """Get rate limit data, refreshing if cache is stale.

    Returns cached data if fresh (< RATELIMIT_CACHE_TTL seconds old),
    otherwise fetches from API. Returns None if unavailable.
    """
    cached = load_ratelimit_cache()
    if not force_refresh and cached:
        age = time.time() - cached.get("ts", 0)
        if age < RATELIMIT_CACHE_TTL:
            return cached

    fresh = fetch_server_ratelimit()
    if fresh:
        save_ratelimit_cache(fresh)
        # Also auto-update window_reset_at in config
        _auto_update_config(fresh)
        return fresh

    return cached  # stale cache is better than nothing


def _auto_update_config(server_data):
    """Auto-update token-tracker.json with server-side data."""
    h5 = server_data.get("5h", {})
    if not h5:
        return

    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}

    changed = False

    # Auto-update window_reset_at from server
    server_reset = h5.get("reset")
    if server_reset:
        new_reset = datetime.fromtimestamp(server_reset).isoformat()
        if cfg.get("window_reset_at") != new_reset:
            cfg["window_reset_at"] = new_reset
            changed = True

    # Auto-calibrate budget if we have utilization data
    utilization = h5.get("utilization", 0)
    if utilization > 0.02:  # only calibrate if there's meaningful usage
        # Compute total local weighted in the server's window
        window_start = server_reset - cfg.get("window_hours", DEFAULT_WINDOW_HOURS) * 3600
        local_total = _sum_local_weighted(window_start)
        if local_total > 0:
            new_budget = int(local_total / utilization)
            old_budget = cfg.get("window_budget", DEFAULT_WINDOW_BUDGET)
            # Only update if it changed significantly (>5%) to avoid jitter
            if abs(new_budget - old_budget) / max(old_budget, 1) > 0.05:
                cfg["window_budget"] = new_budget
                cfg["_auto_calibrated"] = datetime.now().isoformat()
                changed = True

    if changed:
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except OSError:
            pass


def _sum_local_weighted(cutoff_ts):
    """Sum weighted tokens from all transcripts after cutoff."""
    total = 0.0
    try:
        for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
            try:
                if jsonl.stat().st_mtime >= cutoff_ts:
                    w, _ = parse_transcript(str(jsonl))
                    total += w
            except OSError:
                pass
    except OSError:
        pass
    return total


def get_all_local_weighted(cfg):
    """Sum weighted usage from all local transcripts in the window."""
    cutoff_ts = get_window_cutoff(cfg)
    return _sum_local_weighted(cutoff_ts)


# --- CLI commands ---


def parse_duration(s):
    """Parse duration strings like '3h7m', '3h', '45m', '2h30m'."""
    import re
    m = re.match(r'^(\d+)h\s*(\d+)m(?:in)?$', s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60
    m = re.match(r'^(\d+)h$', s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 3600
    m = re.match(r'^(\d+)m(?:in)?$', s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 60
    return None


def calibrate(real_pct, time_remaining=None):
    """Calibrate budget so local weighted usage = real_pct% of budget."""
    try:
        with open(CONFIG_PATH) as f:
            raw_cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw_cfg = {}

    # Calibrate timer first (affects which transcripts are in window)
    if time_remaining is not None:
        secs = parse_duration(time_remaining)
        if secs is None:
            print(f"Error: can't parse '{time_remaining}'. Use e.g. 3h7m, 2h, 45m")
            return
        reset_at = datetime.fromtimestamp(time.time() + secs).isoformat()
        raw_cfg["window_reset_at"] = reset_at
        with open(CONFIG_PATH, "w") as f:
            json.dump(raw_cfg, f, indent=2)

    cfg = load_config()
    local_weighted = get_all_local_weighted(cfg)

    if real_pct <= 0:
        print("Error: usage % must be > 0")
        return
    if local_weighted <= 0:
        print("Error: no local usage found in window")
        return

    new_budget = int(local_weighted / (real_pct / 100))

    old_budget = raw_cfg.get("window_budget", DEFAULT_WINDOW_BUDGET)
    raw_cfg["window_budget"] = new_budget
    raw_cfg["_last_calibration"] = datetime.now().isoformat()

    with open(CONFIG_PATH, "w") as f:
        json.dump(raw_cfg, f, indent=2)

    local_fmt = fmt_tokens(local_weighted)
    print(f"Calibrated: {real_pct}% real usage = {local_fmt} weighted")
    print(f"Budget: {fmt_tokens(old_budget)} -> {fmt_tokens(new_budget)}")
    if time_remaining is not None:
        print(f"Reset in: {time_remaining}")


def status():
    """Show current usage status with server-side data."""
    cfg = load_config()
    server = get_server_ratelimit(force_refresh=True)

    if server and "5h" in server:
        h5 = server["5h"]
        h5_pct = h5["utilization"] * 100
        h5_reset = h5["reset"]
        remaining = h5_reset - time.time()
        if remaining > 0:
            rh = int(remaining // 3600)
            rm = int((remaining % 3600) // 60)
            time_line = f"{rh}h {rm:02d}m until reset"
        else:
            time_line = "window expired"

        print(f"5h window: {h5_pct:.1f}% used  ({h5['status']})")
        print(f"  Resets:  {time_line} ({datetime.fromtimestamp(h5_reset).strftime('%H:%M')})")

        if "7d" in server:
            h7 = server["7d"]
            h7_pct = h7["utilization"] * 100
            h7_reset = datetime.fromtimestamp(h7["reset"]).strftime("%b %d")
            print(f"7d window: {h7_pct:.1f}% used  ({h7['status']})")
            print(f"  Resets:  {h7_reset}")

        if server.get("overage_status"):
            reason = server.get("overage_reason", "")
            print(f"Overage:   {server['overage_status']}{f' ({reason})' if reason else ''}")

        print(f"Source:    server (fetched {datetime.fromtimestamp(server['ts']).strftime('%H:%M:%S')})")
    else:
        # Fallback to local estimates
        local_weighted = get_all_local_weighted(cfg)
        budget = cfg["window_budget"]
        pct = (local_weighted / budget * 100) if budget > 0 else 0

        reset_at = cfg.get("window_reset_at")
        time_line = f"{cfg['window_hours']}h rolling"
        if reset_at:
            try:
                reset_ts = datetime.fromisoformat(reset_at).timestamp()
                remaining = reset_ts - time.time()
                if remaining > 0:
                    rh = int(remaining // 3600)
                    rm = int((remaining % 3600) // 60)
                    time_line = f"{rh}h {rm:02d}m until reset"
                else:
                    time_line = f"{cfg['window_hours']}h rolling (reset passed)"
            except (ValueError, TypeError):
                pass

        print(f"Window:    {time_line}")
        print(f"Budget:    {fmt_tokens(budget)} weighted tokens")
        print(f"Used:      {fmt_tokens(local_weighted)} ({pct:.1f}%)")
        print(f"Remaining: ~{fmt_tokens(max(0, budget - local_weighted))} ({max(0, 100 - pct):.1f}%)")
        print(f"Source:    local estimate (server unavailable)")

    budget = cfg["window_budget"]
    print(f"Budget:    {fmt_tokens(budget)} weighted")
    if cfg.get("_auto_calibrated"):
        print(f"Auto-cal:  {cfg['_auto_calibrated'][:16]}")
    elif cfg.get("_last_calibration"):
        print(f"Manual-cal: {cfg['_last_calibration'][:16]}")


# --- Main hook ---


def main():
    # CLI mode
    if len(sys.argv) >= 2 and sys.argv[1] == "status":
        status()
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "calibrate":
        try:
            pct = float(sys.argv[2])
        except ValueError:
            print("Usage: token-tracker.py calibrate <percent> [time-remaining]")
            return
        time_remaining = sys.argv[3] if len(sys.argv) >= 4 else None
        calibrate(pct, time_remaining)
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "refresh":
        data = fetch_server_ratelimit()
        if data:
            save_ratelimit_cache(data)
            _auto_update_config(data)
            print(json.dumps(data, indent=2))
        else:
            print("Failed to fetch server data", file=sys.stderr)
            sys.exit(1)
        return

    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    transcript_path = input_data.get("transcript_path", "")
    if not transcript_path:
        return

    cfg = load_config()
    cache = load_cache()

    # Current session: always parse fully
    session_weighted, ctx_tokens = parse_transcript(transcript_path)

    # Other recent sessions: use cache where possible
    cutoff_ts = get_window_cutoff(cfg)
    recent_files = find_recent_transcripts(cutoff_ts, transcript_path)
    other_weighted = 0.0
    new_cache = {}

    for fpath, mtime in recent_files:
        cached = cache.get(fpath)
        if cached and cached.get("mtime") == mtime:
            w = cached["weighted"]
        else:
            w, _ = parse_transcript(fpath)
        new_cache[fpath] = {"mtime": mtime, "weighted": w}
        other_weighted += w

    save_cache(new_cache)

    # Add manual usage entries that fall within the window
    manual_weighted = 0.0
    for entry in cfg.get("manual_usage", []):
        try:
            entry_ts = datetime.fromisoformat(entry["ts"]).timestamp()
            if entry_ts >= cutoff_ts:
                manual_weighted += entry.get("weighted", 0)
        except (KeyError, ValueError):
            pass

    window_weighted = session_weighted + other_weighted + manual_weighted
    budget = cfg["window_budget"]

    session_pct = (session_weighted / budget * 100) if budget > 0 else 0

    # Get server data (cached, refreshed if stale)
    server = get_server_ratelimit(force_refresh=False)

    # Prefer server-side percentage, fall back to local estimate
    if server and "5h" in server:
        window_pct = server["5h"]["utilization"] * 100
        pct_source = "S"  # Server
    else:
        window_pct = (window_weighted / budget * 100) if budget > 0 else 0
        pct_source = "L"  # Local estimate

    bar = progress_bar(window_pct)
    window_h = cfg["window_hours"]

    ctx_total, ctx_cache_read, ctx_cache_create = ctx_tokens
    ctx = fmt_tokens(ctx_total)
    cache_pct = int((ctx_cache_read + ctx_cache_create) / ctx_total * 100) if ctx_total > 0 else 0

    # Time remaining from server or local
    if server and "5h" in server:
        remaining = server["5h"]["reset"] - time.time()
        if remaining > 0:
            rh = int(remaining // 3600)
            rm = int((remaining % 3600) // 60)
            time_info = f"{rh}h{rm:02d}m left"
        else:
            time_info = "reset"
    else:
        reset_at = cfg.get("window_reset_at")
        time_info = f"{window_h}h"
        if reset_at:
            try:
                reset_ts = datetime.fromisoformat(reset_at).timestamp()
                remaining = reset_ts - time.time()
                if remaining > 0:
                    rh = int(remaining // 3600)
                    rm = int((remaining % 3600) // 60)
                    time_info = f"{rh}h{rm:02d}m left"
            except (ValueError, TypeError):
                pass

    msg = f"[usage] ctx: {ctx} (cache: {cache_pct}%) | session: {session_pct:.1f}% | {time_info}: {window_pct:.1f}%{pct_source} {bar}"

    print(json.dumps({"systemMessage": msg}))


if __name__ == "__main__":
    main()
