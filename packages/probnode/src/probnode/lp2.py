"""The recorder's LP2 book archive, decoded. Vendored, not imported.

The reference reader for the LP2 format ProbNode's recorder writes, kept byte-for-byte equal to
the copy the ProbNode ingest uses, so what a customer decodes is what the product exported.

What changed against the original, and why:

* `decode` returns the per-level columns (`bid_px0`, `bid_sz0`, ...) the decoder already holds,
  instead of only folding them back into list columns. The exports want exactly those columns
  (the CSV is flat), and rebuilding lists only to flatten them again costs a quarter of the time.
* `to_table` is lobpack's `from_arrays`, for callers that want the books schema as the recorder
  defines it - the round-trip tests compare against it.
* `stream` is new: the same decoding a batch of whole markets at a time, in bounded memory, for
  the ingest. `decode` stays as the reference the tests hold `stream` to.
* LP1 (the xz prototype) is not here. The lake holds LP2 only.

The format, in one paragraph (the Go file is the authority): `b"LOBP2\\n"`, a u32 LE header
length, a JSON header, then one zstd frame per stream in header order. Rows are grouped per token
and stored change-only - every field a zigzag delta against the previous row of the same token,
written only when it changed, with a per-row bit mask saying which. The NO book of a market is the
exact complement of the YES book, so a row of token 2k+1 that mirrors the row of token 2k at the
same millisecond is not stored at all: its partner carries a `twin` bit. Prices are x10000, sizes
x1e6, levels best first.
"""

import json
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyarrow as pa

MAGIC2 = b"LOBP2\n"
VERSION = 2
PX_ONE = 10000  # px ticks of 1e-4: price 1.0

#: The books schema exactly as lobpack defines it, so `to_table` output compares equal to the
#: reference reader's.
SCHEMA = pa.schema(
    [
        ("ts_ms", pa.int64(), False),
        ("ts_ex_ms", pa.int64(), False),
        ("tok", pa.int32(), False),
        ("bid_px", pa.list_(pa.field("element", pa.int32(), False)), False),
        ("bid_sz", pa.list_(pa.field("element", pa.int64(), False)), False),
        ("ask_px", pa.list_(pa.field("element", pa.int32(), False)), False),
        ("ask_sz", pa.list_(pa.field("element", pa.int64(), False)), False),
        ("snap", pa.bool_(), False),
        ("shard", pa.int32(), False),
        ("conn", pa.int32(), False),
    ]
)

SIDES = ("bid_px", "bid_sz", "ask_px", "ask_sz")


@dataclass(frozen=True)
class Decoded:
    """One LP2 object as columns, in (ts_ms, tok) order like the reference reader.

    `columns` holds `ts_ms`, `ts_ex_ms`, `tok`, `snap`, `shard`, `conn`, the level counts `nb` and
    `na`, and one array per side and level (`bid_px0` ... `ask_sz{depth-1}`). An absent level is 0
    in its array and is outside `nb`/`na`; nothing else marks it.
    """

    header: dict[str, Any]
    depth: int
    columns: dict[str, np.ndarray]

    @property
    def rows(self) -> int:
        return int(self.columns["ts_ms"].size)


# ---------- varint / zigzag (vectorised), as in lobpack ----------


def unzz(u: np.ndarray) -> np.ndarray:
    u = u.astype(np.uint64)
    return ((u >> np.uint64(1)).astype(np.int64)) ^ (-(u & np.uint64(1)).astype(np.int64))


def vdec(buf: bytes, count: int) -> np.ndarray:
    b = np.frombuffer(buf, np.uint8)
    ends = np.flatnonzero(b < 0x80)
    if ends.size != count:
        raise ValueError(f"varint stream has {ends.size} values, header says {count}")
    if count == 0:
        return np.zeros(0, np.uint64)
    starts = np.r_[0, ends[:-1] + 1]
    lens = ends - starts + 1
    out = np.zeros(count, np.uint64)
    for k in range(int(lens.max())):
        m = lens > k
        out[m] |= (b[starts[m] + k] & np.uint64(0x7F)).astype(np.uint64) << np.uint64(7 * k)
    return out


def seg_cumsum(d: np.ndarray, run_start: np.ndarray, run_len: np.ndarray) -> np.ndarray:
    c = np.cumsum(d)
    before = np.r_[0, c[:-1]][run_start]
    return c - np.repeat(before, run_len)


def mirror_of(F: dict[str, np.ndarray], depth: int, i: np.ndarray) -> dict[str, np.ndarray]:
    """Complement rows of rows i (token 2k -> 2k+1)."""
    G = {
        "ts_ms": F["ts_ms"][i],
        "ts_ex_ms": F["ts_ex_ms"][i],
        "tok": F["tok"][i] + 1,
        "snap": F["snap"][i],
        "shard": F["shard"][i],
        "conn": F["conn"][i],
        "nb": F["na"][i],
        "na": F["nb"][i],
    }
    for k in range(depth):
        G[f"bid_px{k}"] = np.where(F["na"][i] > k, PX_ONE - F[f"ask_px{k}"][i], 0)
        G[f"bid_sz{k}"] = np.where(F["na"][i] > k, F[f"ask_sz{k}"][i], 0)
        G[f"ask_px{k}"] = np.where(F["nb"][i] > k, PX_ONE - F[f"bid_px{k}"][i], 0)
        G[f"ask_sz{k}"] = np.where(F["nb"][i] > k, F[f"bid_sz{k}"][i], 0)
    return G


def read_header(blob: bytes) -> tuple[dict[str, Any], int]:
    """The JSON header and the offset of the first stream. Cheap: reads no stream."""
    if blob[: len(MAGIC2)] != MAGIC2:
        raise ValueError("not an LP2 object")
    p = len(MAGIC2)
    (hl,) = struct.unpack("<I", blob[p : p + 4])
    hdr = json.loads(blob[p + 4 : p + 4 + hl])
    if hdr["version"] != VERSION or hdr["codec"] != "zstd":
        raise ValueError(f"LP2 version {hdr['version']} codec {hdr['codec']}")
    return hdr, p + 4 + hl


def decode(blob: bytes) -> Decoded:
    """lobpack's `unpack2`, stopping before the list columns are rebuilt."""
    hdr, p = read_header(blob)
    codec = pa.Codec("zstd")
    S = {}
    for s in hdr["streams"]:
        z = blob[p : p + s["z"]]
        p += s["z"]
        raw = codec.decompress(z, decompressed_size=s["raw"], asbytes=True) if s["raw"] else b""
        S[s["name"]] = vdec(raw, s["count"])
    if p != len(blob):
        raise ValueError("trailing bytes after the last stream")
    depth, names, m = hdr["depth"], hdr["fields"], hdr["rows_kept"]
    run_tok = np.cumsum(S["run_tok"].astype(np.int64) + 1) - 1
    run_len = S["run_len"].astype(np.int64) + 1
    if int(run_len.sum()) != m:
        raise ValueError("run lengths do not add up to rows_kept")
    run_start = np.r_[0, np.cumsum(run_len)[:-1]].astype(np.int64)
    new = np.zeros(m, bool)
    new[run_start] = True
    F = {"tok": np.repeat(run_tok, run_len)}
    dts = np.zeros(m, np.int64)
    dts[~new] = unzz(S["dts"])
    dts[run_start] = unzz(S["run_ts0"]) + hdr["base_ts"]
    F["ts_ms"] = seg_cumsum(dts, run_start, run_len)
    F["ts_ex_ms"] = F["ts_ms"] - unzz(S["ex_lag"])
    mask = S["mask"]
    for bit, nm in enumerate(names):
        ch = ((mask >> np.uint64(bit)) & np.uint64(1)).astype(bool)
        d = np.zeros(m, np.int64)
        d[ch] = unzz(S["f_" + nm])
        F[nm] = seg_cumsum(d, run_start, run_len)
    nf = len(names)
    F["snap"] = ((mask >> np.uint64(nf)) & np.uint64(1)).astype(np.int64)
    ti = np.flatnonzero(((mask >> np.uint64(nf + 1)) & np.uint64(1)).astype(bool))
    if ti.size != hdr["rows_mirror"]:
        raise ValueError(f"twin bits {ti.size} != rows_mirror {hdr['rows_mirror']}")
    G = mirror_of(F, depth, ti)
    for c in F:
        F[c] = np.r_[F[c], G[c]]
    o = np.lexsort((F["tok"], F["ts_ms"]))
    for c in F:
        F[c] = F[c][o]
    if F["ts_ms"].size != hdr["rows"]:
        raise ValueError("row count mismatch")
    return Decoded(header=hdr, depth=depth, columns=F)


def to_table(decoded: Decoded) -> pa.Table:
    """lobpack's `from_arrays`: the books schema with list columns, as the recorder defines it."""
    F, depth = decoded.columns, decoded.depth
    cols = {}
    for c, dt, cnt in (
        ("bid_px", pa.int32(), "nb"),
        ("bid_sz", pa.int64(), "nb"),
        ("ask_px", pa.int32(), "na"),
        ("ask_sz", pa.int64(), "na"),
    ):
        cols[c] = pa.ListArray.from_arrays(
            list_offsets(F[cnt]), level_values(F, c, depth, F[cnt]).astype(dt.to_pandas_dtype())
        ).cast(SCHEMA.field(c).type)
    arrs = [
        pa.array(F["ts_ms"], pa.int64()),
        pa.array(F["ts_ex_ms"], pa.int64()),
        pa.array(F["tok"].astype(np.int32), pa.int32()),
        cols["bid_px"],
        cols["bid_sz"],
        cols["ask_px"],
        cols["ask_sz"],
        pa.array(F["snap"].astype(bool), pa.bool_()),
        pa.array(F["shard"].astype(np.int32), pa.int32()),
        pa.array(F["conn"].astype(np.int32), pa.int32()),
    ]
    return pa.Table.from_arrays(arrs, schema=SCHEMA)


def list_offsets(lengths: np.ndarray) -> pa.Array:
    """List offsets for per-row level counts."""
    return pa.array(np.r_[0, np.cumsum(lengths)].astype(np.int32), pa.int32())


def level_values(
    F: dict[str, np.ndarray], side: str, depth: int, lengths: np.ndarray
) -> np.ndarray:
    """The present levels of one side, flattened row by row, best level first."""
    if not depth:
        return np.zeros(0, np.int64)
    M = np.stack([F[f"{side}{k}"] for k in range(depth)], axis=1)
    keep = np.arange(depth)[None, :] < lengths[:, None]
    return M[keep]


# ---------- streaming: one window in bounded memory ----------
#
# Not in lobpack. A real hour is one window of about 35 million rows, and `decode` holds all of
# them at once (about 3 GB). The ingest runs on a box with far less, so it reads the window the
# way it is laid out: token by token. Every stream is decompressed incrementally and its varints
# are consumed through a cursor, a batch of whole token runs at a time. A batch never splits the
# two tokens of one market, so a mirrored row always lands in the same batch as its partner and a
# market's rows stay contiguous in the output.


class _Varints:
    """The varints of one zstd stream, read incrementally. `take(n)` returns the next n values."""

    def __init__(self, name: str, frame: pa.Buffer, count: int, raw: int) -> None:
        self._name = name
        self._stream = pa.input_stream(frame, compression="zstd") if raw else None
        self._buf = np.zeros(0, np.uint8)
        self._left = count
        self._raw_left = raw

    def take(self, n: int) -> np.ndarray:
        if n > self._left:
            raise ValueError(f"stream {self._name}: {n} values asked, {self._left} left")
        if n == 0:
            return np.zeros(0, np.uint64)
        while True:
            ends = np.flatnonzero(self._buf < 0x80)
            if ends.size >= n:
                break
            if self._stream is None:
                raise ValueError(f"stream {self._name} ended early")
            more = self._stream.read(max(1 << 20, 2 * (n - ends.size)))
            if not more:
                raise ValueError(f"stream {self._name} ended early")
            self._raw_left -= len(more)
            self._buf = np.concatenate([self._buf, np.frombuffer(more, np.uint8)])
        cut = int(ends[n - 1]) + 1
        values = vdec(self._buf[:cut].tobytes(), n)
        self._buf = self._buf[cut:]
        self._left -= n
        return values

    def finish(self) -> None:
        """Every value consumed and not a byte more - the streaming form of lobpack's checks."""
        trailing = self._stream.read() if self._stream is not None else b""
        self._raw_left -= len(trailing)
        if self._left or self._buf.size or trailing or self._raw_left:
            raise ValueError(f"stream {self._name} does not match its header")


def stream(buffer: pa.Buffer, max_rows: int) -> Iterator[Decoded]:
    """The rows of one LP2 object in batches of whole markets, each in (tok, ts_ms) order.

    `max_rows` bounds the stored rows of a batch; mirrored rows come on top, at most as many
    again. A single market larger than that is still one batch, because splitting it would
    separate a row from its mirror. Within a market the order is lobpack's tie order.
    """
    hdr, p = read_header(buffer.slice(0, min(buffer.size, 1 << 20)).to_pybytes())
    cursors: dict[str, _Varints] = {}
    for s in hdr["streams"]:
        if p + s["z"] > buffer.size:
            raise ValueError(f"stream {s['name']} runs past the end of the object")
        cursors[s["name"]] = _Varints(s["name"], buffer.slice(p, s["z"]), s["count"], s["raw"])
        p += s["z"]
    if p != buffer.size:
        raise ValueError("trailing bytes after the last stream")
    depth, names = hdr["depth"], hdr["fields"]
    runs = next(s["count"] for s in hdr["streams"] if s["name"] == "run_tok")
    run_tok = np.cumsum(cursors["run_tok"].take(runs).astype(np.int64) + 1) - 1
    run_len = cursors["run_len"].take(runs).astype(np.int64) + 1
    run_ts0 = unzz(cursors["run_ts0"].take(runs)) + hdr["base_ts"]
    if int(run_len.sum()) != hdr["rows_kept"]:
        raise ValueError("run lengths do not add up to rows_kept")

    # A batch may end only where the next run starts another market (tok // 2 changes).
    market_start = np.r_[True, (run_tok[1:] // 2) != (run_tok[:-1] // 2)]
    rows_seen = mirrors_seen = 0
    a = 0
    while a < runs:
        b = a + 1
        total = int(run_len[a])
        while b < runs and (not market_start[b] or total + int(run_len[b]) <= max_rows):
            total += int(run_len[b])
            b += 1
        lens = run_len[a:b]
        m = int(lens.sum())
        starts = np.r_[0, np.cumsum(lens)[:-1]].astype(np.int64)
        new = np.zeros(m, bool)
        new[starts] = True
        F = {"tok": np.repeat(run_tok[a:b], lens)}
        dts = np.zeros(m, np.int64)
        dts[~new] = unzz(cursors["dts"].take(m - (b - a)))
        dts[starts] = run_ts0[a:b]
        F["ts_ms"] = seg_cumsum(dts, starts, lens)
        F["ts_ex_ms"] = F["ts_ms"] - unzz(cursors["ex_lag"].take(m))
        mask = cursors["mask"].take(m)
        for bit, nm in enumerate(names):
            ch = ((mask >> np.uint64(bit)) & np.uint64(1)).astype(bool)
            d = np.zeros(m, np.int64)
            d[ch] = unzz(cursors["f_" + nm].take(int(ch.sum())))
            F[nm] = seg_cumsum(d, starts, lens)
        nf = len(names)
        F["snap"] = ((mask >> np.uint64(nf)) & np.uint64(1)).astype(np.int64)
        ti = np.flatnonzero(((mask >> np.uint64(nf + 1)) & np.uint64(1)).astype(bool))
        G = mirror_of(F, depth, ti)
        for c in F:
            F[c] = np.r_[F[c], G[c]]
        o = np.lexsort((F["ts_ms"], F["tok"]))
        for c in F:
            F[c] = F[c][o]
        rows_seen += F["ts_ms"].size
        mirrors_seen += ti.size
        yield Decoded(header=hdr, depth=depth, columns=F)
        a = b

    # Streams this reader decodes are held to their header exactly. A stream it does not know - an
    # addition a newer writer makes, like the legacy archive's sub_ns - is skipped, the way
    # lobpack's unpack2 skips it: an extension must not make an older reader refuse the file.
    known = {"run_tok", "run_len", "run_ts0", "dts", "ex_lag", "mask"} | {f"f_{n}" for n in names}
    for name, cursor in cursors.items():
        if name in known:
            cursor.finish()
    if rows_seen != hdr["rows"] or mirrors_seen != hdr["rows_mirror"]:
        raise ValueError(
            f"rows {rows_seen} (mirror {mirrors_seen}) != header {hdr['rows']} "
            f"({hdr['rows_mirror']})"
        )
