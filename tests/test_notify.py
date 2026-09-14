from __future__ import annotations

from liqpulse.notify import deliver


def test_deliver_dry_run_without_tokens(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    from liqpulse.config import get_settings

    get_settings.cache_clear()
    out = deliver("hello cards")
    assert out["dry_run"] is True
    assert "hello cards" in out["preview"]
    get_settings.cache_clear()
