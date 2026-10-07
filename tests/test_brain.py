import socket
import threading
import time

import pytest
import uvicorn
from apps.brain.main import MAX_COHORTS, create_app
from fastapi.testclient import TestClient

from matchmind.intel.pipeline import interpret_match
from matchmind.mcp_server.registry import MatchRegistry


@pytest.fixture(scope="module")
def reg(match):
    ip, _ = interpret_match(match)
    r = MatchRegistry()
    r.register("t0001", ip)
    return r


@pytest.fixture()
def client(reg):
    with TestClient(create_app(reg, director=True)) as c:
        yield c


def moment_ids(client, n=2):
    ms = client.get("/api/matches/t0001/moments", params={"min_salience": 0.5}).json()
    return [m["id"] for m in ms[:n]]


def test_health_reports_the_model_client(client):
    d = client.get("/health").json()
    assert d["status"] == "ok" and d["llm"] == "offline"


def test_matches_and_moments(client):
    assert "t0001" in client.get("/api/matches").json()
    ms = client.get("/api/matches/t0001/moments").json()
    assert ms and {"id", "type", "label", "salience"} <= set(ms[0])
    assert client.get("/api/matches/nope/moments").status_code == 404


COHORTS = [{"mode": "analyst", "language": "en"}, {"mode": "casual", "language": "tr", "perspective": "HAR"}]


def test_beats_run_the_real_agent_workflow(client):
    ids = moment_ids(client, 1)
    r = client.post("/api/beats", json={"match_id": "t0001", "moment_ids": ids, "cohorts": COHORTS, "budget": 3})
    assert r.status_code == 200
    beat = r.json()["beats"][0]
    assert beat["level"] == 0 and len(beat["overlays"]) == 2
    assert [t["agent"] for t in beat["trace"]][:3] == ["editor", "explainer", "verifier"]


def test_director_fault_switch_degrades_the_next_request_and_recovers(client):
    ids = moment_ids(client, 1)
    body = {"match_id": "t0001", "moment_ids": ids, "cohorts": COHORTS}
    assert client.post("/api/director/faults", json={"mode": "error"}).json()["mode"] == "error"
    degraded = client.post("/api/beats", json=body).json()["beats"][0]
    assert degraded["level"] == 2 and degraded["overlays"], "an outage still produces overlays"
    client.post("/api/director/faults", json={"mode": "none"})
    assert client.post("/api/beats", json=body).json()["beats"][0]["level"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"match_id": "t0001", "moment_ids": [], "cohorts": COHORTS},
        {"match_id": "t0001", "moment_ids": ["a"] * 7, "cohorts": COHORTS},
        {"match_id": "t0001", "moment_ids": ["x"], "cohorts": [{"mode": "casual", "language": "en"}] * (MAX_COHORTS + 1)},
        {"match_id": "t0001", "moment_ids": ["x"], "cohorts": [{"mode": "casual", "language": "fr"}]},
    ],
)
def test_requests_are_bounded_and_validated(client, body):
    assert client.post("/api/beats", json=body).status_code == 422


def test_director_routes_do_not_exist_unless_enabled(reg, monkeypatch):
    monkeypatch.delenv("MATCHMIND_DIRECTOR", raising=False)
    with TestClient(create_app(reg)) as c:
        assert c.get("/api/director/faults").status_code == 404
        assert c.post("/api/director/faults", json={"mode": "error"}).status_code == 404


def test_director_key_is_required_when_configured(reg, monkeypatch):
    monkeypatch.setenv("MATCHMIND_DIRECTOR_KEY", "s3cret")
    with TestClient(create_app(reg, director=True)) as c:
        assert c.post("/api/director/faults", json={"mode": "error"}).status_code == 403
        assert c.post("/api/director/faults", json={"mode": "error"}, headers={"X-Director-Key": "no"}).status_code == 403
        assert c.post("/api/director/faults", json={"mode": "error"}, headers={"X-Director-Key": "s3cret"}).status_code == 200


def test_unknown_moment_is_a_404(client):
    r = client.post("/api/beats", json={"match_id": "t0001", "moment_ids": ["nope"], "cohorts": COHORTS})
    assert r.status_code == 404


def test_fault_settings_are_validated(client):
    assert client.post("/api/director/faults", json={"mode": "explode"}).status_code == 422
    assert client.post("/api/director/faults", json={"mode": "slow", "delay_s": 999}).status_code == 422


def test_mcp_is_served_over_streamable_http_to_a_real_client(reg):
    """The path agents use: an actual HTTP server and an MCP client over the network stack."""
    import asyncio

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(create_app(reg), host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started

    async def go():
        async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp/") as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                res = await session.call_tool("get_match_state", {"match_id": "t0001"})
                return tools, res

    try:
        tools, res = asyncio.run(go())
    finally:
        server.should_exit = True
        t.join(timeout=5)
    assert "get_window_stats" in tools and not res.isError


def test_the_analytics_endpoint_matches_the_replay_package(reg):
    from matchmind.analytics.season import context_for, load_season

    ctx = context_for(load_season(), "HAR", "NOR")
    ip = reg.get("t0001")
    ip.season = ctx  # the registry fixture's interpreter has no season; give it the one a replay build would
    with TestClient(create_app(reg)) as c:
        d = c.get("/api/matches/t0001/analytics").json()
    assert {"winProbability", "shots", "players", "season", "radars", "teamRadars"} <= set(d)
    assert d["season"]["prediction"]["home"] + d["season"]["prediction"]["draw"] + d["season"]["prediction"]["away"] == pytest.approx(1.0, abs=0.01)


def test_the_report_pdf_is_served_for_committed_matches_only(client):
    r = client.get("/api/matches/pressing-collapse/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert client.get("/api/matches/t0001/report.pdf").status_code == 404, "a match with no built report says so"
    assert client.get("/api/matches/nope/report.pdf").status_code == 404
    assert client.get("/api/matches/..%2F..%2Fetc%2Fpasswd/report.pdf").status_code == 404


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def test_mcp_answers_on_the_public_host_name_only_when_told_to(reg, monkeypatch):
    """Behind a public ingress the Host header is the service's own name; the library refuses it (421) unless allowed."""
    monkeypatch.delenv("MATCHMIND_ALLOWED_HOSTS", raising=False)
    with TestClient(create_app(reg), base_url="https://brain.example.net") as c:
        assert c.post("/mcp/", json=INIT, headers=MCP_HEADERS).status_code == 421
    monkeypatch.setenv("MATCHMIND_ALLOWED_HOSTS", "brain.example.net")
    with TestClient(create_app(reg), base_url="https://brain.example.net") as c:
        assert c.post("/mcp/", json=INIT, headers=MCP_HEADERS).status_code == 200
    with TestClient(create_app(reg), base_url="https://evil.example.org") as c:
        assert c.post("/mcp/", json=INIT, headers=MCP_HEADERS).status_code == 421, "other names stay refused"
