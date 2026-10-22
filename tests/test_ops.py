"""The operations summary: request statistics over a window, and what the agents did."""

from __future__ import annotations

from matchmind.ops import Ops, group_of


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_requests_are_grouped_and_summarised_without_counting_health_checks():
    c = Clock()
    o = Ops(clock=c)
    for ms in (100, 200, 300, 400):
        o.record_request("/api/beats", 200, ms)
    o.record_request("/api/stream/s-x/feed", 200, 20)
    o.record_request("/api/stream", 503, 5)
    o.record_request("/health", 200, 3)
    s = o.snapshot()
    assert s["requests"]["total"] == 6 and s["requests"]["errors"] == 1  # health is not a request a viewer made
    assert s["requests"]["byGroup"]["beats"]["requests"] == 4 and s["requests"]["byGroup"]["beats"]["p95Ms"] == 400
    assert s["requests"]["byGroup"]["stream"] == {"requests": 2, "errors": 1, "p50Ms": 20, "p95Ms": 20} or s["requests"]["byGroup"]["stream"]["errors"] == 1
    assert round(s["requests"]["errorRate"], 3) == round(1 / 6, 3)


def test_the_window_forgets_old_requests():
    c = Clock()
    o = Ops(clock=c)
    o.record_request("/api/beats", 200, 100)
    c.t += 2000
    o.record_request("/api/beats", 200, 50)
    assert o.snapshot()["requests"]["total"] == 1 and o.snapshot(window_s=5000)["requests"]["total"] == 2


def test_it_counts_how_stories_were_made_and_how_much_was_verified():
    o = Ops(clock=Clock())
    ov = lambda v: {"kind": "lower_third", "provenance": {"verified": v}}  # noqa: E731
    o.record_beats({
        "beats": [{"level": 0, "overlays": [ov(True)]}, {"level": 1, "overlays": [ov(True)]}, {"level": 2, "overlays": [ov(True)]}, {"level": 0, "overlays": [ov(False)]}],
        "stats": {"cacheHits": 3, "modelCalls": 1, "hedged": 1, "inputTokens": 900, "outputTokens": 100},
    })
    n = o.snapshot()["narrative"]
    assert (n["stories"], n["modelWritten"], n["repaired"], n["template"]) == (4, 2, 1, 1)
    assert n["templateShare"] == 0.25 and n["claimsVerifiedShare"] == 0.75
    assert n["cacheHitRate"] == 0.75 and n["hedged"] == 1 and n["inputTokens"] == 900


def test_an_idle_service_reports_zeros_not_errors():
    s = Ops(clock=Clock()).snapshot()
    assert s["requests"]["total"] == 0 and s["requests"]["p95Ms"] == 0 and s["narrative"]["claimsVerifiedShare"] == 1.0 and s["narrative"]["cacheHitRate"] == 0.0


def test_paths_belong_to_one_group():
    assert group_of("/api/beats") == "beats" and group_of("/api/stream/abc/feed") == "stream" and group_of("/mcp") == "tools" and group_of("/health") == "health"
    assert group_of("/something/else") == "other"
