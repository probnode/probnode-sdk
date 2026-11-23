# probnode-sdk

Python client and command line for [ProbNode](https://probnode.com): Polymarket order books, trades
and feed gaps as hourly and market-day files (lp2, parquet, csv.gz), with a sha256 for every file.

```sh
pip install probnode-sdk        # not `pip install probnode`: that is someone else's package
probnode login
probnode datasets
probnode files books parquet 2026-11-08T12 2026-11-08T14
probnode sync books parquet 2026-11-08T12 2026-11-08T14 -o data/   # again later: only changes
probnode doctor data/                                              # re-check every sha256
```

```python
import probnode

pn = probnode.Client()  # PROBNODE_API_KEY, or the key `probnode login` saved
files = pn.files("books", "parquet", "2026-11-08T12:00:00Z", "2026-11-08T13:00:00Z")
paths = list(pn.download_all(files, "data/"))  # each checked against its sha256
table = probnode.read(paths[0])  # pyarrow.Table -> .to_pandas() / polars.from_arrow()

for batch in probnode.iter_lp2("hour.lp2"):  # native books, decoded in bounded memory
    ...
```

Units: prices x10,000 (5400 = 0.54), sizes x1,000,000 shares, timestamps in ms UTC. Signed links
last 15 minutes; the client signs again whenever it needs to. The import name is `probnode`; the
PyPI name is `probnode-sdk` because `probnode` is taken.

## Live API

Every book event and trade of the markets you subscribe, as it happens, with the probnode object
(analytics, risk against the normal for similar markets, security, stats):
`pip install "probnode-sdk[live]"`, then `probnode.live.Live`.

```python
import asyncio, time
from probnode.live import Live

async def main():
    market = f"btc-updown-15m-{int(time.time()) // 900 * 900}"
    async with Live("wss://live.probnode.com/v2/live", reconnect=True) as live:
        await live.subscribe([market], ["book+", "trades+"])
        async for msg in live:
            print(msg["type"])

asyncio.run(main())
```

Docs: [Live API](https://probnode.com/docs/live-api?lang=python) ·
[client reference](https://probnode.com/docs/live-api/client?lang=python) ·
[release notes](https://probnode.com/docs/live-api/release-notes) ·
[data API](https://probnode.com/docs).
