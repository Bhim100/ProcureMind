from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert data["health"] == "/api/v1/health"
    assert data["readiness"] == "/api/v1/ready"


def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data
    assert "environment" in data


def test_readiness_endpoint():
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ready", "degraded"]
    assert "database" in data
    assert "storage" in data
    assert "secondary_services" in data
    assert data["storage"]["backend"] in ["local", "s3"]
    assert data["secondary_services"]["falkordb"] == "disabled (optional)"
