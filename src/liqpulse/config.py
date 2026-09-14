from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    feed: str = Field(default="auto", validation_alias=AliasChoices("LIQPULSE_FEED", "feed"))
    sources: str = Field(
        default="okx,hyperliquid,velocity,binance,bybit",
        validation_alias=AliasChoices("LIQPULSE_SOURCES", "sources"),
    )
    symbols: str = Field(
        default="BTC,ETH,SOL",
        validation_alias=AliasChoices("LIQPULSE_SYMBOLS", "symbols"),
    )
    database_url: str = Field(
        default="sqlite:///./data/liqpulse.db",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    paper_cash: float = Field(
        default=100_000.0,
        validation_alias=AliasChoices("LIQPULSE_PAPER_CASH", "paper_cash"),
    )
    host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("LIQPULSE_HOST", "host"))
    port: int = Field(default=8080, validation_alias=AliasChoices("LIQPULSE_PORT", "port"))

    binance_api_key: str = Field(default="", validation_alias=AliasChoices("BINANCE_API_KEY", "binance_api_key"))
    binance_api_secret: str = Field(
        default="", validation_alias=AliasChoices("BINANCE_API_SECRET", "binance_api_secret")
    )
    bybit_api_key: str = Field(default="", validation_alias=AliasChoices("BYBIT_API_KEY", "bybit_api_key"))
    bybit_api_secret: str = Field(default="", validation_alias=AliasChoices("BYBIT_API_SECRET", "bybit_api_secret"))
    coinglass_api_key: str = Field(
        default="", validation_alias=AliasChoices("COINGLASS_API_KEY", "coinglass_api_key")
    )

    telegram_bot_token: str = Field(
        default="", validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "telegram_bot_token")
    )
    telegram_chat_id: str = Field(
        default="", validation_alias=AliasChoices("TELEGRAM_CHAT_ID", "telegram_chat_id")
    )
    discord_webhook_url: str = Field(
        default="", validation_alias=AliasChoices("DISCORD_WEBHOOK_URL", "discord_webhook_url")
    )

    @property
    def source_list(self) -> list[str]:
        return [s.strip().lower() for s in self.sources.split(",") if s.strip()]

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def discord_ready(self) -> bool:
        return bool(self.discord_webhook_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
