from app.models import Base


def test_health_endpoint_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "connected"
    assert payload["service"] == "Job Application Copilot"


def test_expected_tables_registered():
    expected = {
        "users",
        "profiles",
        "jobs",
        "applications",
        "documents",
        "emails",
        "agent_runs",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))
