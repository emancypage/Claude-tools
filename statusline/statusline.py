#!/usr/bin/env python3
"""Claude Code statusLine script: persistent status bar + rate limit cache writer.

Reads the JSON payload that Claude Code pipes to statusLine commands via stdin,
writes rate_limits to the shared cache file (so the Stop hook can read it
without making an API call), and prints a compact status bar.

Requires Claude Code >= 2.1.80 (rate_limits field in statusLine stdin).
"""

import json
import sys
import time
from pathlib import Path

RATELIMIT_CACHE_PATH = Path.home() / ".claude" / "rate-limit-cache.json"


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(int(n))


def progress_bar(pct, width=20):
    filled = int(round(pct / 100 * width))
    filled = max(0, min(width, filled))
    return "\u2588" * filled + "\u2591" * (width - filled)


def color(text, code):
    return f"\033[{code}m{text}\033[0m"


def pct_color(value, text=None):
    """Color a percentage value: green < 50, yellow < 70, orange < 90, red >= 90."""
    s = text if text is not None else f"{value:.0f}%"
    if value >= 90:
        return color(s, "1;31")  # bold red
    if value >= 70:
        return color(s, "31")   # red
    if value >= 50:
        return color(s, "33")   # yellow
    return color(s, "32")       # green


def write_ratelimit_cache(rate_limits):
    """Convert statusLine rate_limits to the cache format the Stop hook expects."""
    cache = {"ts": time.time()}

    fh = rate_limits.get("five_hour", {})
    if fh:
        cache["5h"] = {
            "utilization": fh.get("used_percentage", 0) / 100,
            "reset": fh.get("resets_at", 0),
            "status": "allowed",
        }

    sd = rate_limits.get("seven_day", {})
    if sd:
        cache["7d"] = {
            "utilization": sd.get("used_percentage", 0) / 100,
            "reset": sd.get("resets_at", 0),
            "status": "allowed",
        }

    try:
        with open(RATELIMIT_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    # --- Write rate limits to cache (the main fix) ---
    rate_limits = data.get("rate_limits", {})
    if rate_limits:
        write_ratelimit_cache(rate_limits)

    # --- Build status bar display ---
    parts = []

    # Model
    model = data.get("model", {})
    model_name = model.get("display_name", "?")
    parts.append(model_name)

    # Context window
    ctx = data.get("context_window", {})
    current = ctx.get("current_usage", {})
    input_t = current.get("input_tokens", 0)
    cache_read = current.get("cache_read_input_tokens", 0)
    cache_create = current.get("cache_creation_input_tokens", 0)
    ctx_total = input_t + cache_read + cache_create

    if ctx_total > 0:
        cache_pct = int((cache_read + cache_create) / ctx_total * 100)
        if ctx_total > 180_000:
            ctx_str = color(fmt_tokens(ctx_total), "1;31")
        elif ctx_total > 120_000:
            ctx_str = color(fmt_tokens(ctx_total), "31")
        elif ctx_total > 80_000:
            ctx_str = color(fmt_tokens(ctx_total), "33")
        else:
            ctx_str = color(fmt_tokens(ctx_total), "32")
        parts.append(f"ctx:{ctx_str}({cache_pct}%)")

    # 5h rate limit
    fh = rate_limits.get("five_hour", {})
    if fh:
        pct = fh.get("used_percentage", 0)
        resets_at = fh.get("resets_at", 0)
        remaining = resets_at - time.time()
        if remaining > 0:
            rh = int(remaining // 3600)
            rm = int((remaining % 3600) // 60)
            time_str = f"{rh}h{rm:02d}m"
        else:
            time_str = "reset"
        bar = progress_bar(pct, 15)
        parts.append(f"5h:{pct_color(pct)} {time_str} {bar}")

    # 7d rate limit (only show if > 50%)
    sd = rate_limits.get("seven_day", {})
    if sd:
        pct_7d = sd.get("used_percentage", 0)
        if pct_7d > 50:
            parts.append(f"7d:{pct_color(pct_7d)}")

    # Cost
    cost = data.get("cost", {})
    cost_usd = cost.get("total_cost_usd", 0)
    if cost_usd > 0.01:
        parts.append(f"${cost_usd:.2f}")

    print(" | ".join(parts))


if __name__ == "__main__":
    main()
