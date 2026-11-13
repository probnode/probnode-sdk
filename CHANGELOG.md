# Changelog

All notable changes to `probnode-sdk` and `probnode-mcp` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and both packages follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The two packages are released together
with the same version number.

## [Unreleased]

## [0.2.0] - 2026-11-13

### Added

- `probnode-sdk`: `Client.export_book(market, day, dest)` downloads one market's UTC day of the
  full order book (every level change and every trade) as parquet or csv.gz, checked against its
  sha256; `Client.book_export()` returns the signed link and the file's rows, bytes and sha256
  without downloading.
- `probnode-sdk`: `probnode export MARKET DAY [--format parquet|csv] [-o DIR]` on the command line.
- `probnode-mcp`: the `export_book` tool, a signed link to one market's day of the full book.

## [0.1.0] - 2026-11-12

First release of both packages on PyPI.

### Added

- `probnode-sdk`: `probnode.Client`, one HTTP call per method, with the key taken from the
  argument, `PROBNODE_API_KEY`, or what `probnode login` saved.
  - Account: `login`, `me`, `usage`.
  - Catalog, public and keyless: `datasets`, `series`, `markets`, `coverage`, `samples`.
  - Files: `files` (hourly or `granularity="market_day"`, narrowed by `market` or `series`),
    `sign`, `download` and `download_all`. A download is written to a `.part` file and renamed only
    once complete and its sha256 matches the listing.
  - `timeseries`: one market's rows over a window of up to 7 days, as a pyarrow Table or a list of
    dicts.
  - Errors raise `ProbNodeError` with the HTTP status and the API's own message.
- `probnode-sdk`: `probnode.read(path)` opens a downloaded parquet, csv.gz or lp2 file as a pyarrow
  Table; `probnode.iter_lp2(path)` reads an lp2 file in bounded memory.
- `probnode-sdk`: the `probnode` command: `login`, `datasets`, `files`, `download`, `sync` and
  `doctor`. `sync` fetches only what is new or changed, and fetches again any file whose size or
  modification time changed on disk since it was written; `doctor` re-checks every synced file's
  sha256.
- `probnode-mcp`: an MCP server exposing `datasets`, `search_markets`, `coverage`, `list_files`,
  `sign_files`, `timeseries` and `samples`. Bulk data is returned as signed URLs; `timeseries`
  returns at most 500 rows to the model.

[Unreleased]: https://github.com/probnode/probnode-sdk/compare/pypi-v0.2.0...HEAD
[0.2.0]: https://github.com/probnode/probnode-sdk/compare/pypi-v0.1.0...pypi-v0.2.0
[0.1.0]: https://github.com/probnode/probnode-sdk/releases/tag/pypi-v0.1.0
