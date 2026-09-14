from __future__ import annotations

import os
from pathlib import Path

import pytest

from liqpulse.config import get_settings
from liqpulse.db import init_db, reset_engine


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "liqpulse.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("LIQPULSE_PAPER_CASH", "100000")
    get_settings.cache_clear()
    reset_engine()
    init_db()
    yield path
    reset_engine()
    get_settings.cache_clear()
    os.environ.pop("DATABASE_URL", None)
