from __future__ import annotations

import os

import pytest

from liqpulse.backtest import run_backtest
from liqpulse.brief import build_brief, render_cards
from liqpulse.cards import generate_and_store, load_latest
from liqpulse.db import latest_snapshots, get_session_factory
from liqpulse.ingest.runner import run_ingest


def test_mock_ingest_persists(db_path):
    snaps, report = run_ingest(mode="mock", sources=["mock"], symbols=["BTC", "ETH", "SOL"])
    assert report.used_mock_fallback
    assert len(snaps) == 3
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        stored = latest_snapshots(session)
    assert {s.symbol for s in stored} == {"BTC", "ETH", "SOL"}


def test_latest_cards_dedupe_per_venue_symbol_type(db_path):
    snaps, _ = run_ingest(mode="mock")
    generate_and_store(snaps)
    generate_and_store(snaps)
    loaded = load_latest(50)
    keys = [(c.venue, c.symbol, c.card_type) for c in loaded]
    assert keys == list(dict.fromkeys(keys))


def test_cards_roundtrip(db_path):
    snaps, _ = run_ingest(mode="mock")
    cards = generate_and_store(snaps)
    assert cards
    assert all(c.features for c in cards)
    loaded = load_latest(20)
    assert loaded
    assert loaded[0].id is not None
    text = render_cards(loaded)
    assert "funding_8h" in text or "vol_expansion" in text
    brief = build_brief("morning", loaded)
    assert "Not financial advice" in brief


@pytest.mark.network
@pytest.mark.skipif(
    os.environ.get("CI") == "true" or os.environ.get("LIQPULSE_FEED", "").lower() == "mock",
    reason="CI / mock feed stays offline; no live venue calls",
)
def test_live_okx_or_fallback(db_path):
    snaps, report = run_ingest(mode="auto", sources=["okx"], symbols=["BTC"])
    assert snaps
    assert report.snapshot_count >= 1
    if "okx" in report.sources_ok:
        assert snaps[0].venue == "okx"
        assert snaps[0].mark_price and snaps[0].mark_price > 0
        assert snaps[0].last_funding is not None
    else:
        assert report.used_mock_fallback


def test_backtest_on_mock_tape(db_path):
    from datetime import datetime, timezone, timedelta

    from liqpulse.db import persist_snapshots, get_session_factory
    from liqpulse.ingest.mock import fetch_mock

    t0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    first = fetch_mock(["BTC"], ts=t0)
    second = fetch_mock(["BTC"], ts=t0 + timedelta(hours=8))
    second[0].mark_price = (first[0].mark_price or 0) * 1.01
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        persist_snapshots(session, first + second)
    result = run_backtest()
    assert result.notes
    assert result.trades
    assert result.trades[0].side == "short"
    assert result.trades[0].pnl < 0
