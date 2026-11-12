"""Open any downloaded ProbNode file as a pyarrow Table: lp2, parquet or csv.gz."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa

#: Stored rows per decode batch. About 0.5 GB of working memory on a real hour of books; a
#: whole-object decode of the same hour needs ~8 GB, which is why lp2 is always read in batches.
LP2_BATCH_ROWS = 200_000


def iter_lp2(path: str | Path, batch_rows: int = LP2_BATCH_ROWS) -> Iterator[pa.Table]:
    """The books in one lp2 file as tables of whole markets, in bounded memory.

    Columns: ts_ms (our receive clock) and ts_ex_ms (the venue's), tok (index into the file's
    token list), the bid/ask price and size lists - prices x10000, sizes x1e6, best level first -
    snap, shard and conn.
    """
    from . import lp2

    buffer = pa.memory_map(str(path)).read_buffer()
    for decoded in lp2.stream(buffer, batch_rows):
        yield lp2.to_table(decoded)


def read(path: str | Path) -> pa.Table:
    """A pyarrow Table for one file. `.to_pandas()` or `polars.from_arrow()` from there.

    An hour of books is tens of millions of rows; for lp2 prefer `iter_lp2` unless the whole hour
    fits in memory, and for parquet `pyarrow.parquet.ParquetFile(path).iter_batches()`.
    """
    path = Path(path)
    name = path.name
    if name.endswith(".lp2"):
        return pa.concat_tables(iter_lp2(path))
    if name.endswith(".parquet"):
        import pyarrow.parquet as pq

        return pq.read_table(path)
    if name.endswith(".csv.gz") or name.endswith(".csv"):
        import pyarrow.csv as pacsv

        return pacsv.read_csv(path)
    raise ValueError(f"not a ProbNode data file (lp2, parquet, csv.gz): {path}")
