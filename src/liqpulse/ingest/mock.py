from __future__ import annotations

from datetime import datetime, timezone

from liqpulse.models import MarketSnapshot

# Deterministic paper tape so tests and first-run demos are stable.
# Values are illustrative, not a historical backfill.
MOCK_BOOK: dict[str, dict] = {
    "BTC": {
        "mark": 78_670.0,
        "index": 78_704.0,
        "funding": 0.00048,
        "period": 8.0,
        "oi": 26_400.0,
        "vol": 2.15e9,
        "high": 78_871.0,
        "low": 76_323.0,
        "chg": 1.89,
        "liq_long": 18.4e6,
        "liq_short": 6.1e6,
        "ls": 1.32,
        "rvol": 0.42,
    },
    "ETH": {
        "mark": 2_523.4,
        "index": 2_523.2,
        "funding": -0.00021,
        "period": 8.0,
        "oi": 410_000.0,
        "vol": 1.38e9,
        "high": 2_548.0,
        "low": 2_401.0,
        "chg": -3.4,
        "liq_long": 42.0e6,
        "liq_short": 9.5e6,
        "ls": 1.61,
        "rvol": 0.58,
    },
    "SOL": {
        "mark": 102.47,
        "index": 102.52,
        "funding": 0.00095,
        "period": 8.0,
        "oi": 5.3e6,
        "vol": 1.41e8,
        "high": 108.2,
        "low": 96.4,
        "chg": 4.8,
        "liq_long": 4.2e6,
        "liq_short": 11.8e6,
        "ls": 0.78,
        "rvol": 0.71,
    },
}


def fetch_mock(symbols: list[str], ts: datetime | None = None) -> list[MarketSnapshot]:
    now = ts or datetime.now(timezone.utc)
    out: list[MarketSnapshot] = []
    for symbol in symbols:
        row = MOCK_BOOK.get(symbol)
        if row is None:
            continue
        mark = row["mark"]
        oi = row["oi"]
        out.append(
            MarketSnapshot(
                ts=now,
                venue="mock",
                source="mock",
                symbol=symbol,
                mark_price=mark,
                index_price=row["index"],
                last_funding=row["funding"],
                funding_period_hours=row["period"],
                open_interest=oi,
                oi_notional=oi * mark,
                volume_24h_notional=row["vol"],
                high_24h=row["high"],
                low_24h=row["low"],
                change_24h_pct=row["chg"],
                liq_long_notional=row["liq_long"],
                liq_short_notional=row["liq_short"],
                long_short_ratio=row["ls"],
                realized_vol_24h=row["rvol"],
                extra={"fixture": True},
            )
        )
    return out
