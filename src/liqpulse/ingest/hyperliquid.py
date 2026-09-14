from __future__ import annotations

from datetime import datetime, timezone

from liqpulse.ingest.http import client, fnum, post_json
from liqpulse.models import MarketSnapshot

INFO = "https://api.hyperliquid.xyz/info"
WANTED = {"BTC", "ETH", "SOL"}


def fetch_hyperliquid(symbols: list[str]) -> list[MarketSnapshot]:
    now = datetime.now(timezone.utc)
    want = {s.upper() for s in symbols}
    snaps: list[MarketSnapshot] = []
    with client() as c:
        meta, ctxs = post_json(c, INFO, {"type": "metaAndAssetCtxs"})
        universe = meta.get("universe") or []
        predicted = {}
        try:
            raw = post_json(c, INFO, {"type": "predictedFundings"})
            for coin, venues in raw:
                predicted[str(coin)] = {name: payload for name, payload in venues}
        except Exception:
            predicted = {}

        for i, asset in enumerate(universe):
            name = str(asset.get("name", "")).upper()
            if name not in want or name not in WANTED:
                continue
            if i >= len(ctxs):
                continue
            ctx = ctxs[i]
            mark = fnum(ctx.get("markPx"))
            oracle = fnum(ctx.get("oraclePx"))
            prev = fnum(ctx.get("prevDayPx"))
            chg = None
            if prev and mark and prev > 0:
                chg = ((mark / prev) - 1.0) * 100.0
            oi = fnum(ctx.get("openInterest"))
            pred = predicted.get(name, {})
            hl = pred.get("HlPerp") or {}
            period = fnum(hl.get("fundingIntervalHours")) or 1.0
            extra = {
                "predicted": {
                    k: {
                        "fundingRate": fnum((v or {}).get("fundingRate")),
                        "interval_hours": fnum((v or {}).get("fundingIntervalHours")),
                    }
                    for k, v in pred.items()
                    if isinstance(v, dict)
                }
            }
            snaps.append(
                MarketSnapshot(
                    ts=now,
                    venue="hyperliquid",
                    source="hyperliquid_info",
                    symbol=name,
                    mark_price=mark,
                    index_price=oracle,
                    last_funding=fnum(ctx.get("funding")),
                    funding_period_hours=period,
                    open_interest=oi,
                    oi_notional=(oi * mark) if oi and mark else None,
                    volume_24h_notional=fnum(ctx.get("dayNtlVlm")),
                    change_24h_pct=chg,
                    extra=extra,
                )
            )
    if not snaps:
        raise RuntimeError("hyperliquid returned no requested symbols")
    return snaps
