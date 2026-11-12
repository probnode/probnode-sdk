"""ProbNode as MCP tools, for an AI agent working with Polymarket history.

    {"mcpServers": {"probnode": {"command": "probnode-mcp",
                                 "env": {"PROBNODE_API_KEY": "pn_..."}}}}

Every tool is one ProbNode API call through `probnode.Client`, so an agent sees exactly what a
customer's script sees: the same entitlements, the same quotas, the same refusals in words. Tools
return small JSON; bulk data is handed over as signed URLs (`sign_files`) or a capped range query
(`timeseries`), never streamed through the model's context.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from probnode import Client, ProbNodeError

#: Rows a `timeseries` call returns to the model at most. The API caps a window at 200,000 rows;
#: that is a file, not context. More than this, the tool says so and suggests files instead.
MAX_ROWS_TO_MODEL = 500

mcp = FastMCP("probnode")
_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = Client()
    return _client


def _refusal(exc: ProbNodeError) -> dict[str, Any]:
    return {"error": exc.detail, "status": exc.status}


@mcp.tool()
def datasets() -> Any:
    """Datasets ProbNode holds (books, trades, gaps, markets, quotes, ohlcv_1m), their formats,
    whether a paid plan is needed (tier "tape") and the first and last UTC hour held."""
    try:
        return client().datasets()
    except ProbNodeError as exc:
        return _refusal(exc)


@mcp.tool()
def search_markets(query: str, limit: int = 20) -> Any:
    """Find Polymarket markets by words in their slug or title. Returns slugs, series, start and
    end times, resolution and outcome token ids."""
    try:
        return client().markets(q=query, limit=min(max(limit, 1), 100))
    except ProbNodeError as exc:
        return _refusal(exc)


@mcp.tool()
def coverage(token_id: str, start: str | None = None, end: str | None = None) -> Any:
    """How completely one outcome token was recorded, hour by hour: recorded ms, gaps and uptime.
    Times are ISO UTC. Hours marked implied were recorded whole (no gap touched them)."""
    try:
        return client().coverage(token_id, start, end)
    except ProbNodeError as exc:
        return _refusal(exc)


@mcp.tool()
def list_files(
    dataset: str,
    format: str,
    start: str,
    end: str,
    granularity: str = "hour",
    market: list[str] | None = None,
) -> Any:
    """Files for a dataset and format over [start, end) (ISO UTC, on the hour, at most 31 days):
    object path, rows, bytes and sha256 each, plus totals. granularity "hour" (all markets per
    file) or "market_day" (one market, one UTC day). Needs an API key."""
    try:
        files = client().files(
            dataset, format, start, end, granularity=granularity, market=market or ()
        )
    except ProbNodeError as exc:
        return _refusal(exc)
    return {
        "total_files": len(files),
        "total_bytes": sum(f.bytes for f in files),
        "total_rows": sum(f.rows for f in files),
        "files": [
            {
                "object_path": f.object_path,
                "rows": f.rows,
                "bytes": f.bytes,
                "sha256": f.sha256,
                "market": f.market,
            }
            for f in files[:200]
        ],
        "truncated": len(files) > 200,
    }


@mcp.tool()
def sign_files(object_paths: list[str]) -> Any:
    """Short-lived download URLs (about 15 minutes) for object paths from list_files. Each counts
    against the account's daily signed-URL limit; tape data needs a paid plan."""
    try:
        return client().sign(object_paths)
    except ProbNodeError as exc:
        return _refusal(exc)


@mcp.tool()
def timeseries(dataset: str, market: str, start: str, end: str) -> Any:
    """Rows of one dataset (e.g. quotes, trades, ohlcv_1m) for one market over a short window,
    as JSON objects. For more than a few hundred rows use list_files + sign_files instead."""
    try:
        rows = client().timeseries(dataset, market, start, end, format="ndjson")
    except ProbNodeError as exc:
        return _refusal(exc)
    if len(rows) > MAX_ROWS_TO_MODEL:
        return {
            "rows": rows[:MAX_ROWS_TO_MODEL],
            "returned": MAX_ROWS_TO_MODEL,
            "total": len(rows),
            "note": "more rows than fit here; narrow the window or download files",
        }
    return {"rows": rows, "returned": len(rows), "total": len(rows)}


@mcp.tool()
def samples() -> Any:
    """Free sample files - one market-day per dataset and format - with URLs that need no key."""
    try:
        return client().samples()
    except ProbNodeError as exc:
        return _refusal(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
