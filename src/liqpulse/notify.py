from __future__ import annotations

from typing import Any

import httpx

from liqpulse.config import get_settings
from liqpulse.ingest.http import USER_AGENT


def _chunk(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            parts.append("".join(buf))
            buf = [line]
            size = len(line)
        else:
            buf.append(line)
            size += len(line)
    if buf:
        parts.append("".join(buf))
    return parts


def deliver(text: str, dry_run: bool | None = None) -> dict[str, Any]:
    settings = get_settings()
    auto_dry = not (settings.telegram_ready or settings.discord_ready)
    dry = auto_dry if dry_run is None else dry_run
    result: dict[str, Any] = {"dry_run": dry, "telegram": None, "discord": None, "preview": text[:1200]}
    if dry:
        return result

    if settings.telegram_ready:
        sent = []
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        with httpx.Client(timeout=12.0, headers={"User-Agent": USER_AGENT}) as c:
            for chunk in _chunk(text):
                r = c.post(
                    url,
                    json={"chat_id": settings.telegram_chat_id, "text": chunk, "disable_web_page_preview": True},
                )
                sent.append({"status": r.status_code, "ok": r.is_success})
        result["telegram"] = sent

    if settings.discord_ready:
        with httpx.Client(timeout=12.0, headers={"User-Agent": USER_AGENT}) as c:
            r = c.post(settings.discord_webhook_url, json={"content": text[:1900]})
            result["discord"] = {"status": r.status_code, "ok": r.is_success}
    return result
