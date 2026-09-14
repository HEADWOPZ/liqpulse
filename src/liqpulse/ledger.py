from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from liqpulse.config import get_settings
from liqpulse.db import AccountRow, JournalRow, PositionRow, get_session_factory, init_db
from liqpulse.models import LedgerView, PositionView, utcnow


def _signed_pnl(side: str, qty: float, entry: float, exit_px: float) -> float:
    sign = 1.0 if side == "long" else -1.0
    return (exit_px - entry) * qty * sign


def _position_view(row: PositionRow) -> PositionView:
    pnl = _signed_pnl(row.side, row.qty, row.entry_price, row.mark_price)
    return PositionView(
        id=row.id,
        symbol=row.symbol,
        venue=row.venue,
        side=row.side,  # type: ignore[arg-type]
        qty=row.qty,
        entry_price=row.entry_price,
        mark_price=row.mark_price,
        notional=row.qty * row.mark_price,
        unrealized_pnl=pnl,
        opened_at=row.opened_at,
        note=row.note,
        card_id=row.card_id,
    )


def _account(session: Session) -> AccountRow:
    acct = session.get(AccountRow, 1)
    if acct is None:
        settings = get_settings()
        acct = AccountRow(id=1, starting_cash=settings.paper_cash, cash=settings.paper_cash, realized_pnl=0.0)
        session.add(acct)
        session.flush()
    return acct


def status() -> LedgerView:
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        acct = _account(session)
        rows = list(session.scalars(select(PositionRow).where(PositionRow.status == "open")))
        views = [_position_view(r) for r in rows]
        unreal = sum(v.unrealized_pnl for v in views)
        # Equity is mark-to-market: starting + realized + open uPnL.
        # Cash is unallocated paper; open lots reserve entry notional.
        return LedgerView(
            cash=acct.cash,
            starting_cash=acct.starting_cash,
            equity=acct.starting_cash + acct.realized_pnl + unreal,
            realized_pnl=acct.realized_pnl,
            unrealized_pnl=unreal,
            open_count=len(views),
            positions=views,
        )


def open_position(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    venue: str = "paper",
    note: str = "",
    card_id: int | None = None,
    ts: datetime | None = None,
) -> PositionView:
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    if qty <= 0 or price <= 0:
        raise ValueError("qty and price must be positive")
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        acct = _account(session)
        notional = qty * price
        if notional > acct.cash:
            raise ValueError(f"paper cash {acct.cash:.2f} too small for notional {notional:.2f}")
        acct.cash -= notional
        row = PositionRow(
            symbol=symbol.upper(),
            venue=venue,
            side=side,
            qty=qty,
            entry_price=price,
            mark_price=price,
            opened_at=ts or utcnow(),
            note=note,
            card_id=card_id,
            status="open",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _position_view(row)


def close_position(position_id: int, price: float | None = None, ts: datetime | None = None) -> float:
    if price is not None and price <= 0:
        raise ValueError("price must be positive")
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        row = session.get(PositionRow, position_id)
        if row is None or row.status != "open":
            raise ValueError(f"open position {position_id} not found")
        exit_px = price if price is not None else row.mark_price
        pnl = _signed_pnl(row.side, row.qty, row.entry_price, exit_px)
        reserved = row.qty * row.entry_price
        acct = _account(session)
        acct.cash += reserved + pnl
        acct.realized_pnl += pnl
        row.status = "closed"
        row.closed_at = ts or utcnow()
        row.close_price = exit_px
        row.realized_pnl = pnl
        row.mark_price = exit_px
        session.commit()
        return pnl


def mark_positions(marks: dict[str, float], ts: datetime | None = None) -> LedgerView:
    """marks keys are SYMBOL or VENUE:SYMBOL."""
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        rows = list(session.scalars(select(PositionRow).where(PositionRow.status == "open")))
        for row in rows:
            key_a = row.symbol.upper()
            key_b = f"{row.venue}:{row.symbol}".upper()
            px = marks.get(key_b) or marks.get(key_a)
            if px and px > 0:
                row.mark_price = px
        session.commit()
    return status()


def write_journal(kind: str, body: str, extras: dict | None = None) -> int:
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        row = JournalRow(
            ts=datetime.now(timezone.utc),
            kind=kind,
            body=body,
            extras_json=json.dumps(extras or {}, default=str),
        )
        session.add(row)
        session.commit()
        return row.id


def suggest_from_cards(cards, notional: float = 1_000.0) -> list[PositionView]:
    """Open tiny paper lots from top cards. Never routes live."""
    opened: list[PositionView] = []
    from liqpulse.db import latest_snapshots

    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        snaps = { (s.venue, s.symbol): s for s in latest_snapshots(session) }
    for card in cards:
        if card.side_bias not in {"long", "short"}:
            continue
        snap = snaps.get((card.venue, card.symbol))
        px = snap.mark_price if snap else None
        if not px:
            continue
        qty = notional / px
        try:
            opened.append(
                open_position(
                    symbol=card.symbol,
                    side=card.side_bias,
                    qty=qty,
                    price=px,
                    venue=card.venue,
                    note=f"suggest:{card.card_type}:{card.score}",
                    card_id=card.id,
                )
            )
        except ValueError:
            continue
        if len(opened) >= 3:
            break
    return opened
