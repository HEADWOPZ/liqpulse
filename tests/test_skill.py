from pathlib import Path

from liqpulse.config import ROOT


def test_liq_brief_skill_exists():
    paths = [
        ROOT / "skills" / "liq-brief" / "SKILL.md",
        ROOT / ".claude" / "skills" / "liq-brief" / "SKILL.md",
        ROOT / ".hermes" / "skills" / "liq-brief" / "SKILL.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "name: liq-brief" in text
        assert "liqpulse brief morning" in text
        assert "Not financial advice" in text
