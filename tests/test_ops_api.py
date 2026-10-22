from apps.brain.main import create_app
from fastapi.testclient import TestClient


def test_ops_and_ready():
    c = TestClient(create_app(llm="offline"))
    c.get("/api/matches")
    ops = c.get("/api/ops").json()
    assert ops["requests"]["total"] >= 1 and "streams" in ops and "narrative" in ops
    r = c.get("/ready")
    assert r.status_code in (200, 503) and "checks" in r.json()
