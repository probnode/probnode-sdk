"""probnode.live: the Probe (binary) frame decoder against a frame the Go engine wrote."""

from pathlib import Path

import pytest

from probnode.live import Live, decode

FRAME = bytes.fromhex((Path(__file__).parent / "live_frame.hex").read_text().strip())


def test_decode_a_book_level_and_its_probnode_record() -> None:
    recs = decode(FRAME)
    assert [r["type"] for r in recs] == ["book", "probnode"]
    lv, pn = recs
    assert lv["price"] == 0.49 and lv["size"] == 1000 and lv["seq"] == 42 and lv["instrument"] == 7
    assert pn["ref"] == 42 and pn["kind"] == "book"
    assert pn["stats"] == {"bucket": pn["stats"]["bucket"], "stats_version": "v0-fixture"}
    assert pn["stats"]["bucket"].startswith("updown-15m|")
    spread = pn["metrics"]["spread"]
    assert spread["value"] == 0.02 and spread["p_bucket"] == 50 and spread["x_norm"] == 1.0
    assert pn["metrics"]["imbalance"]["value"] is None  # Missing in the fixture State
    assert pn["metrics"]["depth"]["value"] == 1000.0  # $490 + $510 within 5c
    assert (
        pn["metrics"]["cost_to_trade.buy"]["after_move_60s"] is None
    )  # no after table in the fixture
    assert pn["security"] == {"flag": "none", "open": 0}


def test_decode_refuses_a_truncated_frame() -> None:
    with pytest.raises(ValueError):
        decode(FRAME[:-8])


def test_format_is_checked() -> None:
    with pytest.raises(ValueError):
        Live("wss://example.test/v2/live", format="xml")


def test_reconnect_resubscribes_and_reports_the_gap() -> None:
    """A live server that drops the first connection: the client reopens, sends its subscription
    again (one message per channel set), and on_gap gets the stretch."""
    import asyncio
    import json

    websockets = pytest.importorskip("websockets")
    got: list[list[dict]] = []
    gaps: list[tuple[int, int]] = []

    async def handler(ws) -> None:  # type: ignore[no-untyped-def]
        msgs = []
        conn = len(got)
        got.append(msgs)
        async for raw in ws:
            m = json.loads(raw)
            msgs.append(m)
            if m["op"] == "sub":
                await ws.send(json.dumps({"type": "header", "conn": conn}))
                if conn == 0:
                    await ws.close()
                    return

    async def main() -> None:
        async with websockets.serve(handler, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            live = Live(
                f"ws://127.0.0.1:{port}", reconnect=True, on_gap=lambda a, b: gaps.append((a, b))
            )
            async with live:
                await live.subscribe(["m1", "m2"], ["book+"])
                await live.unsubscribe(["m2"])
                seen = []
                async for msg in live:
                    seen.append(msg)
                    if msg.get("conn") == 1:
                        break
            assert [m["conn"] for m in seen] == [0, 1]

    asyncio.run(main())
    assert got[1] == [{"op": "sub", "markets": ["m1"], "channels": ["book+"], "format": "json"}]
    assert len(gaps) == 1 and gaps[0][0] <= gaps[0][1]
