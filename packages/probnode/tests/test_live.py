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
