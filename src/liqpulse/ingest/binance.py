from __future__ import annotations

from datetime import datetime, timezone

import httpx

from liqpulse.ingest.http import client, fnum, get_json
from liqpulse.models import MarketSnapshot

BASE = "https://fapi.binance.com"

SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


def _realized_vol(klines: list) -> float | None:
    if not klines or len(klines) < 8:
        return None
    rets: list[float] = []
    prev = None
    for k in klines:
        close = fnum(k[4])
        if close is None or close <= 0:
            continue
        if prev is not None and prev > 0:
            rets.append((close / prev) - 1.0)
        prev = close
    if len(rets) < 6:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    hourly = var**0.5
    return hourly * (24**0.5) * (365**0.5)


def _liq_notionals(orders: list, hours: float = 1.5) -> tuple[float, float]:
    cutoff_ms = datetime.now(timezone.utc).timestamp() * 1000 - hours * 3600 * 1000
    long_n = 0.0
    short_n = 0.0
    for o in orders:
        ts = fnum(o.get("time")) or 0.0
        if ts < cutoff_ms:
            continue
        qty = fnum(o.get("origQty")) or 0.0
        px = fnum(o.get("averagePrice") or o.get("price")) or 0.0
        notional = qty * px
        side = str(o.get("side", "")).upper()
        # BUY force order liquidates shorts; SELL liquidates longs.
        if side == "BUY":
            short_n += notional
        else:
            long_n += notional
    return long_n, short_n


def fetch_binance(symbols: list[str]) -> list[MarketSnapshot]:
    now = datetime.now(timezone.utc)
    snaps: list[MarketSnapshot] = []
    with client() as c:
        for symbol in symbols:
            inst = SYMBOL_MAP.get(symbol)
            if not inst:
                continue
            premium = get_json(c, f"{BASE}/fapi/v1/premiumIndex", {"symbol": inst})
            ticker = get_json(c, f"{BASE}/fapi/v1/ticker/24hr", {"symbol": inst})
            oi = get_json(c, f"{BASE}/fapi/v1/openInterest", {"symbol": inst})
            mark = fnum(premium.get("markPrice"))
            last = fnum(ticker.get("lastPrice")) or mark
            open_interest = fnum(oi.get("openInterest"))
            liq_long = liq_short = None
            try:
                orders = get_json(c, f"{BASE}/fapi/v1/allForceOrders", {"symbol": inst, "limit": 50})
                if isinstance(orders, list):
                    liq_long, liq_short = _liq_notionals(orders)
            except httpx.HTTPError:
                pass
            rvol = None
            try:
                klines = get_json(
                    c, f"{BASE}/fapi/v1/klines", {"symbol": inst, "interval": "1h", "limit": 24}
                )
                rvol = _realized_vol(klines)
            except httpx.HTTPError:
                pass
            next_funding = None
            nft = fnum(premium.get("nextFundingTime"))
            if nft:
                next_funding = datetime.fromtimestamp(nft / 1000.0, tz=timezone.utc)
            snaps.append(
                MarketSnapshot(
                    ts=now,
                    venue="binance",
                    source="binance_fapi",
                    symbol=symbol,
                    mark_price=mark,
                    index_price=fnum(premium.get("indexPrice")),
                    last_funding=fnum(premium.get("lastFundingRate")),
                    funding_period_hours=8.0,
                    next_funding_ts=next_funding,
                    open_interest=open_interest,
                    oi_notional=(open_interest * last) if open_interest and last else None,
                    volume_24h_notional=fnum(ticker.get("quoteVolume")),
                    high_24h=fnum(ticker.get("highPrice")),
                    low_24h=fnum(ticker.get("lowPrice")),
                    change_24h_pct=fnum(ticker.get("priceChangePercent")),
                    liq_long_notional=liq_long,
                    liq_short_notional=liq_short,
                    realized_vol_24h=rvol,
                    extra={"instrument": inst},
                )
            )
    return snaps
