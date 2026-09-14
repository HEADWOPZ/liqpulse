from __future__ import annotations

from liqpulse.db import get_session_factory, init_db, latest_cards, persist_cards
from liqpulse.features.scoring import score_universe
from liqpulse.models import MarketSnapshot, OpportunityCard


def generate_and_store(snaps: list[MarketSnapshot]) -> list[OpportunityCard]:
    cards = score_universe(snaps)
    if not cards:
        return []
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        persist_cards(session, cards)
    return cards


def load_latest(limit: int = 40) -> list[OpportunityCard]:
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        return latest_cards(session, limit=limit)
