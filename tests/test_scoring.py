from __future__ import annotations

from datetime import datetime, timezone

from liqpulse.features.scoring import build_features, make_cards, score_universe
from liqpulse.ingest.mock import fetch_mock
from liqpulse.models import MarketSnapshot


def _snap(**kwargs) -> MarketSnapshot:
    base = dict(
        ts=datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc),
        venue="test",
        source="unit",
        symbol="BTC",
        mark_price=80_000.0,
        index_price=80_000.0,
        last_funding=0.0001,
        funding_period_hours=8.0,
        open_interest=10_000.0,
        oi_notional=800_000_000.0,
        volume_24h_notional=1_000_000_000.0,
        high_24h=81_000.0,
        low_24h=79_000.0,
        change_24h_pct=0.5,
        liq_long_notional=1_000_000.0,
        liq_short_notional=1_000_000.0,
        long_short_ratio=1.0,
        realized_vol_24h=0.4,
        extra={},
    )
    base.update(kwargs)
    return MarketSnapshot(**base)


def test_funding_normalization_hourly_vs_eight_hour():
    eight = _snap(last_funding=0.0008, funding_period_hours=8.0)
    hourly = _snap(last_funding=0.0001, funding_period_hours=1.0)
    assert abs(eight.funding_8h() - 0.0008) < 1e-12
    assert abs(hourly.funding_8h() - 0.0008) < 1e-12
    assert abs(eight.funding_apr() - hourly.funding_apr()) < 1e-12


def test_positive_funding_creates_short_carry_card():
    snap = _snap(last_funding=0.0009, change_24h_pct=0.2)
    cards = make_cards(snap)
    carry = [c for c in cards if c.card_type == "carry"]
    assert carry
    assert carry[0].side_bias == "short"
    names = {f.name for f in carry[0].features}
    assert "funding_8h" in names
    assert "funding_apr" in names
    assert carry[0].score > 0


def test_negative_funding_creates_long_carry_card():
    snap = _snap(last_funding=-0.0007)
    cards = make_cards(snap)
    carry = [c for c in cards if c.card_type == "carry"]
    assert carry[0].side_bias == "long"


def test_long_liq_cascade_squeeze_card():
    snap = _snap(
        last_funding=0.00005,
        high_24h=82_000,
        low_24h=74_000,
        change_24h_pct=-4.2,
        liq_long_notional=40_000_000,
        liq_short_notional=4_000_000,
        long_short_ratio=1.5,
    )
    cards = make_cards(snap)
    sq = [c for c in cards if c.card_type == "squeeze_risk"]
    assert sq
    assert sq[0].side_bias == "short"
    imb = next(f for f in sq[0].features if f.name == "liq_imbalance")
    assert imb.value > 0.5


def test_quiet_market_has_no_cards():
    snap = _snap(
        last_funding=0.00005,
        high_24h=80_200,
        low_24h=79_800,
        change_24h_pct=0.1,
        liq_long_notional=100_000,
        liq_short_notional=110_000,
        long_short_ratio=1.02,
    )
    assert make_cards(snap) == []


def test_feature_contributions_are_finite():
    for snap in fetch_mock(["BTC", "ETH", "SOL"]):
        feats = build_features(snap)
        assert feats
        for f in feats:
            assert f.contribution == f.contribution  # not NaN
            assert f.contribution >= 0


def test_score_universe_orders_by_score():
    snaps = fetch_mock(["BTC", "ETH", "SOL"])
    cards = score_universe(snaps)
    assert cards
    scores = [c.score for c in cards]
    assert scores == sorted(scores, reverse=True)


def test_thin_book_apr_is_capped_and_flagged():
    snap = _snap(venue="velocity", last_funding=-0.005, funding_period_hours=1.0)
    cards = make_cards(snap)
    carry = next(c for c in cards if c.card_type == "carry")
    assert carry.score <= 55.0
    assert "thin" in carry.thesis.lower()
