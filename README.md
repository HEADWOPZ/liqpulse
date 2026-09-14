# LiqPulse

Paper-first **liquidation & carry loop monitor**. It watches public perp funding, open interest, and liquidation prints, scores them with **transparent heuristics**, and ships structured opportunity cards (carry, squeeze risk) on a morning / evening loop.

v1 does **not** route live orders, custody margin, or claim a backtested edge. There is no “$15k yesterday.”

**Not financial advice.** Cards are evidence packs, not trade tickets.

## Architecture

```mermaid
flowchart LR
  subgraph ingest [Public ingest]
    OKX[OKX REST]
    HL[Hyperliquid /info]
    VEL[Velocity Solana perps]
    CEX[Binance / Bybit REST]
    MOCK[Mock tape]
  end
  subgraph store [Feature store]
    SNAP[SQLite / Postgres snapshots]
    SCORE[Heuristic scorer]
    CARDS[Opportunity cards]
  end
  subgraph out [Delivery]
    CLI[CLI brief + journal]
    DESK[Dark web desk]
    NOTE[Telegram / Discord]
    PAPER[Paper ledger]
  end
  OKX --> SNAP
  HL --> SNAP
  VEL --> SNAP
  CEX --> SNAP
  MOCK --> SNAP
  SNAP --> SCORE --> CARDS
  CARDS --> CLI
  CARDS --> DESK
  CARDS --> NOTE
  SNAP --> PAPER
```

| Piece | What it does |
| --- | --- |
| Ingest | Public REST/POST only. Mock always works. |
| Features | Funding extremes, vol expansion, liq imbalance, crowding, cross-venue funding dispersion |
| Cards | `carry` and `squeeze_risk` with per-feature contribution |
| Loop | `liqpulse brief morning` / `evening` (or `liqpulse run`) |
| Ledger | Paper positions, marks, realized / unrealized PnL. No live routing. |
| Replay | `liqpulse backtest` over **stored** snapshots |

## Data sources

No exchange API key is required for v1. Keys are documented only if you later raise rate limits.

| Source | Auth | Notes |
| --- | --- | --- |
| **mock** | none | Deterministic majors tape for offline / CI |
| **okx** | public | Funding, ticker, OI, liquidation orders, L/S ratio |
| **hyperliquid** | public `POST /info` | Funding, OI, plus `predictedFundings` (CEX prints as evidence) |
| **velocity** | public | Solana-perps proxy (`BTC-PERP` / `ETH-PERP` / `SOL-PERP`). Thin books — treat size as illustrative |
| **binance** | public fapi (optional key unused) | Often geo-fenced (HTTP 451). Client is real; ingest records the miss |
| **bybit** | public v5 (optional key unused) | Often CloudFront-blocked. Same honesty as Binance |
| Coinglass | key required | **Not called** unless you add a key later; the free path returns `API key missing` |

Default feed is `auto`: try configured live venues, **fall back to mock** if none respond.

## Setup

Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # optional
```

SQLite is the default (`./data/liqpulse.db`). Postgres:

```bash
pip install -e ".[postgres]"
export DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/liqpulse
```

## Run (README contract)

### Mock (always)

```bash
LIQPULSE_FEED=mock liqpulse ingest
LIQPULSE_FEED=mock liqpulse score
LIQPULSE_FEED=mock liqpulse brief morning
liqpulse cards
liqpulse paper status
liqpulse notify --dry-run
```

### Live public (at least one venue if reachable)

```bash
liqpulse sources
liqpulse ingest --mode auto
# force a venue
liqpulse ingest --source okx,hyperliquid,velocity --mode live
liqpulse brief morning
```

On a box that can reach OKX / Hyperliquid / Velocity you should see real marks and funding. Binance/Bybit failures are expected from some regions and are printed, not hidden.

### Paper ledger

```bash
liqpulse paper open BTC --side short --qty 0.01 --price 78000 --note "manual paper"
liqpulse paper status
liqpulse paper suggest --notional 1000
liqpulse brief evening          # marks from latest snapshots + journal
liqpulse paper close 1 --price 77500
```

### Replay

```bash
liqpulse ingest --mode mock
liqpulse ingest --mode mock
liqpulse backtest
# or
python scripts/backtest.py
```

Mark-to-mark only. No fees, no slippage, no invented sample.

### Dark desk

```bash
liqpulse desk --host 127.0.0.1 --port 8080
# open http://127.0.0.1:8080
```

Latest cards (with feature tables), snapshots, and the paper ledger. The **ingest + score** button hits `POST /api/ingest`.

### Agentic skill

Hermes / Claude skill: **`liq-brief`**

- [`skills/liq-brief/SKILL.md`](skills/liq-brief/SKILL.md)
- [`.claude/skills/liq-brief/SKILL.md`](.claude/skills/liq-brief/SKILL.md)
- [`.hermes/skills/liq-brief/SKILL.md`](.hermes/skills/liq-brief/SKILL.md)

```bash
liqpulse run --cycle morning
liqpulse run --cycle evening
```

Cron (UTC):

```
0 13 * * *  cd /path/to/liqpulse && .venv/bin/liqpulse run --cycle morning
0 22 * * *  cd /path/to/liqpulse && .venv/bin/liqpulse run --cycle evening
```

### Delivery

`liqpulse notify` **dry-runs** (prints the payload) unless tokens are set:

| Env | Effect |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Send the brief via Bot API |
| `DISCORD_WEBHOOK_URL` | POST the brief to a webhook |

`--dry-run` forces print-only even when tokens exist.

## Scoring (what the numbers mean)

Nothing here is a trained model or a year of proprietary data.

- **funding_8h** — venue rate scaled to 8 hours so hourly books (Hyperliquid, Velocity) compare with CEX 8h prints.
- **funding_apr** — `rate × (24 / period_hours) × 365`. Simple, not compounded. APR > 500% is flagged as thin-book / unit risk and score-capped.
- **carry card** — fires when `|funding_8h| ≥ 0.03%` or `|APR| ≥ 15%`. Positive funding → paper bias **short** (longs pay). The opposite for negative funding.
- **vol_expansion** — 24h range vs a 4% “quiet day” reference.
- **liq_imbalance** — `(long liqs − short liqs) / total` from public liquidation prints when the venue exposes them.
- **squeeze_risk** — vol expansion plus liquidation / crowding alignment (cascade-down vs squeeze-up).
- **funding_venue_dispersion** — max−min 8h funding across venues in the same ingest.

Each card lists `contribution` per feature so you can see why it scored.

## Tests

```bash
pytest
```

Covers scoring, paper ledger PnL, mock persist → cards, notify dry-run, and live OKX when the network allows (otherwise mock fallback).

## Disclaimer

LiqPulse is a research desk for **paper** observation of public market-structure prints. It is not a broker, not an advisor, and not a performance track record. Do not size real leverage off these cards.

## License

[MIT](LICENSE) © 2026 Kevin Lance Murray
