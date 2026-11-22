"""Reading Probe, the format the full book is delivered in (owner, 2026-11-21).

The decoding itself belongs to `probe-format`, the published reader, and is covered by its own
conformance vectors - not re-tested here. What this file holds is the part that is ours and the
part that breaks silently: that a `.evmin` file is routed to that reader at all, that an hour is
handed over a market at a time rather than in one table nobody's laptop can hold, and that a
missing extra says what to install instead of raising `ModuleNotFoundError` at a customer.

A real Probe file is not committed: the smallest honest one is megabytes, this package is
mirrored on its own, and the reader it would exercise has its own vectors. Set
`PROBNODE_PROBE_SAMPLE` to a Probe file to run the end-to-end case as well.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pyarrow as pa
import pytest

import probnode
from probnode import read as read_module


class FakeHandle:
    """What `probe_format.open()` returns, in the shape `read.py` uses."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.version = 2
        self.header = {"markets": 2}
        self.asked: list[str] = []

    def markets(self) -> pa.Table:
        return pa.table({"slug": ["will-x-happen", "will-y-happen"]})

    def book_max(self, market: str) -> pa.Table:
        self.asked.append(market)
        return pa.table({"market": [market], "price": [500_000]})


@pytest.fixture()
def fake_probe_format(monkeypatch: pytest.MonkeyPatch) -> list[FakeHandle]:
    made: list[FakeHandle] = []

    def opener(path: str) -> FakeHandle:
        handle = FakeHandle(path)
        made.append(handle)
        return handle

    module = types.ModuleType("probe_format")
    module.open = opener  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "probe_format", module)
    return made


def test_probnode_exports_the_probe_readers() -> None:
    assert {"read", "iter_probe", "open_probe", "iter_lp2"} <= set(probnode.__all__)


@pytest.mark.parametrize("suffix", [".evmin", ".probe"])
def test_read_routes_probe_files_to_the_published_reader(
    tmp_path: Path, fake_probe_format: list[FakeHandle], suffix: str
) -> None:
    """`.evmin` is what the lake holds; `.probe` is what the CLI's own examples call it."""
    path = tmp_path / f"hour{suffix}"
    path.write_bytes(b"EVM4 not really, the reader is faked here")
    table = probnode.read(path)
    assert table.num_rows == 2  # one market per row, both markets concatenated
    assert fake_probe_format[0].asked == ["will-x-happen", "will-y-happen"]


def test_iter_probe_yields_one_market_at_a_time(
    tmp_path: Path, fake_probe_format: list[FakeHandle]
) -> None:
    path = tmp_path / "hour.evmin"
    path.write_bytes(b"EVM4")
    tables = list(probnode.iter_probe(path))
    assert [t.column("market")[0].as_py() for t in tables] == [
        "will-x-happen",
        "will-y-happen",
    ]
    assert all(t.num_rows == 1 for t in tables), "an hour must not arrive as one table"


def test_open_probe_hands_over_the_readers_own_handle(
    tmp_path: Path, fake_probe_format: list[FakeHandle]
) -> None:
    path = tmp_path / "hour.evmin"
    path.write_bytes(b"EVM4")
    handle = probnode.open_probe(path)
    assert handle.version == 2 and handle.header["markets"] == 2


def test_a_missing_extra_says_what_to_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    #: `None` in sys.modules is the documented way to make an import fail: Python raises
    #: ImportError rather than searching, which is exactly the customer's situation.
    monkeypatch.setitem(sys.modules, "probe_format", None)
    path = tmp_path / "hour.evmin"
    path.write_bytes(b"EVM4")
    with pytest.raises(ImportError) as caught:
        probnode.read(path)
    message = str(caught.value)
    assert "probnode-sdk[probe]" in message
    assert "github.com/probnode/probe" in message


def test_an_unknown_extension_names_every_format_we_read(tmp_path: Path) -> None:
    path = tmp_path / "hour.lobpack"
    path.write_bytes(b"?")
    with pytest.raises(ValueError, match=r"probe/\.evmin, parquet, csv\.gz, lp2"):
        probnode.read(path)


@pytest.mark.skipif(
    not os.environ.get("PROBNODE_PROBE_SAMPLE"),
    reason="set PROBNODE_PROBE_SAMPLE to a Probe file to decode one for real",
)
def test_a_real_probe_hour_decodes() -> None:
    sample = Path(os.environ["PROBNODE_PROBE_SAMPLE"])
    handle = probnode.open_probe(sample)
    assert handle.version in (1, 2, 3)
    first = next(iter(probnode.iter_probe(sample)))
    assert first.num_rows > 0
    assert read_module.PROBE_SUFFIXES[0] == ".evmin"
