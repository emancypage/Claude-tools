Show current token usage status from the rate limit cache.

Run this command and show the user the output:

```bash
python3 -c "
import json, time
from datetime import datetime
from pathlib import Path
p = Path.home() / '.claude/rate-limit-cache.json'
if not p.exists():
    print('No rate limit data yet — statusLine must run at least once.')
else:
    d = json.loads(p.read_text())
    h5 = d.get('5h', {})
    h7 = d.get('7d', {})
    rem = h5['reset'] - time.time()
    rh, rm = int(rem // 3600), int((rem % 3600) // 60)
    print(f'5h window: {h5[\"utilization\"]*100:.1f}% used  ({h5[\"status\"]})')
    print(f'  Resets:  {rh}h {rm:02d}m until reset ({datetime.fromtimestamp(h5[\"reset\"]).strftime(\"%H:%M\")})')
    print(f'7d window: {h7[\"utilization\"]*100:.1f}% used  ({h7[\"status\"]})')
    print(f'  Resets:  {datetime.fromtimestamp(h7[\"reset\"]).strftime(\"%b %d\")}')
    print(f'Source:    cache (fetched {datetime.fromtimestamp(d[\"ts\"]).strftime(\"%H:%M:%S\")})')
"
```

After running, briefly summarize the usage status to the user.
