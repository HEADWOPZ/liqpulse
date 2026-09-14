from __future__ import annotations

from typing import Any

import httpx

USER_AGENT = "LiqPulse/0.1 (+https://github.com/HEADWOPZ/liqpulse; paper-research)"
TIMEOUT = httpx.Timeout(12.0, connect=6.0)


def client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def get_json(c: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    r = c.get(url, params=params)
    r.raise_for_status()
    return r.json()


def post_json(c: httpx.Client, url: str, payload: dict[str, Any]) -> Any:
    r = c.post(url, json=payload, headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def fnum(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
