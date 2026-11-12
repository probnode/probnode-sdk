# ProbNode clients

Open-source clients for [ProbNode](https://probnode.com): Polymarket order books, trades, quotes,
OHLCV and feed gaps as hourly and market-day files (lp2, parquet, csv.gz), each with a sha256.

| Package | What it is |
|---|---|
| [`probnode-sdk`](packages/probnode) | Python client and the `probnode` command: datasets, files, download with sha256 checks, `sync`, `doctor`, timeseries, free samples, and the lp2 reader. `import probnode`. |
| [`probnode-mcp`](packages/probnode-mcp) | An MCP server that gives an AI agent the same API. |

```sh
pip install probnode-sdk        # not `pip install probnode`: that name is someone else's package
probnode login
probnode datasets
```

API reference: https://probnode.com/docs. Get a free key: https://probnode.com/login.

This repository is a mirror of the clients the ProbNode service is tested against; issues and pull
requests are welcome here.

MIT licensed.
