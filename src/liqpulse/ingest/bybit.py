from __future__ import annotations

from datetime import datetime, timezone

import httpx

from liqpulse.ingest.http import client, fnum, get_json
from liqpulse.models import MarketSnapshot

BASE = "https://api.bybit.com"
SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


def fetch_bybit(symbols: list[str]) -> list[MarketSnapshot]:
    now = datetime.now(timezone.utc)
    snaps: list[MarketSnapshot] = []
    with client() as c:
        for symbol in symbols:
            inst = SYMBOL_MAP.get(symbol)
            if not inst:
                continue
            tickers = get_json(c, f"{BASE}/v5/market/tickers", {"category": "linear", "symbol": inst})
            lst = (tickers.get("result") or {}).get("list") or []
            if not lst:
                raise RuntimeError(f"bybit empty ticker for {inst}")
            t = lst[0]
            mark = fnum(t.get("markPrice"))
            index = fnum(t.get("indexPrice"))
            last = fnum(t.get("lastPrice")) or mark
            funding = fnum(t.get("fundingRate"))
            oi = fnum(t.get("openInterest"))
            oi_value = fnum(t.get("openInterestValue"))
            if oi_value is None and oi and last:
                oi_value = oi * last
            next_funding = None
            nft = fnum(t.get("nextFundingTime"))
            if nft:
                # Bybit returns ms
                if nft > 1e12:
                    next_funding = datetime.fromtimestamp(nft / 1000.0, tz=timezone.utc)
                else:
                    next_funding = datetime.fromtimestamp(nft, tz=timezone.utc)
            rvol = None
            try:
                kl = get_json(
                    c,
                    f"{BASE}/v5/market/kline",
                    {"category": "linear", "symbol": inst, "interval": "60", "limit": 24},
                )
                rows = (kl.get("result") or {}).get("list") or []
                closes: list[float] = []
                for row in reversed(rows):
                    px = fnum(row[4])
                    if px:
                        closes.append(px)
                if len(closes) >= 8:
                    rets = [(closes[i] / closes[i - 1]) - 1.0 for i in range(1, len(closes))]
                    mean = sum(rets) / len(rets)
                    var = sum((x - mean) ** 2 for x in rets) / max(len(rets) - 1, 1)
                    rvol = (var**0.5) * (24**0.5) * (365**0.5)
            except httpx.HTTPError:
                pass
            snaps.append(
                MarketSnapshot(
                    ts=now,
                    venue="bybit",
                    source="bybit_v5",
                    symbol=symbol,
                    mark_price=mark,
                    index_price=index,
                    last_funding=funding,
                    funding_period_hours=8.0,
                    next_funding_ts=next_funding,
                    open_interest=oi,
                    oi_notional=oi_value,
                    volume_24h_notional=fnum(t.get("turnover24h")),
                    high_24h=fnum(t.get("highPrice24h")),
                    low_24h=fnum(t.get("lowPrice24h")),
                    change_24h_pct=fnum(t.get("price24hPcnt")),
                    realized_vol_24h=rvol,
                    extra={"instrument": inst},
                )
            )
    return snaps
