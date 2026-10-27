from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check_unit():
    """Test the health check endpoint specifically."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_corpus_state_without_failing():
    """Liveness must stay 200 while the regulation corpus is still building,
    or ECS kills the task mid-ingestion."""
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert "regulations_loaded" in body
    assert isinstance(body["regulation_chunks"], int)
