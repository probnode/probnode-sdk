"""Open any downloaded ProbNode file as a pyarrow Table: Probe, parquet, csv.gz - or lp2.

Probe (`.evmin`) is the full book and the format the book is delivered in. It is decoded by the
published reader, `probe-format`, which is the same Rust implementation behind the `probe` CLI and
is not vendored here: one decoder, with its own conformance vectors, rather than a second one that
could drift from it. Install it with the extra - `pip install "probnode-sdk[probe]"`.

lp2 is the earlier three-level book. It is no longer delivered (2026-11-21), and the vendored
decoder stays for as long as anyone holds a file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa

#: Stored rows per decode batch. About 0.5 GB of working memory on a real hour of books; a
#: whole-object decode of the same hour needs ~8 GB, which is why lp2 is always read in batches.
LP2_BATCH_ROWS = 200_000
#: The extensions a Probe file is written with. `.evmin` is what the recorder writes and what the
#: lake holds - it is the format's own version string (`evmin/4`, `/5`, `/6`); `.probe` is the
#: name the CLI's own examples use.
PROBE_SUFFIXES = (".evmin", ".probe")


def _probe_format():  # noqa: ANN202 - the module, or a message that says what to install
    try:
        import probe_format
    except ImportError as exc:  # pragma: no cover - exercised by test_read_probe_without_extra
        raise ImportError(
            "reading Probe needs the published reader: pip install 'probnode-sdk[probe]' "
            "(or pip install probe-format). It is Apache-2.0, github.com/probnode/probe"
        ) from exc
    return probe_format


def open_probe(path: str | Path):  # noqa: ANN201 - probe_format's own file handle
    """The `probe_format` handle for a Probe file: `.version`, `.header`, `.markets()`, `.events()`,
    `.levels()`, `.book_max()`, `.book_at()`, `.transcode()`.

    Use this when you want one market, one time range or the book at an instant. `read()` and
    `iter_probe()` are the two convenience paths over it.
    """
    return _probe_format().open(str(path))


def iter_probe(path: str | Path) -> Iterator[pa.Table]:
    """One `book-max` table per market of a Probe hour, in bounded memory.

    The same shape as `iter_lp2`: whole markets, one at a time, because an hour of the full book
    is hundreds of millions of levels and nobody's laptop holds it at once. A market's block index
    makes each of these a seek rather than a scan.
    """
    handle = open_probe(path)
    for slug in handle.markets()["slug"].to_pylist():
        yield handle.book_max(market=slug)


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

    An hour of books is tens of millions of rows; for Probe prefer `iter_probe` and for lp2
    `iter_lp2` unless the whole hour fits in memory, and for parquet
    `pyarrow.parquet.ParquetFile(path).iter_batches()`.
    """
    path = Path(path)
    name = path.name
    if name.endswith(PROBE_SUFFIXES):
        return pa.concat_tables(list(iter_probe(path)))
    if name.endswith(".lp2"):
        return pa.concat_tables(iter_lp2(path))
    if name.endswith(".parquet"):
        import pyarrow.parquet as pq

        return pq.read_table(path)
    if name.endswith(".csv.gz") or name.endswith(".csv"):
        import pyarrow.csv as pacsv

        return pacsv.read_csv(path)
    raise ValueError(f"not a ProbNode data file (probe/.evmin, parquet, csv.gz, lp2): {path}")
