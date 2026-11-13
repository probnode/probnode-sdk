"""Find markets in the catalog and print how completely each outcome token was recorded.

Shows: `Client.datasets()`, `Client.markets(q=...)` and `Client.coverage(token_id)` - the dataset
list, the market catalog and the coverage ledger (recorded milliseconds, gaps and uptime per token
and UTC hour).

Plan: none. These calls are public and work without an API key.

    python examples/01_catalog_and_coverage.py bitcoin
"""

import sys

import probnode

query = sys.argv[1] if len(sys.argv) > 1 else "bitcoin"

with probnode.Client() as pn:
    print("datasets:")
    for d in pn.datasets():
        if d.get("last_hour"):
            print(f"  {d['code']:<12} {d['tier']:<5} {d['first_hour']} .. {d['last_hour']}")

    markets = pn.markets(q=query, limit=3)
    for m in markets:
        print(f"\n{m['slug']}  ({m['start_ts']} .. {m['end_ts']})")
        for token in m["tokens"]:
            hours = pn.coverage(token["token_id"])
            recorded = sum(h["recorded_ms"] for h in hours)
            gaps = sum(h["gap_count"] for h in hours)
            print(
                f"  {token['outcome']:<4} {len(hours)} hours, "
                f"{recorded / 3_600_000:.2f} h recorded, {gaps} gaps"
            )
