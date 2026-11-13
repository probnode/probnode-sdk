"""Query downloaded trades parquet in place with DuckDB, and the same with polars.

Shows: the files the SDK writes are plain parquet under `data/<object_path>`, laid out as
`x/parquet/trades/event_date=YYYY-MM-DD/market=<slug>.parquet`, so any parquet engine reads a whole
directory of them without going through the SDK.

Plan: whatever the downloaded files needed - Research or Pro for trades. Run
examples/02_trades_to_pandas.py (or `probnode download trades parquet ... --granularity market_day`)
first. Requires `pip install duckdb polars`.

    python examples/04_query_parquet.py [data-dir]
"""

import sys
from pathlib import Path

import duckdb
import polars as pl

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
pattern = (root / "x" / "parquet" / "trades" / "**" / "*.parquet").as_posix()
if not list(root.glob("x/parquet/trades/**/*.parquet")):
    sys.exit(f"no trades parquet under {root}: run examples/02_trades_to_pandas.py first")

# The market is the file name (market=<slug>.parquet); event_date= is a directory partition.
MARKET = r"market=([^/]+)\.parquet$"

# DuckDB: SQL straight over the files.
print(
    duckdb.sql(
        f"""
        SELECT event_date,
               regexp_extract(filename, '{MARKET}', 1)          AS market,
               token_id,
               count(*)                                         AS trades,
               sum(size)                                        AS shares,
               sum(price * size) / sum(size)                    AS vwap
        FROM read_parquet('{pattern}', hive_partitioning = true, filename = true)
        GROUP BY ALL
        ORDER BY ALL
        """
    )
)

# polars: the same, lazily.
print(
    pl.scan_parquet(pattern, hive_partitioning=True, include_file_paths="path")
    .with_columns(pl.col("path").str.extract(MARKET, 1).alias("market"))
    .group_by("event_date", "market", "token_id")
    .agg(
        pl.len().alias("trades"),
        pl.col("size").sum().alias("shares"),
        ((pl.col("price") * pl.col("size")).sum() / pl.col("size").sum()).alias("vwap"),
    )
    .sort("event_date", "market", "token_id")
    .collect()
)
