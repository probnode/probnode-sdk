"""The real-time stream `/v2/live`: connect, subscribe, read messages (JSON dicts or Probe records).

    import asyncio
    from probnode.live import Live

    async def main():
        async with Live(url="wss://<live host>/v2/live", key="pmd_...") as live:
            await live.subscribe(["btc-updown-15m-1795366800"], ["book+", "trades+"])
            async for msg in live:
                if msg["type"] == "book+":
                    risk = msg["probnode"]["risk"]["factors"]
                    print(msg["bb"], msg["ba"], risk["depth"]["deviation"]["p_bucket"])

    asyncio.run(main())

`format="probe"` gets the same events as binary records (book+ / trades+ as the event's records:
levels, the probnode record, the BookExt / TradeExt); `decode()` turns a frame into dicts. Needs
the `websockets` package (`pip install probnode[live]`).
"""

from __future__ import annotations

import json
import struct
from collections.abc import AsyncIterator, Iterable
from typing import Any

PRICE = 1e9  # prices are integers x1e9 on the wire
SIZE = 1e6  # sizes and USD x1e6
MISSING = -(1 << 63)
PN_NONE = -(1 << 31)

BOOK_LEVEL, TRADE, FILL, WALLET, SYMBOL = 0x01, 0x02, 0x03, 0x04, 0x05
STATS, SIGNAL, BOOK_EXT, TRADE_EXT, PROBNODE_EXT, GAP, HEARTBEAT = (
    0x10,
    0x11,
    0x12,
    0x13,
    0x14,
    0x20,
    0x21,
)

PN_NAMES = (
    "spread",
    "depth_bid",
    "depth_ask",
    "imbalance",
    "microprice_lean",
    "updates_per_s",
    "volume_1m",
    "trades_1m",
    "taker_imbalance_1m",
    "avg_trade",
    "cost_to_trade.buy",
    "cost_to_trade.sell",
    "depth",
    "resilience",
    "volatility.10s",
    "volatility.1m",
    "adverse_selection",
    "quote_stability",
    "resolution_jump",
)
PN_FACTORS = 9


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode()


def _header(p: bytes) -> dict[str, Any]:
    _, rtype, venue, inst, ts = struct.unpack_from("<BBHIQ", p, 0)
    return {"rtype": rtype, "venue": venue, "instrument": inst, "ts_event": ts}


def _probnode(p: bytes) -> dict[str, Any]:
    h = _header(p)
    ts_recv, ref, kind, flag, open_ = struct.unpack_from("<QIBBB", p, 16)
    metrics, o = {}, 80
    for name in PN_NAMES:
        value, xnorm, pb, ps = struct.unpack_from("<qiBB", p, o)
        metrics[name] = {
            "value": None if value == MISSING else value / 1e6,
            "x_norm": None if xnorm == PN_NONE else xnorm / 1e4,
            "p_bucket": None if pb == 255 else pb,
            "p_self": None if ps == 255 else ps,
        }
        o += 16
    for name in PN_NAMES[-PN_FACTORS:]:
        a50, a90 = struct.unpack_from("<ii", p, o)
        metrics[name]["after_move_60s"] = (
            None if a50 == PN_NONE else {"p50": a50 / 1e6, "p90": a90 / 1e6}
        )
        o += 8
    return {
        **h,
        "type": "probnode",
        "ts_recv": ts_recv,
        "ref": ref,
        "kind": "trade" if kind else "book",
        "security": {"flag": "attack" if flag else "none", "open": open_},
        "stats": {"bucket": _cstr(p[32:64]), "stats_version": _cstr(p[64:80])},
        "metrics": metrics,
    }


def decode(frame: bytes) -> list[dict[str, Any]]:
    """The records of one binary (Probe) frame. Book levels, trades and probnode records are
    decoded; every other type comes back with its header and its bytes (`raw`)."""
    out, i = [], 0
    while i + 16 <= len(frame):
        n = frame[i] * 4
        if n < 16 or i + n > len(frame):
            raise ValueError(f"bad record length {n} at {i}")
        p = frame[i : i + n]
        h = _header(p)
        if h["rtype"] in (BOOK_LEVEL, TRADE):
            ts_recv, price, size, seq = struct.unpack_from("<QqqI", p, 16)
            rec = {
                **h,
                "type": "book" if h["rtype"] == BOOK_LEVEL else "trade",
                "ts_recv": ts_recv,
                "price": price / PRICE,
                "size": size / SIZE,
                "seq": seq,
                "side": p[44],
            }
            if h["rtype"] == BOOK_LEVEL:
                rec["action"], rec["flags"] = chr(p[45]), p[46]
        elif h["rtype"] == PROBNODE_EXT:
            rec = _probnode(p)
        else:
            rec = {**h, "type": f"0x{h['rtype']:02x}", "raw": p}
        out.append(rec)
        i += n
    return out


class Live:
    """One connection to `/v2/live`. The key (an account's API key) sets the plan; none = Free."""

    def __init__(self, url: str, key: str | None = None, *, format: str = "json") -> None:
        if format not in ("json", "probe"):
            raise ValueError("format is json or probe")
        self.url, self.key, self.format = url, key, format
        self._ws: Any = None

    async def __aenter__(self) -> Live:
        import websockets  # optional dependency: probnode[live]

        headers = {"Authorization": f"Bearer {self.key}"} if self.key else None
        self._ws = await websockets.connect(self.url, additional_headers=headers, max_size=None)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def subscribe(
        self,
        markets: Iterable[str],
        channels: Iterable[str] = ("book+", "trades+"),
        blocks: Iterable[str] | None = None,
    ) -> None:
        """Watch markets on channels; blocks picks the probnode blocks.

        Blocks: analytics, risk, security, stats (all when None).
        """
        msg: dict[str, Any] = {
            "op": "sub",
            "markets": list(markets),
            "channels": list(channels),
            "format": self.format,
        }
        if blocks is not None:
            msg["blocks"] = list(blocks)
        await self._ws.send(json.dumps(msg))

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async for frame in self._ws:
            if isinstance(frame, bytes):
                for rec in decode(frame):
                    yield rec
                continue
            m = json.loads(frame)
            for rec in m if isinstance(m, list) else [m]:
                yield rec
