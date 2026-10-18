from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root() -> None:
    """Test the root endpoint."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Sophikron API"}


def test_health_check() -> None:
    """Test the health endpoint."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}