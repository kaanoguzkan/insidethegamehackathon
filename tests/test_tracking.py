import numpy as np

from matchmind.tracking.analyzer import PhysicalAnalyzer, analyze_match
from matchmind.tracking.frames import decode_chunk, encode_chunk, iter_chunks


def test_chunk_roundtrip_keeps_positions_to_a_decimetre(match):
    for chunk in list(iter_chunks(match))[:20]:
        back = decode_chunk(encode_chunk(chunk))
        assert back.index == chunk.index and back.slots == chunk.slots
        assert np.allclose(back.frames, chunk.frames, atol=0.06, equal_nan=True)
        assert np.array_equal(back.alive, chunk.alive)


def test_chunks_are_small_enough_to_stream(match):
    sizes = [len(encode_chunk(c)) for c in list(iter_chunks(match))[:30]]
    assert max(sizes) < 8_000  # a 5 s chunk stays in the low kilobytes


def test_every_pass_and_shot_is_enriched_once(match):
    out = analyze_match(match)
    wanted = {e["id"] for e in match.events if e["type"] in ("pass", "shot")}
    got = [d["ref"] for d in out.enrichments]
    assert set(got) == wanted
    assert len(got) == len(set(got))


def test_ball_speeds_are_physically_plausible(match):
    out = analyze_match(match)
    passes = [d["physics"] for d in out.enrichments if "ballSpeedKmh" in d["physics"]]
    shots = [d["physics"] for d in out.enrichments if "shotSpeedKmh" in d["physics"]]
    speeds = [p["ballSpeedKmh"] for p in passes if p["ballSpeedKmh"] is not None]
    assert 30 < np.mean(speeds) < 90 and max(speeds) < 140
    s = [p["shotSpeedKmh"] for p in shots if p["shotSpeedKmh"] is not None]
    assert 50 < np.mean(s) < 130 and max(s) < 160
    for p in passes:
        assert 0.0 <= p["pressurePasser"] <= 1.0 and 0.0 <= p["laneBlock"] <= 1.0


def test_sprints_and_top_speeds_obey_thresholds(match):
    out = analyze_match(match)
    sprints = [e for e in out.events if e["type"] == "sprint"]
    assert sprints
    assert all(e["attributes"]["peakKmh"] >= 25.0 for e in sprints)
    assert all(e["attributes"]["peakKmh"] < 40.0 for e in sprints)
    assert all(e["attributes"]["distanceM"] > 3.0 for e in sprints)
    tops = [e for e in out.events if e["type"] == "top_speed"]
    assert all(e["attributes"]["peakKmh"] >= 32.0 for e in tops)


def test_team_shape_snapshots_every_30_seconds(match):
    out = analyze_match(match)
    har = [e for e in out.events if e["type"] == "team_shape" and e["team"] == "HAR"]
    gaps = np.diff([e["clock"]["matchMs"] for e in har])
    assert set(gaps.tolist()) <= {30_000}
    a = har[40]["attributes"]
    assert 3 < a["lineHeightM"] < 80 and 15 < a["widthM"] < 70


def test_streaming_matches_batch(match):
    """Feeding chunks one at a time, as the Azure Function does, gives the same facts."""
    batch = analyze_match(match)
    an = PhysicalAnalyzer(match.meta)
    an.add_events(match.events)
    events, enrich = [], []
    for ch in iter_chunks(match):
        out = an.process_chunk(ch)
        events += out.events
        enrich += out.enrichments
    out = an.flush()
    events += out.events
    enrich += out.enrichments
    assert sorted(e["id"] for e in events) == sorted(e["id"] for e in batch.events)
    assert {d["ref"]: d["physics"] for d in enrich} == {d["ref"]: d["physics"] for d in batch.enrichments}


def test_bundle_roundtrip_and_size(match):
    import json

    from matchmind.tracking import bundle

    data = bundle.encode(match)
    pos, ball, hz = bundle.decode(data)
    n = match.meta["frames"]
    assert pos.shape == (n, 22, 2) and ball.shape == (n, 4) and hz == 5
    assert np.allclose(pos, match.frames[:n], atol=0.06, equal_nan=True)
    assert np.array_equal(ball[:, 3] > 0.5, match.ball[:n, 3] > 0.5)
    assert len(data) < 3_000_000, "a whole match should be a couple of megabytes"
    table = bundle.slot_table(match)
    assert table[0]["fromFrame"] == 0 and all(len(r["ids"]) == 22 for r in table)
    assert len(table) > 1, "substitutions must show up as slot changes"
    assert json.dumps(table)


def test_encoded_files_are_byte_reproducible(match):
    """gzip headers carry a timestamp; without mtime=0 every rebuild would churn the committed packages."""
    from matchmind.tracking import bundle
    from matchmind.tracking.frames import encode_chunk, iter_chunks

    assert bundle.encode(match) == bundle.encode(match)
    ch = next(iter(iter_chunks(match)))
    assert encode_chunk(ch) == encode_chunk(ch)
