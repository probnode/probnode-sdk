"""Download one market's UTC day of trades and load it into pandas.

Shows: `Client.files(..., granularity="market_day", market=[slug])` to list the market-day file,
`Client.download_all()` to fetch it (each file checked against its sha256), and `probnode.read()`
to open it as a pyarrow Table.

Plan: Research or Pro (trades are paid data). Needs an API key: `probnode login` or
PROBNODE_API_KEY. Requires pandas: `pip install "probnode-sdk[pandas]"`.

    python examples/02_trades_to_pandas.py <market-slug> [YYYY-MM-DD]

The day defaults to yesterday (UTC). Find a slug with examples/01_catalog_and_coverage.py.
"""

import sys
from datetime import date, datetime, timedelta, timezone

import probnode

if len(sys.argv) < 2:
    sys.exit(__doc__)
market = sys.argv[1]
day = (
    date.fromisoformat(sys.argv[2])
    if len(sys.argv) > 2
    else (datetime.now(timezone.utc).date() - timedelta(days=1))
)
start, end = f"{day}T00:00:00Z", f"{day + timedelta(days=1)}T00:00:00Z"

with probnode.Client() as pn:
    files = pn.files("trades", "parquet", start, end, granularity="market_day", market=[market])
    if not files:
        sys.exit(f"no trades file for {market} on {day}")
    paths = list(pn.download_all(files, "data/"))

df = probnode.read(paths[0]).to_pandas()
print(f"{paths[0]}: {len(df):,} trades")
print(df.head())
print(df.groupby("token_id")["size"].sum())
