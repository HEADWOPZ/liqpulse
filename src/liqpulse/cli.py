from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from liqpulse import __version__
from liqpulse.backtest import render_backtest, run_backtest
from liqpulse.brief import build_brief, evening_journal, morning_brief, render_cards, render_ledger_block
from liqpulse.cards import generate_and_store, load_latest
from liqpulse.config import get_settings
from liqpulse.db import init_db, latest_snapshots, get_session_factory
from liqpulse.ingest.runner import LIVE_FETCHERS, run_ingest
from liqpulse.ledger import close_position, open_position, status, suggest_from_cards
from liqpulse.notify import deliver

app = typer.Typer(help="LiqPulse — paper-first liquidation & carry monitor.")
paper_app = typer.Typer(help="Paper ledger. No live order routing.")
app.add_typer(paper_app, name="paper")
console = Console()


def _print(text: str) -> None:
    console.print(text)


@app.callback()
def _root() -> None:
    init_db()


@app.command()
def version() -> None:
    """Print package version."""
    _print(__version__)


@app.command()
def sources() -> None:
    """Show configured symbols and which live venues exist."""
    settings = get_settings()
    table = Table(title="LiqPulse sources")
    table.add_column("source")
    table.add_column("kind")
    table.add_column("notes")
    table.add_row("mock", "always", "deterministic paper tape")
    table.add_row("okx", "public REST", "funding, OI, liqs, L/S ratio")
    table.add_row("hyperliquid", "public POST /info", "funding + predicted CEX prints")
    table.add_row("velocity", "public REST", "Solana-perps proxy (thin book)")
    table.add_row("binance", "public fapi", "often geo-fenced; keys unused in v1")
    table.add_row("bybit", "public v5", "often geo-fenced; keys unused in v1")
    console.print(table)
    _print(f"feed={settings.feed}  selected={','.join(settings.source_list)}  symbols={','.join(settings.symbol_list)}")
    _print(f"known live fetchers: {', '.join(sorted(LIVE_FETCHERS))}")


@app.command()
def ingest(
    source: Optional[str] = typer.Option(None, help="Comma list or mock. Default from env."),
    mode: Optional[str] = typer.Option(None, help="mock | live | auto"),
) -> None:
    """Pull public (or mock) snapshots and persist them."""
    srcs = [s.strip() for s in source.split(",")] if source else None
    snaps, report = run_ingest(mode=mode, sources=srcs)
    _print(
        f"ingest mode={report.mode} ok={report.sources_ok} "
        f"failed={list(report.sources_failed)} snapshots={report.snapshot_count} "
        f"mock_fallback={report.used_mock_fallback}"
    )
    for name, err in report.sources_failed.items():
        _print(f"  fail {name}: {err}")
    table = Table()
    table.add_column("venue")
    table.add_column("symbol")
    table.add_column("mark")
    table.add_column("fund 8h")
    table.add_column("source")
    for s in snaps:
        f8 = s.funding_8h()
        table.add_row(
            s.venue,
            s.symbol,
            f"{s.mark_price:.4g}" if s.mark_price else "-",
            f"{f8:.6f}" if f8 is not None else "-",
            s.source,
        )
    console.print(table)


@app.command()
def score() -> None:
    """Score latest snapshots into opportunity cards."""
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        snaps = latest_snapshots(session)
    if not snaps:
        snaps, _ = run_ingest()
    cards = generate_and_store(snaps)
    _print(render_cards(cards))


@app.command()
def cards(limit: int = typer.Option(12, help="Max cards to print")) -> None:
    """Print stored opportunity cards."""
    stored = load_latest(limit)
    _print(render_cards(stored, limit=limit))


@app.command()
def brief(
    when: str = typer.Argument("morning", help="morning | evening"),
    notify: bool = typer.Option(False, help="Also run delivery (dry-run unless tokens set)"),
) -> None:
    """Morning brief or evening paper journal."""
    kind = when.lower()
    if kind not in {"morning", "evening"}:
        raise typer.BadParameter("when must be morning or evening")
    text = morning_brief() if kind == "morning" else evening_journal()
    _print(text)
    if notify:
        result = deliver(text)
        _print(f"\ndelivery dry_run={result['dry_run']} telegram={result['telegram']} discord={result['discord']}")


@app.command("run")
def run_cycle(
    cycle: str = typer.Option("morning", help="morning | evening"),
    notify: bool = typer.Option(True, help="Attempt Telegram/Discord (dry-run if unset)"),
) -> None:
    """Scheduled job entrypoint: ingest → score → brief/journal → notify."""
    text = morning_brief() if cycle.lower() == "morning" else evening_journal()
    _print(text)
    if notify:
        result = deliver(text)
        _print(f"\ndelivery dry_run={result['dry_run']} telegram={result['telegram']} discord={result['discord']}")


@app.command()
def notify(
    dry_run: bool = typer.Option(False, "--dry-run", help="Force print-only even if tokens are set"),
) -> None:
    """Send the latest brief-shaped payload (or dry-run it)."""
    stored = load_latest(8)
    text = build_brief("morning", stored)
    result = deliver(text, dry_run=True if dry_run else None)
    _print(text)
    _print(f"\ndelivery dry_run={result['dry_run']} telegram={result['telegram']} discord={result['discord']}")
    if result["dry_run"]:
        _print("dry-run: no HTTP POST. Set TELEGRAM_* or DISCORD_WEBHOOK_URL to go live.")


@app.command()
def desk(
    host: Optional[str] = typer.Option(None),
    port: Optional[int] = typer.Option(None),
) -> None:
    """Serve the dark web desk."""
    import uvicorn

    from liqpulse.web.app import create_app

    settings = get_settings()
    uvicorn.run(create_app(), host=host or settings.host, port=port or settings.port, log_level="info")


@app.command()
def backtest() -> None:
    """Replay stored snapshots with the published carry rule."""
    _print(render_backtest(run_backtest()))


@paper_app.command("status")
def paper_status() -> None:
    _print(render_ledger_block())


@paper_app.command("open")
def paper_open(
    symbol: str = typer.Argument(...),
    side: str = typer.Option(..., "--side", help="long | short"),
    qty: float = typer.Option(..., "--qty"),
    price: float = typer.Option(..., "--price"),
    venue: str = typer.Option("paper", "--venue"),
    note: str = typer.Option("", "--note"),
) -> None:
    view = open_position(symbol, side, qty, price, venue=venue, note=note)
    _print(f"opened #{view.id} {view.side} {view.qty} {view.symbol} @{view.entry_price}")


@paper_app.command("close")
def paper_close(
    position_id: int = typer.Argument(...),
    price: Optional[float] = typer.Option(None, "--price"),
) -> None:
    pnl = close_position(position_id, price)
    _print(f"closed #{position_id} realized {pnl:,.2f}")
    _print(render_ledger_block())


@paper_app.command("suggest")
def paper_suggest(notional: float = typer.Option(1_000.0, help="USD notional per card")) -> None:
    """Open up to 3 tiny paper lots from the latest directional cards."""
    stored = load_latest(12)
    opened = suggest_from_cards(stored, notional=notional)
    if not opened:
        _print("no suggestions opened (need cards + marks)")
        return
    for p in opened:
        _print(f"opened #{p.id} {p.side} {p.qty:.6g} {p.symbol} @{p.entry_price} ({p.note})")
    _print(render_ledger_block())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
