"""Transparent heuristics. Every weight is visible; nothing is a trained black box."""

from __future__ import annotations

import math
from typing import Iterable

from liqpulse.models import Feature, MarketSnapshot, OpportunityCard, utcnow

# 0.01% per 8h is the long-run "boring" perp funding print (~11% APR).
FUNDING_REF_8H = 0.0001
TYPICAL_RANGE_PCT = 4.0
CARRY_APR_TRIGGER = 0.15
CARRY_8H_TRIGGER = 0.0003
VOL_EXPANSION_TRIGGER = 1.30


def _tanh(x: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return math.tanh(x / scale)


def _pct_range(snap: MarketSnapshot) -> float | None:
    if snap.high_24h and snap.low_24h and snap.mark_price:
        mid = (snap.high_24h + snap.low_24h) / 2.0
        if mid > 0:
            return ((snap.high_24h - snap.low_24h) / mid) * 100.0
    if snap.change_24h_pct is not None:
        return abs(snap.change_24h_pct)
    return None


def _premium_bps(snap: MarketSnapshot) -> float | None:
    if snap.mark_price and snap.index_price and snap.index_price > 0:
        return ((snap.mark_price / snap.index_price) - 1.0) * 10_000.0
    extra = snap.extra or {}
    if extra.get("premium") is not None:
        try:
            return float(extra["premium"]) * 10_000.0
        except (TypeError, ValueError):
            return None
    return None


def _liq_imbalance(snap: MarketSnapshot) -> float | None:
    long_n = snap.liq_long_notional
    short_n = snap.liq_short_notional
    if long_n is None or short_n is None:
        return None
    denom = long_n + short_n
    if denom <= 0:
        return 0.0
    return (long_n - short_n) / denom


def _cross_venue_funding(symbol: str, snaps: Iterable[MarketSnapshot]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in snaps:
        if s.symbol != symbol:
            continue
        f8 = s.funding_8h()
        if f8 is None:
            continue
        out[s.venue] = f8
    return out


def build_features(
    snap: MarketSnapshot, universe: list[MarketSnapshot] | None = None
) -> list[Feature]:
    features: list[Feature] = []
    f8 = snap.funding_8h()
    apr = snap.funding_apr()
    if f8 is not None:
        features.append(
            Feature(
                name="funding_8h",
                value=f8,
                unit="rate",
                contribution=35.0 * _tanh(abs(f8), FUNDING_REF_8H * 4),
                note="Normalized to 8h so hourly venues compare with CEX prints.",
            )
        )
    if apr is not None:
        thin = abs(apr) > 5.0
        features.append(
            Feature(
                name="funding_apr",
                value=apr,
                unit="APR",
                contribution=20.0 * _tanh(abs(apr), 0.8),
                note=(
                    "Simple rate × periods/year. Not compounded. "
                    + ("Thin-book / check units — do not size this." if thin else "No edge claimed beyond the print.")
                ),
            )
        )
    prem = _premium_bps(snap)
    if prem is not None:
        features.append(
            Feature(
                name="premium_bps",
                value=prem,
                unit="bps",
                contribution=10.0 * _tanh(abs(prem), 15.0),
                note="Mark minus index, in basis points.",
            )
        )
    rng = _pct_range(snap)
    if rng is not None:
        expansion = rng / TYPICAL_RANGE_PCT
        features.append(
            Feature(
                name="range_24h_pct",
                value=rng,
                unit="%",
                contribution=0.0,
                note="High-low over mid (or |24h change| fallback).",
            )
        )
        features.append(
            Feature(
                name="vol_expansion",
                value=expansion,
                unit="x",
                contribution=18.0 * _tanh(max(expansion - 1.0, 0.0), 0.8),
                note=f"24h range vs a {TYPICAL_RANGE_PCT:.0f}% 'quiet day' reference.",
            )
        )
    if snap.change_24h_pct is not None:
        features.append(
            Feature(
                name="change_24h_pct",
                value=snap.change_24h_pct,
                unit="%",
                contribution=0.0,
                note="Spot/mark 24h percent change.",
            )
        )
    imb = _liq_imbalance(snap)
    if imb is not None:
        features.append(
            Feature(
                name="liq_imbalance",
                value=imb,
                unit="[-1,1]",
                contribution=16.0 * abs(imb),
                note="(long liqs − short liqs) / total. +1 = only longs blown out.",
            )
        )
    liq_tot = None
    if snap.liq_long_notional is not None and snap.liq_short_notional is not None:
        liq_tot = snap.liq_long_notional + snap.liq_short_notional
        features.append(
            Feature(
                name="liq_notional",
                value=liq_tot,
                unit="USD",
                contribution=8.0 * _tanh(liq_tot, 25_000_000.0),
                note="Recent public liquidation prints (venue-specific window).",
            )
        )
    if snap.long_short_ratio is not None:
        crowd = snap.long_short_ratio - 1.0
        features.append(
            Feature(
                name="long_short_ratio",
                value=snap.long_short_ratio,
                unit="x",
                contribution=10.0 * _tanh(abs(crowd), 0.6),
                note=">1 crowded long, <1 crowded short (account-ratio when available).",
            )
        )
    if snap.oi_notional and snap.volume_24h_notional and snap.volume_24h_notional > 0:
        oi_vol = snap.oi_notional / snap.volume_24h_notional
        features.append(
            Feature(
                name="oi_over_volume",
                value=oi_vol,
                unit="x",
                contribution=6.0 * _tanh(oi_vol, 2.0),
                note="Sticky OI vs 24h notional — a crowding proxy, not a forecast.",
            )
        )
    if snap.realized_vol_24h is not None:
        features.append(
            Feature(
                name="realized_vol",
                value=snap.realized_vol_24h,
                unit="ann.",
                contribution=8.0 * _tanh(snap.realized_vol_24h, 0.8),
                note="Hourly close-to-close σ, annualized. Small-sample.",
            )
        )
    if universe:
        book = _cross_venue_funding(snap.symbol, universe)
        if len(book) >= 2:
            spread = max(book.values()) - min(book.values())
            features.append(
                Feature(
                    name="funding_venue_dispersion",
                    value=spread,
                    unit="8h rate",
                    contribution=8.0 * _tanh(spread, 0.0008),
                    note="max−min 8h funding across venues in this ingest.",
                )
            )
    return features


def _feat(features: list[Feature], name: str) -> Feature | None:
    for f in features:
        if f.name == name:
            return f
    return None


def _clamp(score: float) -> float:
    return max(0.0, min(100.0, round(score, 1)))


def make_cards(snap: MarketSnapshot, universe: list[MarketSnapshot] | None = None) -> list[OpportunityCard]:
    features = build_features(snap, universe)
    cards: list[OpportunityCard] = []
    f8 = snap.funding_8h()
    apr = snap.funding_apr()
    imb = _liq_imbalance(snap)
    vol = _feat(features, "vol_expansion")
    ls = snap.long_short_ratio
    evidence = {
        "venue": snap.venue,
        "source": snap.source,
        "symbol": snap.symbol,
        "mark_price": snap.mark_price,
        "last_funding": snap.last_funding,
        "funding_period_hours": snap.funding_period_hours,
        "funding_8h": f8,
        "funding_apr": apr,
        "oi_notional": snap.oi_notional,
        "liq_long_notional": snap.liq_long_notional,
        "liq_short_notional": snap.liq_short_notional,
        "heuristic": "v1-transparent",
    }
    snap_id = snap.extra.get("id") if snap.extra else None

    carry_hit = False
    if f8 is not None and apr is not None:
        carry_hit = abs(apr) >= CARRY_APR_TRIGGER or abs(f8) >= CARRY_8H_TRIGGER
    if carry_hit and f8 is not None:
        side: str = "short" if f8 > 0 else "long"
        # Collect funding by sitting on the receiving side.
        score = 0.0
        for f in features:
            if f.name in {"funding_8h", "funding_apr", "premium_bps", "funding_venue_dispersion", "long_short_ratio"}:
                score += f.contribution
        if abs(apr or 0) > 5.0:
            score = min(score, 55.0)
            title = f"{snap.symbol} {snap.venue} thin-book carry flag"
            thesis = (
                f"Reported funding annualizes to {apr:.0%} on {snap.venue}. "
                f"That is almost certainly a thin Solana/DEX book or a unit quirk — "
                f"logged as evidence, not a trade. Receiving side would be {side}."
            )
        else:
            title = f"{snap.symbol} {snap.venue} funding carry"
            thesis = (
                f"8h funding is {f8:.4%} ({apr:.1%} simple APR). "
                f"Positive funding means longs pay shorts. Paper bias: {side} to collect. "
                f"This is a heuristic on a public print, not a forecast."
            )
        cards.append(
            OpportunityCard(
                ts=snap.ts or utcnow(),
                venue=snap.venue,
                symbol=snap.symbol,
                card_type="carry",
                title=title,
                thesis=thesis,
                side_bias=side,  # type: ignore[arg-type]
                score=_clamp(score if score else 25.0),
                features=features,
                evidence=evidence,
                snapshot_id=snap_id,
            )
        )

    squeeze_hit = False
    vol_x = vol.value if vol else 0.0
    crowded_long = (ls is not None and ls >= 1.25) or (f8 is not None and f8 >= FUNDING_REF_8H)
    crowded_short = (ls is not None and ls <= 0.80) or (f8 is not None and f8 <= -FUNDING_REF_8H)
    cascade_down = False
    squeeze_up = False
    if vol_x >= VOL_EXPANSION_TRIGGER:
        if (imb is not None and imb > 0.15 and (snap.change_24h_pct or 0) < 0) or (
            crowded_long and (snap.change_24h_pct or 0) < -1.5
        ):
            cascade_down = True
        if (imb is not None and imb < -0.15 and (snap.change_24h_pct or 0) > 0) or (
            crowded_short and (snap.change_24h_pct or 0) > 1.5
        ):
            squeeze_up = True
    if imb is not None and abs(imb) > 0.35 and (vol_x >= 1.0 or abs(snap.change_24h_pct or 0) >= 2.0):
        if imb > 0:
            cascade_down = True
        else:
            squeeze_up = True
    squeeze_hit = cascade_down or squeeze_up
    if squeeze_hit:
        side = "short" if cascade_down and not squeeze_up else "long" if squeeze_up and not cascade_down else "neutral"
        score = 0.0
        for f in features:
            if f.name in {"vol_expansion", "liq_imbalance", "liq_notional", "long_short_ratio", "realized_vol"}:
                score += f.contribution
        if cascade_down and squeeze_up:
            thesis = (
                f"{snap.symbol} on {snap.venue} is two-way violent: vol expanded and both "
                f"liquidation sides are active. No directional paper bias."
            )
            title = f"{snap.symbol} {snap.venue} two-way squeeze risk"
        elif cascade_down:
            thesis = (
                f"Vol expansion {vol_x:.2f}× with long-liq pressure "
                f"(imbalance {imb if imb is not None else 'n/a'}). "
                f"Crowded-long unwind proxy — paper bias short, fade-the-cascade, not a market order."
            )
            title = f"{snap.symbol} {snap.venue} long-liq cascade risk"
        else:
            thesis = (
                f"Vol expansion {vol_x:.2f}× with short-liq pressure. "
                f"Squeeze-up proxy — paper bias long. Public prints only."
            )
            title = f"{snap.symbol} {snap.venue} short-squeeze risk"
        cards.append(
            OpportunityCard(
                ts=snap.ts or utcnow(),
                venue=snap.venue,
                symbol=snap.symbol,
                card_type="squeeze_risk",
                title=title,
                thesis=thesis,
                side_bias=side,  # type: ignore[arg-type]
                score=_clamp(score if score else 28.0),
                features=features,
                evidence=evidence,
                snapshot_id=snap_id,
            )
        )
    return cards


def score_universe(snaps: list[MarketSnapshot]) -> list[OpportunityCard]:
    cards: list[OpportunityCard] = []
    for snap in snaps:
        cards.extend(make_cards(snap, snaps))
    cards.sort(key=lambda c: c.score, reverse=True)
    return cards
