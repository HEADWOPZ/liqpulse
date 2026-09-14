from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from liqpulse.config import ROOT, get_settings
from liqpulse.models import MarketSnapshot, OpportunityCard


class Base(DeclarativeBase):
    pass


class SnapshotRow(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    index_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_funding: Mapped[float | None] = mapped_column(Float, nullable=True)
    funding_period_hours: Mapped[float] = mapped_column(Float, default=8.0)
    next_funding_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    oi_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_24h_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    liq_long_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    liq_short_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    long_short_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_vol_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_json: Mapped[str] = mapped_column(Text, default="{}")


class CardRow(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    card_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256))
    thesis: Mapped[str] = mapped_column(Text)
    side_bias: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float, index=True)
    horizon: Mapped[str] = mapped_column(String(32), default="8h-24h")
    features_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id"), nullable=True)


class AccountRow(Base):
    __tablename__ = "paper_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    starting_cash: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)


class PositionRow(Base):
    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    venue: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    mark_price: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    card_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)


class JournalRow(Base):
    __tablename__ = "journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    body: Mapped[str] = mapped_column(Text)
    extras_json: Mapped[str] = mapped_column(Text, default="{}")


_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    # sqlite:///./data/liqpulse.db or sqlite:////abs/path
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        if raw.startswith("./") or not raw.startswith("/"):
            path = (ROOT / raw).resolve()
        else:
            path = Path(raw)
        path.parent.mkdir(parents=True, exist_ok=True)


def get_engine(url: str | None = None) -> Engine:
    global _engine
    settings = get_settings()
    url = url or settings.database_url
    if url.startswith("sqlite:///./"):
        rel = url[len("sqlite:///") :]
        url = "sqlite:///" + str((ROOT / rel).resolve())
    if _engine is not None and str(_engine.url) == url:
        return _engine
    _ensure_sqlite_dir(url)
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)
    return _engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    global _Session
    engine = get_engine(url)
    if _Session is None or _Session.kw.get("bind") is not engine:
        _Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return _Session


def init_db(url: str | None = None) -> None:
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    settings = get_settings()
    SessionLocal = get_session_factory(url)
    with SessionLocal() as session:
        acct = session.get(AccountRow, 1)
        if acct is None:
            session.add(
                AccountRow(id=1, starting_cash=settings.paper_cash, cash=settings.paper_cash, realized_pnl=0.0)
            )
            session.commit()


def reset_engine() -> None:
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def snapshot_from_row(row: SnapshotRow) -> MarketSnapshot:
    extra = json.loads(row.extra_json or "{}")
    extra["id"] = row.id
    return MarketSnapshot(
        ts=row.ts,
        venue=row.venue,
        source=row.source,
        symbol=row.symbol,
        mark_price=row.mark_price,
        index_price=row.index_price,
        last_funding=row.last_funding,
        funding_period_hours=row.funding_period_hours,
        next_funding_ts=row.next_funding_ts,
        open_interest=row.open_interest,
        oi_notional=row.oi_notional,
        volume_24h_notional=row.volume_24h_notional,
        high_24h=row.high_24h,
        low_24h=row.low_24h,
        change_24h_pct=row.change_24h_pct,
        liq_long_notional=row.liq_long_notional,
        liq_short_notional=row.liq_short_notional,
        long_short_ratio=row.long_short_ratio,
        realized_vol_24h=row.realized_vol_24h,
        extra=extra,
    )


def card_from_row(row: CardRow) -> OpportunityCard:
    return OpportunityCard(
        id=row.id,
        ts=row.ts,
        venue=row.venue,
        symbol=row.symbol,
        card_type=row.card_type,  # type: ignore[arg-type]
        title=row.title,
        thesis=row.thesis,
        side_bias=row.side_bias,  # type: ignore[arg-type]
        score=row.score,
        horizon=row.horizon,
        features=json.loads(row.features_json or "[]"),
        evidence=json.loads(row.evidence_json or "{}"),
        snapshot_id=row.snapshot_id,
    )


def persist_snapshots(session: Session, snaps: list[MarketSnapshot]) -> list[int]:
    ids: list[int] = []
    for snap in snaps:
        row = SnapshotRow(
            ts=snap.ts,
            venue=snap.venue,
            source=snap.source,
            symbol=snap.symbol,
            mark_price=snap.mark_price,
            index_price=snap.index_price,
            last_funding=snap.last_funding,
            funding_period_hours=snap.funding_period_hours,
            next_funding_ts=snap.next_funding_ts,
            open_interest=snap.open_interest,
            oi_notional=snap.oi_notional,
            volume_24h_notional=snap.volume_24h_notional,
            high_24h=snap.high_24h,
            low_24h=snap.low_24h,
            change_24h_pct=snap.change_24h_pct,
            liq_long_notional=snap.liq_long_notional,
            liq_short_notional=snap.liq_short_notional,
            long_short_ratio=snap.long_short_ratio,
            realized_vol_24h=snap.realized_vol_24h,
            extra_json=json.dumps(snap.extra, default=str),
        )
        session.add(row)
        session.flush()
        snap.extra["id"] = row.id
        ids.append(row.id)
    session.commit()
    return ids


def persist_cards(session: Session, cards: list[OpportunityCard]) -> list[int]:
    ids: list[int] = []
    for card in cards:
        row = CardRow(
            ts=card.ts,
            venue=card.venue,
            symbol=card.symbol,
            card_type=card.card_type,
            title=card.title,
            thesis=card.thesis,
            side_bias=card.side_bias,
            score=card.score,
            horizon=card.horizon,
            features_json=json.dumps([f.model_dump() for f in card.features], default=str),
            evidence_json=json.dumps(card.evidence, default=str),
            snapshot_id=card.snapshot_id,
        )
        session.add(row)
        session.flush()
        card.id = row.id
        ids.append(row.id)
    session.commit()
    return ids


def latest_snapshots(session: Session) -> list[MarketSnapshot]:
    rows = session.scalars(select(SnapshotRow).order_by(SnapshotRow.ts.desc()).limit(400)).all()
    seen: set[tuple[str, str]] = set()
    out: list[MarketSnapshot] = []
    for row in rows:
        key = (row.venue, row.symbol)
        if key in seen:
            continue
        seen.add(key)
        out.append(snapshot_from_row(row))
    return out


def all_snapshots(session: Session, limit: int = 2000) -> list[MarketSnapshot]:
    rows = session.scalars(select(SnapshotRow).order_by(SnapshotRow.ts.asc()).limit(limit)).all()
    return [snapshot_from_row(r) for r in rows]


def latest_cards(session: Session, limit: int = 40) -> list[OpportunityCard]:
    rows = session.scalars(select(CardRow).order_by(CardRow.ts.desc(), CardRow.score.desc()).limit(400)).all()
    seen: set[tuple[str, str, str]] = set()
    out: list[OpportunityCard] = []
    for row in rows:
        key = (row.venue, row.symbol, row.card_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(card_from_row(row))
        if len(out) >= limit:
            break
    out.sort(key=lambda c: (-c.score, c.symbol, c.venue))
    return out


def latest_journal(session: Session, limit: int = 20) -> list[JournalRow]:
    return list(session.scalars(select(JournalRow).order_by(JournalRow.ts.desc()).limit(limit)).all())
