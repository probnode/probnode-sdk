"""How much of a market's day was recorded, and what the feed-gap journal says about that day.

Shows: `Client.coverage(token_id, start, end)` - the coverage ledger, which is the gap journal
summed per token and UTC hour - turned into a recorded share per outcome token; then the hourly
`gaps` files for the same day, downloaded and read, with their rows counted by reason.

Plan: Free. The coverage ledger needs no key; downloading the gaps files needs a key
(`probnode login` or PROBNODE_API_KEY), and the Free plan signs 50 files a day.

    python examples/03_gaps_and_recorded_share.py <market-slug> [YYYY-MM-DD]

The day defaults to yesterday (UTC).
"""

import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import probnode

HOUR_MS = 3_600_000

if len(sys.argv) < 2:
    sys.exit(__doc__)
slug = sys.argv[1]
day = (
    date.fromisoformat(sys.argv[2])
    if len(sys.argv) > 2
    else (datetime.now(timezone.utc).date() - timedelta(days=1))
)
start, end = f"{day}T00:00:00Z", f"{day + timedelta(days=1)}T00:00:00Z"

with probnode.Client() as pn:
    found = [m for m in pn.markets(q=slug, limit=100) if m["slug"] == slug]
    if not found:
        sys.exit(f"no market {slug!r} in the catalog")

    print(f"{slug}, {day}:")
    for token in found[0]["tokens"]:
        hours = pn.coverage(token["token_id"], start, end)
        if not hours:
            print(f"  {token['outcome']:<4} not recorded that day")
            continue
        recorded = sum(h["recorded_ms"] for h in hours)
        share = recorded / (len(hours) * HOUR_MS)
        gaps = sum(h["gap_count"] for h in hours)
        print(f"  {token['outcome']:<4} {share:.4%} of {len(hours)} hours recorded, {gaps} gaps")

    # The journal itself: one file per hour, for every market the recorder followed.
    files = pn.files("gaps", "parquet", start, end)
    paths = list(pn.download_all(files, "data/"))

reasons: Counter[str] = Counter()
for path in paths:
    table = probnode.read(path)
    if "reason" in table.column_names:
        reasons.update(table.column("reason").to_pylist())
print(f"\ngap journal, {len(paths)} files: {sum(reasons.values())} rows")
for reason, n in reasons.most_common():
    print(f"  {reason:<24} {n}")
