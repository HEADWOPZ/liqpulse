---
name: liq-brief
description: Generate LiqPulse morning or evening liquidation/carry briefs from public (or mock) perp snapshots. Use when the user asks for a liq brief, carry scan, squeeze risk, paper journal, or to run the LiqPulse agentic loop.
---

# liq-brief

Paper-first. Not financial advice. Do not place live orders, size leverage, or invent historical edge.

## When to use

- Morning: ingest public prints, score cards, summarize carry + squeeze risk.
- Evening: same, then mark the paper ledger and write a P&L-style journal.

## Run

From the LiqPulse repo (after `pip install -e .`):

```bash
liqpulse brief morning
liqpulse brief evening
# scheduled / agent loop
liqpulse run --cycle morning
liqpulse run --cycle evening
```

Mock-only (offline, tests, demos):

```bash
LIQPULSE_FEED=mock liqpulse brief morning
```

Inspect cards and the ledger:

```bash
liqpulse cards
liqpulse paper status
liqpulse notify --dry-run
```

## How to write the brief

1. Call the CLI (do not fabricate prints). If the command fails, say so and fall back to `liqpulse cards` / stored journal.
2. Quote **opportunity cards** with their feature breakdown (`funding_8h`, `funding_apr`, `vol_expansion`, `liq_imbalance`, …).
3. Keep venue + source visible. Binance/Bybit may be geo-fenced; OKX / Hyperliquid / Velocity are the usual live publics.
4. Velocity (Solana-perps) books are thin — flag size as illustrative.
5. Paper ledger only. Never claim "$X yesterday" or a live fill.
6. End with the disclaimer: paper-only v1, heuristics not a model, not financial advice.

## Card types

- `carry` — extreme funding. Positive 8h funding → shorts receive (paper bias short to collect).
- `squeeze_risk` — vol expansion + liq imbalance / crowding. Directional only when the prints agree.

## Delivery

`liqpulse notify` is dry-run unless `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID` or `DISCORD_WEBHOOK_URL` are set.
