from fastapi.testclient import TestClient

from liqpulse.ingest.runner import run_ingest
from liqpulse.web.app import create_app


def test_desk_html_and_health(db_path):
    run_ingest(mode="mock")
    client = TestClient(create_app())
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["paper_only"] is True
    page = client.get("/")
    assert page.status_code == 200
    assert "Opportunity cards" in page.text
    assert "Paper ledger" in page.text
    cards = client.get("/api/cards")
    assert cards.status_code == 200
    assert isinstance(cards.json(), list)
