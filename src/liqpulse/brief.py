from __future__ import annotations

from datetime import datetime, timezone

from liqpulse.cards import generate_and_store, load_latest
from liqpulse.db import latest_journal, latest_snapshots
from liqpulse.db import get_session_factory, init_db
from liqpulse.ingest.runner import run_ingest
from liqpulse.ledger import mark_positions, status, write_journal
from liqpulse.models import IngestReport, OpportunityCard


def _fmt_pct(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.{digits}f}%"


def render_cards(cards: list[OpportunityCard], limit: int = 8) -> str:
    if not cards:
        return "No opportunity cards this cycle. Markets look boring on the public prints, or ingest was empty."
    lines: list[str] = []
    for card in cards[:limit]:
        lines.append(f"## [{card.score:5.1f}] {card.card_type} · {card.symbol} {card.venue}")
        lines.append(f"{card.title}")
        lines.append(f"bias={card.side_bias}  horizon={card.horizon}")
        lines.append(card.thesis)
        lines.append("features:")
        for feat in card.features:
            if feat.contribution <= 0 and feat.name not in {"funding_8h", "funding_apr", "liq_imbalance", "vol_expansion"}:
                continue
            lines.append(
                f"  - {feat.name:24s} {feat.value: .6g} {feat.unit:8s}  "
                f"contrib={feat.contribution:5.1f}  {feat.note}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def render_ledger_block() -> str:
    view = status()
    lines = [
        f"paper cash     {view.cash:,.2f}",
        f"equity         {view.equity:,.2f}",
        f"realized pnl   {view.realized_pnl:,.2f}",
        f"unrealized     {view.unrealized_pnl:,.2f}",
        f"open positions {view.open_count}",
    ]
    for p in view.positions:
        lines.append(
            f"  #{p.id} {p.side:5s} {p.qty:.6g} {p.symbol} @{p.entry_price:.4g} "
            f"mark {p.mark_price:.4g} uPnL {p.unrealized_pnl:,.2f} ({p.venue})"
        )
    return "\n".join(lines)


def build_brief(kind: str, cards: list[OpportunityCard], report: IngestReport | None = None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = "LiqPulse morning brief" if kind == "morning" else "LiqPulse evening paper journal"
    chunks = [
        f"# {header}",
        f"{now}",
        "",
        "Paper-only v1. Not financial advice. Heuristics are public and reversible.",
        "",
    ]
    if report:
        chunks.append(
            f"ingest mode={report.mode} ok={','.join(report.sources_ok) or '-'} "
            f"failed={list(report.sources_failed.keys()) or '-'} "
            f"snapshots={report.snapshot_count} mock_fallback={report.used_mock_fallback}"
        )
        if report.sources_failed:
            for name, err in report.sources_failed.items():
                chunks.append(f"  fail {name}: {err}")
        chunks.append("")
    chunks.append("## Opportunity cards")
    chunks.append(render_cards(cards))
    chunks.append("")
    chunks.append("## Paper ledger")
    chunks.append(render_ledger_block())
    if kind == "evening":
        chunks.append("")
        chunks.append("## Evening note")
        chunks.append(
            "Marks applied from the latest snapshot per venue/symbol. "
            "No funding cashflows are booked automatically — estimate carry from the funding_8h feature."
        )
    return "\n".join(chunks)


def morning_brief(persist: bool = True) -> str:
    snaps, report = run_ingest(persist=persist)
    cards = generate_and_store(snaps) if snaps else []
    text = build_brief("morning", cards, report)
    write_journal("morning", text, {"snapshot_count": report.snapshot_count, "cards": len(cards)})
    return text


def evening_journal(persist: bool = True) -> str:
    snaps, report = run_ingest(persist=persist)
    cards = generate_and_store(snaps) if snaps else []
    marks: dict[str, float] = {}
    for s in snaps:
        if s.mark_price:
            marks[s.symbol.upper()] = s.mark_price
            marks[f"{s.venue}:{s.symbol}".upper()] = s.mark_price
    if marks:
        mark_positions(marks)
    text = build_brief("evening", cards, report)
    view = status()
    write_journal(
        "evening",
        text,
        {"equity": view.equity, "realized": view.realized_pnl, "unrealized": view.unrealized_pnl},
    )
    return text


def last_stored_brief() -> str:
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        rows = latest_journal(session, limit=1)
        if rows:
            return rows[0].body
        cards = load_latest(12)
        return build_brief("morning", cards)


def desk_payload() -> dict:
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        cards = [c.model_dump(mode="json") for c in load_latest(24)]
        snaps = [s.model_dump(mode="json") for s in latest_snapshots(session)]
    view = status()
    return {
        "cards": cards,
        "snapshots": snaps,
        "ledger": view.model_dump(mode="json"),
        "disclaimer": "Paper-only v1. Not financial advice.",
    }
