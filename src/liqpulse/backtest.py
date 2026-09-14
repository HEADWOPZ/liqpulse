"""Replay stored snapshots. Tiny, honest, no walk-forward claim."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from liqpulse.db import all_snapshots, get_session_factory, init_db
from liqpulse.features.scoring import CARRY_8H_TRIGGER, score_universe
from liqpulse.models import MarketSnapshot


@dataclass
class Trade:
    ts: str
    symbol: str
    venue: str
    side: str
    qty: float
    entry: float
    exit: float
    pnl: float
    reason: str


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    starting_cash: float = 100_000.0
    ending_equity: float = 100_000.0
    notes: str = ""

    @property
    def pnl(self) -> float:
        return self.ending_equity - self.starting_cash


def _group(snaps: list[MarketSnapshot]) -> dict[tuple[str, str], list[MarketSnapshot]]:
    book: dict[tuple[str, str], list[MarketSnapshot]] = defaultdict(list)
    for s in snaps:
        book[(s.venue, s.symbol)].append(s)
    for key in book:
        book[key].sort(key=lambda s: s.ts)
    return book


def run_backtest(notional: float = 1_000.0, starting_cash: float = 100_000.0) -> BacktestResult:
    """
    Rule: if a carry card fires and |funding_8h| >= trigger, hold one snapshot
    interval on the receiving side. PnL = mark change only (funding is *not*
    double-counted as cash). This is a tape replay, not a research edge.
    """
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        snaps = all_snapshots(session, limit=5000)
    result = BacktestResult(starting_cash=starting_cash, ending_equity=starting_cash)
    if len(snaps) < 2:
        result.notes = "Need at least two stored snapshots. Run `liqpulse ingest` a couple of times first."
        return result

    cash = starting_cash
    trades: list[Trade] = []
    grouped = _group(snaps)
    for (_venue, _symbol), series in grouped.items():
        if len(series) < 2:
            continue
        for i in range(len(series) - 1):
            cur, nxt = series[i], series[i + 1]
            if not cur.mark_price or not nxt.mark_price:
                continue
            cards = score_universe([cur])
            carry = next((c for c in cards if c.card_type == "carry" and c.side_bias in {"long", "short"}), None)
            f8 = cur.funding_8h()
            if carry is None or f8 is None or abs(f8) < CARRY_8H_TRIGGER:
                continue
            qty = notional / cur.mark_price
            sign = 1.0 if carry.side_bias == "long" else -1.0
            pnl = (nxt.mark_price - cur.mark_price) * qty * sign
            cash += pnl
            trades.append(
                Trade(
                    ts=cur.ts.isoformat(),
                    symbol=cur.symbol,
                    venue=cur.venue,
                    side=carry.side_bias,
                    qty=qty,
                    entry=cur.mark_price,
                    exit=nxt.mark_price,
                    pnl=pnl,
                    reason=carry.title,
                )
            )
    result.trades = trades
    result.ending_equity = cash
    result.notes = (
        f"{len(trades)} paper fills over {len(snaps)} snapshots. "
        "Mark-to-mark only; no fees, no slippage, no funding cash. Not a performance claim."
    )
    return result


def render_backtest(result: BacktestResult) -> str:
    lines = [
        "# LiqPulse snapshot replay",
        result.notes,
        f"starting {result.starting_cash:,.2f}  ending {result.ending_equity:,.2f}  pnl {result.pnl:,.2f}",
        "",
    ]
    for t in result.trades[:40]:
        lines.append(
            f"{t.ts} {t.venue:12s} {t.side:5s} {t.symbol}  {t.entry:.4g} → {t.exit:.4g}  pnl {t.pnl:,.2f}"
        )
    if not result.trades:
        lines.append("(no carry triggers between consecutive snapshots)")
    return "\n".join(lines)
