from __future__ import annotations

from liqpulse.ledger import close_position, mark_positions, open_position, status, write_journal


def test_open_mark_close_pnl(db_path):
    pos = open_position("BTC", "long", qty=0.1, price=100_000, venue="okx", note="unit")
    assert pos.id >= 1
    view = status()
    assert view.open_count == 1
    assert view.cash == 100_000 - 10_000
    assert abs(view.equity - 100_000) < 1e-6
    assert abs(view.unrealized_pnl) < 1e-9

    marked = mark_positions({"BTC": 110_000})
    assert marked.positions[0].unrealized_pnl == 1_000.0
    assert marked.equity == 100_000 + 1_000

    pnl = close_position(pos.id, price=110_000)
    assert pnl == 1_000.0
    done = status()
    assert done.open_count == 0
    assert done.realized_pnl == 1_000.0
    assert abs(done.cash - 101_000) < 1e-6
    assert abs(done.equity - 101_000) < 1e-6


def test_short_pnl(db_path):
    pos = open_position("ETH", "short", qty=2, price=2_000, venue="mock")
    close = close_position(pos.id, price=1_800)
    assert close == 400.0
    assert status().realized_pnl == 400.0


def test_rejects_oversize(db_path):
    try:
        open_position("BTC", "long", qty=10, price=100_000)
        assert False, "should reject"
    except ValueError as exc:
        assert "cash" in str(exc)


def test_journal_writes(db_path):
    jid = write_journal("morning", "hello", {"k": 1})
    assert jid >= 1
