#!/usr/bin/env python3
"""Replay stored LiqPulse snapshots. Prefer `liqpulse backtest`."""

from liqpulse.backtest import render_backtest, run_backtest

if __name__ == "__main__":
    print(render_backtest(run_backtest()))
