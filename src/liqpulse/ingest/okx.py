from __future__ import annotations

from datetime import datetime, timezone

import httpx

from liqpulse.ingest.http import client, fnum, get_json
from liqpulse.models import MarketSnapshot

BASE = "https://www.okx.com"
SYMBOL_MAP = {"BTC": "BTC-USDT-SWAP", "ETH": "ETH-USDT-SWAP", "SOL": "SOL-USDT-SWAP"}
DEFAULT_CTVAL = {"BTC": 0.01, "ETH": 0.1, "SOL": 1.0}


def _okx_data(payload: dict) -> list:
    if str(payload.get("code")) not in {"0", "00"}:
        raise RuntimeError(payload.get("msg") or "okx error")
    return payload.get("data") or []


def _ctval(c: httpx.Client, inst: str, symbol: str) -> float:
    try:
        payload = get_json(c, f"{BASE}/api/v5/public/instruments", {"instType": "SWAP", "instId": inst})
        rows = _okx_data(payload)
        if rows:
            return fnum(rows[0].get("ctVal")) or DEFAULT_CTVAL.get(symbol, 1.0)
    except (httpx.HTTPError, RuntimeError, TypeError):
        pass
    return DEFAULT_CTVAL.get(symbol, 1.0)


def _liq(c: httpx.Client, inst: str, uly: str, ctval: float) -> tuple[float, float]:
    payload = get_json(
        c,
        f"{BASE}/api/v5/public/liquidation-orders",
        {"instType": "SWAP", "uly": uly, "state": "filled", "limit": 50},
    )
    rows = _okx_data(payload)
    long_n = short_n = 0.0
    cutoff = datetime.now(timezone.utc).timestamp() * 1000 - 2 * 3600 * 1000
    for block in rows:
        for d in block.get("details") or []:
            ts = fnum(d.get("ts") or d.get("time")) or 0.0
            if ts < cutoff:
                continue
            sz = fnum(d.get("sz")) or 0.0
            px = fnum(d.get("bkPx")) or 0.0
            notional = sz * px * ctval
            pos = str(d.get("posSide", "")).lower()
            if pos == "long":
                long_n += notional
            elif pos == "short":
                short_n += notional
    return long_n, short_n


def _ls_ratio(c: httpx.Client, symbol: str) -> float | None:
    try:
        payload = get_json(
            c,
            f"{BASE}/api/v5/rubik/stat/contracts/long-short-account-ratio",
            {"ccy": symbol, "period": "1H"},
        )
        rows = _okx_data(payload)
        if rows:
            return fnum(rows[0][1])
    except (httpx.HTTPError, RuntimeError, IndexError, TypeError):
        return None
    return None


def _rvol(c: httpx.Client, inst: str) -> float | None:
    try:
        payload = get_json(c, f"{BASE}/api/v5/market/candles", {"instId": inst, "bar": "1H", "limit": 24})
        rows = _okx_data(payload)
        closes: list[float] = []
        for row in reversed(rows):
            px = fnum(row[4])
            if px:
                closes.append(px)
        if len(closes) < 8:
            return None
        rets = [(closes[i] / closes[i - 1]) - 1.0 for i in range(1, len(closes))]
        mean = sum(rets) / len(rets)
        var = sum((x - mean) ** 2 for x in rets) / max(len(rets) - 1, 1)
        return (var**0.5) * (24**0.5) * (365**0.5)
    except (httpx.HTTPError, RuntimeError):
        return None


def fetch_okx(symbols: list[str]) -> list[MarketSnapshot]:
    now = datetime.now(timezone.utc)
    snaps: list[MarketSnapshot] = []
    with client() as c:
        for symbol in symbols:
            inst = SYMBOL_MAP.get(symbol)
            if not inst:
                continue
            uly = inst.replace("-SWAP", "")
            funding_rows = _okx_data(get_json(c, f"{BASE}/api/v5/public/funding-rate", {"instId": inst}))
            ticker_rows = _okx_data(get_json(c, f"{BASE}/api/v5/market/ticker", {"instId": inst}))
            oi_rows = _okx_data(get_json(c, f"{BASE}/api/v5/public/open-interest", {"instId": inst}))
            if not funding_rows or not ticker_rows:
                raise RuntimeError(f"okx missing core data for {inst}")
            f = funding_rows[0]
            t = ticker_rows[0]
            oi = oi_rows[0] if oi_rows else {}
            mark = fnum(t.get("last"))
            high = fnum(t.get("high24h"))
            low = fnum(t.get("low24h"))
            open24 = fnum(t.get("open24h"))
            chg = None
            if open24 and mark and open24 > 0:
                chg = ((mark / open24) - 1.0) * 100.0
            ctval = _ctval(c, inst, symbol)
            liq_long = liq_short = None
            try:
                liq_long, liq_short = _liq(c, inst, uly, ctval)
            except (httpx.HTTPError, RuntimeError):
                pass
            next_funding = None
            nft = fnum(f.get("nextFundingTime"))
            if nft:
                next_funding = datetime.fromtimestamp(nft / 1000.0, tz=timezone.utc)
            snaps.append(
                MarketSnapshot(
                    ts=now,
                    venue="okx",
                    source="okx_public",
                    symbol=symbol,
                    mark_price=mark,
                    index_price=None,
                    last_funding=fnum(f.get("fundingRate")),
                    funding_period_hours=8.0,
                    next_funding_ts=next_funding,
                    open_interest=fnum(oi.get("oiCcy")),
                    oi_notional=fnum(oi.get("oiUsd")),
                    volume_24h_notional=(
                        (fnum(t.get("volCcy24h")) or 0.0) * mark if mark and fnum(t.get("volCcy24h")) else None
                    ),
                    high_24h=high,
                    low_24h=low,
                    change_24h_pct=chg,
                    liq_long_notional=liq_long,
                    liq_short_notional=liq_short,
                    long_short_ratio=_ls_ratio(c, symbol),
                    realized_vol_24h=_rvol(c, inst),
                    extra={
                        "instrument": inst,
                        "premium": fnum(f.get("premium")),
                        "interest_rate": fnum(f.get("interestRate")),
                    },
                )
            )
    return snaps
