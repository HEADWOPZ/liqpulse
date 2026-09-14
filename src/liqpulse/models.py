from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

Side = Literal["long", "short"]
CardType = Literal["carry", "squeeze_risk"]
FeedMode = Literal["mock", "live", "auto"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Feature(BaseModel):
    name: str
    value: float
    unit: str = ""
    contribution: float = 0.0
    note: str = ""


class MarketSnapshot(BaseModel):
    ts: datetime
    venue: str
    source: str
    symbol: str
    mark_price: float | None = None
    index_price: float | None = None
    last_funding: float | None = None
    funding_period_hours: float = 8.0
    next_funding_ts: datetime | None = None
    open_interest: float | None = None
    oi_notional: float | None = None
    volume_24h_notional: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    change_24h_pct: float | None = None
    liq_long_notional: float | None = None
    liq_short_notional: float | None = None
    long_short_ratio: float | None = None
    realized_vol_24h: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def funding_8h(self) -> float | None:
        if self.last_funding is None:
            return None
        return self.last_funding * (8.0 / self.funding_period_hours)

    def funding_apr(self) -> float | None:
        if self.last_funding is None:
            return None
        periods = (24.0 / self.funding_period_hours) * 365.0
        return self.last_funding * periods


class OpportunityCard(BaseModel):
    ts: datetime
    venue: str
    symbol: str
    card_type: CardType
    title: str
    thesis: str
    side_bias: Literal["long", "short", "neutral"]
    score: float
    horizon: str = "8h-24h"
    features: list[Feature] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    snapshot_id: int | None = None
    id: int | None = None


class PositionView(BaseModel):
    id: int
    symbol: str
    venue: str
    side: Side
    qty: float
    entry_price: float
    mark_price: float
    notional: float
    unrealized_pnl: float
    opened_at: datetime
    note: str = ""
    card_id: int | None = None


class LedgerView(BaseModel):
    cash: float
    starting_cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    open_count: int
    positions: list[PositionView] = Field(default_factory=list)


class IngestReport(BaseModel):
    mode: str
    sources_attempted: list[str]
    sources_ok: list[str]
    sources_failed: dict[str, str]
    snapshot_count: int
    used_mock_fallback: bool = False
