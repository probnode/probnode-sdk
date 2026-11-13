<p align="center">
  <a href="https://probnode.com"><img src="assets/probnode-logo-round.svg" alt="ProbNode" width="96" height="96"></a>
</p>

<h1 align="center">ProbNode clients</h1>

<p align="center">
  <a href="https://pypi.org/project/probnode-sdk/"><img src="https://img.shields.io/pypi/v/probnode-sdk?label=probnode-sdk" alt="probnode-sdk on PyPI"></a>
  <a href="https://pypi.org/project/probnode-mcp/"><img src="https://img.shields.io/pypi/v/probnode-mcp?label=probnode-mcp" alt="probnode-mcp on PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <a href="https://github.com/probnode/probnode-sdk/actions/workflows/ci.yml"><img src="https://github.com/probnode/probnode-sdk/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license"></a>
</p>

The official Python client, command line and MCP server for [ProbNode](https://probnode.com):
Polymarket order books, trades and a published record of what was captured, delivered as parquet
and csv files with a sha256 for every file.

| Package | Install | What it is |
|---|---|---|
| [`probnode-sdk`](packages/probnode) | `pip install probnode-sdk` | The Python client (`import probnode`) and the `probnode` command. |
| [`probnode-mcp`](packages/probnode-mcp) | `pip install probnode-mcp` | An MCP server that gives an AI agent the same API. |

## Install

```sh
pip install probnode-sdk              # the PyPI name; the import name is `probnode`
pip install "probnode-sdk[pandas]"    # with pandas; `[polars]` for polars
```

Python 3.10 or newer. `pip install probnode` installs an unrelated package: the name was taken.

## Quickstart

```python
import probnode

pn = probnode.Client()  # key from PROBNODE_API_KEY, or the one `probnode login` saved
files = pn.files("trades", "parquet", "2026-11-12T00:00:00Z", "2026-11-13T00:00:00Z",
                 granularity="market_day", market=["<market-slug>"])
paths = list(pn.download_all(files, "data/"))  # each file checked against its sha256
df = probnode.read(paths[0]).to_pandas()       # a pyarrow Table; polars.from_arrow() works too
```

The catalog and the coverage ledger are public, no key needed:

```python
pn = probnode.Client()
market = pn.markets(q="bitcoin", limit=1)[0]
print(market["slug"], [t["outcome"] for t in market["tokens"]])
print(pn.coverage(market["tokens"][0]["token_id"]))  # recorded ms, gaps and uptime per hour
```

One market's UTC day of the full order book, every level change and every trade:

```python
path = pn.export_book("<market-slug>", "2026-11-12", "data/")  # parquet; format="csv" for csv.gz
```

The first request for a market and day builds the file, later ones find it built; the day must
have ended (UTC).

Get a key at [probnode.com/login](https://probnode.com/login), or mint one with
`Client().login(email, password)`. Errors raise `probnode.ProbNodeError`, carrying the HTTP status
and the API's own message.

More in [`examples/`](examples):

| Script | Shows | Plan |
|---|---|---|
| [`01_catalog_and_coverage.py`](examples/01_catalog_and_coverage.py) | search the catalog, a market's coverage per token | none, no key |
| [`02_trades_to_pandas.py`](examples/02_trades_to_pandas.py) | one market's day of trades into pandas | Research or Pro |
| [`03_gaps_and_recorded_share.py`](examples/03_gaps_and_recorded_share.py) | a market's recorded share, the day's gap journal by reason | Free |
| [`04_query_parquet.py`](examples/04_query_parquet.py) | DuckDB and polars over the downloaded parquet | as the files |

## Command line

```sh
probnode login                                                    # email + password, key saved
probnode datasets                                                 # datasets, formats, hours held
probnode files trades parquet 2026-11-12T06 2026-11-12T12         # what a selection holds
probnode download trades parquet 2026-11-12T06 2026-11-12T12 -o data/
probnode sync trades parquet 2026-11-12T06 2026-11-12T12 -o data/ # again later: only what changed
probnode doctor data/                                             # re-check every sha256
probnode export <market-slug> 2026-11-12 -o data/                 # one market-day of the full book
```

Times are UTC hours; the end is exclusive. `--granularity market_day` and `--market <slug>` select
one file per market and UTC day. Exit codes: 0 done, 1 a check failed, 2 the API refused.
`probnode --help` lists everything.

## MCP

```sh
pip install probnode-mcp
```

```json
{"mcpServers": {"probnode": {"command": "probnode-mcp", "env": {"PROBNODE_API_KEY": "pmd_..."}}}}
```

Tools: `datasets`, `search_markets`, `coverage`, `list_files`, `sign_files`, `timeseries`,
`samples`, and `export_book` (a signed link to one market's day of the full book). Every call goes through the same API, plan and limits as the
SDK. Bulk data is handed over as signed URLs rather than through the model's context; `timeseries`
returns at most 500 rows.

## Data

Polymarket, every market, no volume gate. Schemas by level:

| Level | Schema | What it is | Delivered as | Plan |
|---|---|---|---|---|
| L2 - depth | `book_full` (book-max) | every change of every price level of every outcome token, and the trades, in arrival order | one market's UTC day as parquet or csv | Research, Pro |
| L1 - trades | `trades` | every trade: token, price, size, side, both timestamps, transaction hash | one market's UTC day as parquet or csv; hourly parquet as recorded | Research, Pro |
| L0 - definitions | `markets` | the map from outcome token to market | hourly parquet | Free |
| Reference | `gaps` | the recorder's feed-gap journal: every interruption, with its reason | hourly parquet | Free |
| Reference | coverage | per outcome token and UTC hour: milliseconds recorded, gaps, uptime | JSON from the API | public, no key |

In the market-day files prices are probabilities and sizes are outcome-token shares, as decimals;
hourly files keep the recorder's integer scales. Timestamps are UTC, and book and trade rows carry
two clocks: when ProbNode received the message and the venue's own. ProbNode stores the book in
its own compact format, Probe (`.probe`); what you download is parquet or csv. Columns, units and
every endpoint: [probnode.com/docs](https://probnode.com/docs).

## Links

- Documentation: https://probnode.com/docs
- API reference (OpenAPI 3.1): https://probnode.com/openapi.json
- Plans and pricing: https://probnode.com/pricing
- Help centre: https://probnode.com/help
- Contact: hello@probnode.com
- Security reports: see [SECURITY.md](SECURITY.md)

Bugs and feature requests for the clients: [open an issue](https://github.com/probnode/probnode-sdk/issues).
Questions about your account, plan or the data itself: hello@probnode.com.

## License

MIT, see [LICENSE](LICENSE). The license covers the code in this repository; the data you download
is licensed under the terms of your ProbNode plan.
