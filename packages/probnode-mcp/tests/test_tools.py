"""The MCP tools against a stub client: they pass arguments through, cap what reaches the model,
and turn API refusals into a JSON error instead of a crashed tool call."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from probnode import DataFile, ProbNodeError

from probnode_mcp import server


class Stub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def datasets(self) -> list[dict]:
        return [{"code": "books"}]

    def files(self, *args: Any, **kw: Any) -> list[DataFile]:
        self.calls.append(("files", (args, kw)))
        if args[0] == "secret":
            raise ProbNodeError(402, "books need a paid plan")
        return [
            DataFile("books", "parquet", "2026-11-08", h, "s6", f"x/{h}", 10, 100, "ab" * 32)
            for h in range(250)
        ]

    def sign(self, paths: list[str]) -> dict[str, str]:
        return {p: f"https://lake/{p}" for p in paths}

    def timeseries(self, *args: Any, **kw: Any) -> list[dict]:
        assert kw["format"] == "ndjson"
        return [{"i": i} for i in range(int(args[1]))]


@pytest.fixture(autouse=True)
def stub(monkeypatch: pytest.MonkeyPatch) -> Stub:
    s = Stub()
    monkeypatch.setattr(server, "_client", s)
    return s


def test_list_files_totals_and_truncates(stub: Stub) -> None:
    out = server.list_files("books", "parquet", "a", "b", granularity="market_day", market=["m"])
    assert out["total_files"] == 250 and out["total_bytes"] == 25_000
    assert len(out["files"]) == 200 and out["truncated"] is True
    assert stub.calls[0][1][1] == {"granularity": "market_day", "market": ["m"]}


def test_refusal_is_returned_not_raised() -> None:
    assert server.list_files("secret", "parquet", "a", "b") == {
        "error": "books need a paid plan",
        "status": 402,
    }


def test_timeseries_caps_rows_for_the_model() -> None:
    small = server.timeseries("quotes", "3", "a", "b")
    assert small["returned"] == 3 and small["total"] == 3
    big = server.timeseries("quotes", "1000", "a", "b")
    assert big["returned"] == server.MAX_ROWS_TO_MODEL and big["total"] == 1000 and big["note"]


def test_every_tool_is_registered() -> None:
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {
        "datasets",
        "search_markets",
        "coverage",
        "list_files",
        "sign_files",
        "timeseries",
        "samples",
    }
