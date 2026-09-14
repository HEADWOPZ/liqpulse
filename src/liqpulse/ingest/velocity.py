from __future__ import annotations

from datetime import datetime, timezone

from liqpulse.ingest.http import client, fnum, get_json
from liqpulse.models import MarketSnapshot

# Public Solana-perps stats (Velocity / Drift successor). No API key.
STATS = "https://data.velocity.exchange/stats/markets"
SYMBOL_MAP = {"BTC": "BTC-PERP", "ETH": "ETH-PERP", "SOL": "SOL-PERP"}


def fetch_velocity(symbols: list[str]) -> list[MarketSnapshot]:
    now = datetime.now(timezone.utc)
    with client() as c:
        payload = get_json(c, STATS)
    markets = payload.get("markets") if isinstance(payload, dict) else payload
    if not isinstance(markets, list):
        raise RuntimeError("velocity stats/markets: unexpected shape")
    by_symbol = {str(m.get("symbol")): m for m in markets}
    snaps: list[MarketSnapshot] = []
    for symbol in symbols:
        inst = SYMBOL_MAP.get(symbol)
        m = by_symbol.get(inst) if inst else None
        if not m or str(m.get("marketType", "")).lower() != "perp":
            continue
        mark = fnum(m.get("markPrice"))
        oracle = fnum(m.get("oraclePrice"))
        funding = m.get("fundingRate") or {}
        # Protocol reports signed long-side rate. Positive => longs pay shorts.
        last_funding = fnum(funding.get("long")) if isinstance(funding, dict) else fnum(funding)
        oi = m.get("openInterest") or {}
        oi_long = abs(fnum(oi.get("long")) or 0.0) if isinstance(oi, dict) else fnum(oi) or 0.0
        oi_short = abs(fnum(oi.get("short")) or 0.0) if isinstance(oi, dict) else 0.0
        oi_base = oi_long + oi_short
        high = None
        low = None
        ph = m.get("priceHigh") or {}
        pl = m.get("priceLow") or {}
        if isinstance(ph, dict):
            high = fnum(ph.get("oracle") or ph.get("fill"))
        if isinstance(pl, dict):
            low = fnum(pl.get("oracle") or pl.get("fill"))
        chg = fnum(m.get("priceChange24hPercent"))
        quote_vol = fnum(m.get("quoteVolume"))
        ls = (oi_long / oi_short) if oi_short > 0 else None
        snaps.append(
            MarketSnapshot(
                ts=now,
                venue="velocity",
                source="velocity_data_api",
                symbol=symbol,
                mark_price=mark,
                index_price=oracle,
                last_funding=last_funding,
                funding_period_hours=1.0,  # Velocity/Drift-style hourly funding
                open_interest=oi_base,
                oi_notional=(oi_base * mark) if mark else None,
                volume_24h_notional=quote_vol,
                high_24h=high,
                low_24h=low,
                change_24h_pct=chg,
                long_short_ratio=ls,
                extra={
                    "instrument": inst,
                    "oi_long": oi_long,
                    "oi_short": oi_short,
                    "funding_short": fnum(funding.get("short")) if isinstance(funding, dict) else None,
                    "thin_book": True,
                    "note": "Solana-perps proxy. Books are thin vs CEX; treat size as illustrative.",
                },
            )
        )
    if not snaps:
        raise RuntimeError("velocity returned no requested perp markets")
    return snaps
