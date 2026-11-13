<p align="center">
  <a href="https://probnode.com"><img src="https://raw.githubusercontent.com/probnode/probnode-sdk/main/assets/probnode-logo.png" alt="ProbNode" width="96" height="96"></a>
</p>

<h1 align="center">probnode-sdk</h1>

<p align="center"><b>The official Python client, command line and MCP server for ProbNode: Polymarket order books, trades and coverage.</b></p>

<p align="center">
  <a href="https://github.com/probnode/probnode-sdk/actions/workflows/ci.yml"><img src="https://github.com/probnode/probnode-sdk/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://pypi.org/project/probnode-sdk/"><img src="https://img.shields.io/pypi/v/probnode-sdk.svg?label=probnode-sdk" alt="probnode-sdk on PyPI"></a>
  <a href="https://pypi.org/project/probnode-mcp/"><img src="https://img.shields.io/pypi/v/probnode-mcp.svg?label=probnode-mcp" alt="probnode-mcp on PyPI"></a>
  <a href="https://pypi.org/project/probnode-sdk/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/probnode/probnode-sdk/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
</p>

## Overview

The official Python client, command line and MCP server for [ProbNode](https://probnode.com).
ProbNode records Polymarket at full depth: every change of every price level of every outcome
token, every trade, and a published record of what was captured. The data is delivered as parquet
and csv files with a sha256 for every file.

| Package | Install | What it is |
|---|---|---|
| [`probnode-sdk`](packages/probnode) | `pip install probnode-sdk` | The Python client (`import probnode`) and the `probnode` command. |
| [`probnode-mcp`](packages/probnode-mcp) | `pip install probnode-mcp` | An MCP server that gives an AI agent the same API. |

## Features

- **One market's day of the full book in one call.** `export_book` builds and downloads every
  level change and every trade of a market's UTC day, as parquet or csv.gz.
- **Downloads you can trust.** Each file is written to a `.part`, checked against its sha256, and
  only then renamed; `probnode doctor` re-checks a whole directory later.
- **Incremental sync.** `probnode sync` fetches only what is new or changed since the last run.
- **Straight into a table.** `probnode.read()` opens parquet, csv.gz and lp2 as a pyarrow Table,
  ready for pandas, polars or DuckDB.
- **Public catalog and coverage.** Markets, series, samples and the per-hour coverage ledger need
  no key.
- **For AI agents.** `probnode-mcp` exposes the same API as MCP tools, with bulk data handed over
  as signed links rather than through the model's context.

## Installation

```sh
pip install probnode-sdk              # the PyPI name; the import name is `probnode`
pip install "probnode-sdk[pandas]"    # with pandas; `[polars]` for polars
pip install probnode-mcp              # the MCP server
```

Python 3.10 or newer. `pip install probnode` installs an unrelated package: the name was taken.

## Quick start

### Python

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

### Command line

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

### MCP

```json
{"mcpServers": {"probnode": {"command": "probnode-mcp", "env": {"PROBNODE_API_KEY": "pmd_..."}}}}
```

Tools: `datasets`, `search_markets`, `coverage`, `list_files`, `sign_files`, `timeseries`,
`samples`, and `export_book` (a signed link to one market's day of the full book). Every call goes
through the same API, plan and limits as the SDK. Bulk data is handed over as signed URLs rather
than through the model's context; `timeseries` returns at most 500 rows.

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
its own compact format, [Probe](https://github.com/probnode/probe) (`.probe`); what you download
is parquet or csv.

## Documentation

- Documentation: [probnode.com/docs](https://probnode.com/docs)
- Schemas, columns and units: [probnode.com/docs/schemas](https://probnode.com/docs/schemas)
- API reference (OpenAPI 3.1): [probnode.com/openapi.json](https://probnode.com/openapi.json)
- Plans and pricing: [probnode.com/pricing](https://probnode.com/pricing)

## Versioning and compatibility

- Both packages follow [Semantic Versioning](https://semver.org) and are released together with
  the same version number, from a `pypi-vX.Y.Z` tag. Until 1.0, a minor version may change the
  API; every change is listed in the [CHANGELOG](CHANGELOG.md).
- Python 3.10 or newer; CI tests 3.10 and 3.12.
- The client talks to the ProbNode API's `/v1`; answers are returned as dicts and pyarrow Tables,
  so fields the API adds later reach you without an upgrade.

## Support

- Questions about your account, plan or the data: [hello@probnode.com](mailto:hello@probnode.com)
  or the [help centre](https://probnode.com/help).
- Bugs and feature requests for the clients: [open an issue](https://github.com/probnode/probnode-sdk/issues/new/choose).
- Security reports: privately, as the [security policy](SECURITY.md) says.

## Contributing

Pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). This project follows the
[Contributor Covenant](CODE_OF_CONDUCT.md).

## Other ProbNode libraries

| Repository | Language | What it is | Package |
|---|---|---|---|
| [probnode-rs](https://github.com/probnode/probnode-rs) | Rust | The official Rust client: async and blocking, typed models | `probnode` (crates.io release on the way) |
| [probnode-cpp](https://github.com/probnode/probnode-cpp) | C++17 | The official C++ client, built with CMake | CMake `find_package` or FetchContent |
| [probe](https://github.com/probnode/probe) | Rust, Python | Probe, the lossless order-book file format: specification, library and CLI | [`probe-format`](https://crates.io/crates/probe-format), [`probe-cli`](https://crates.io/crates/probe-cli) on crates.io |

## License

MIT, see [LICENSE](LICENSE). Copyright 2026 ProbNode. The license covers the code in this
repository; the data you download is licensed under the terms of your ProbNode plan.
