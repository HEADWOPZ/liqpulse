from __future__ import annotations

from collections.abc import Callable

from liqpulse.config import get_settings
from liqpulse.db import get_session_factory, init_db, persist_snapshots
from liqpulse.ingest.binance import fetch_binance
from liqpulse.ingest.bybit import fetch_bybit
from liqpulse.ingest.hyperliquid import fetch_hyperliquid
from liqpulse.ingest.mock import fetch_mock
from liqpulse.ingest.okx import fetch_okx
from liqpulse.ingest.velocity import fetch_velocity
from liqpulse.models import IngestReport, MarketSnapshot

LIVE_FETCHERS: dict[str, Callable[[list[str]], list[MarketSnapshot]]] = {
    "okx": fetch_okx,
    "hyperliquid": fetch_hyperliquid,
    "velocity": fetch_velocity,
    "binance": fetch_binance,
    "bybit": fetch_bybit,
}

# Prefer venues that are widely reachable without keys. Binance/Bybit stay
# first-class but are often geo-fenced; ingest records the failure honestly.
DEFAULT_LIVE_ORDER = ["okx", "hyperliquid", "velocity", "binance", "bybit"]


def run_ingest(
    mode: str | None = None,
    sources: list[str] | None = None,
    symbols: list[str] | None = None,
    persist: bool = True,
) -> tuple[list[MarketSnapshot], IngestReport]:
    settings = get_settings()
    mode = (mode or settings.feed).lower()
    symbols = symbols or settings.symbol_list
    if sources:
        requested = [s.lower() for s in sources]
    else:
        requested = [s for s in settings.source_list if s != "mock"] or list(DEFAULT_LIVE_ORDER)

    snaps: list[MarketSnapshot] = []
    ok: list[str] = []
    failed: dict[str, str] = {}
    used_mock = False

    if mode == "mock" or requested == ["mock"]:
        snaps = fetch_mock(symbols)
        ok = ["mock"]
        used_mock = True
        report = IngestReport(
            mode="mock",
            sources_attempted=["mock"],
            sources_ok=ok,
            sources_failed=failed,
            snapshot_count=len(snaps),
            used_mock_fallback=True,
        )
        if persist:
            _save(snaps)
        return snaps, report

    attempted: list[str] = []
    for name in requested:
        if name == "mock":
            continue
        fetcher = LIVE_FETCHERS.get(name)
        if fetcher is None:
            failed[name] = "unknown source"
            continue
        attempted.append(name)
        try:
            batch = fetcher(symbols)
            if not batch:
                raise RuntimeError("empty batch")
            snaps.extend(batch)
            ok.append(name)
        except Exception as exc:  # noqa: BLE001 — source isolation
            failed[name] = str(exc)[:240]

    if not snaps and mode in {"auto", "live"}:
        if mode == "live":
            report = IngestReport(
                mode=mode,
                sources_attempted=attempted,
                sources_ok=ok,
                sources_failed=failed,
                snapshot_count=0,
                used_mock_fallback=False,
            )
            return [], report
        snaps = fetch_mock(symbols)
        ok.append("mock")
        used_mock = True

    report = IngestReport(
        mode=mode,
        sources_attempted=attempted or ["mock"],
        sources_ok=ok,
        sources_failed=failed,
        snapshot_count=len(snaps),
        used_mock_fallback=used_mock,
    )
    if persist and snaps:
        _save(snaps)
    return snaps, report


def _save(snaps: list[MarketSnapshot]) -> None:
    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        persist_snapshots(session, snaps)
