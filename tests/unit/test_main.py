from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check_unit():
    """Test the health check endpoint specifically."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
