import json

import pytest

from matchmind.agents.verify import Registry, verify_text
from matchmind.core.contracts import Cohort, Overlay
from matchmind.core.paths import league_dir, scenarios_dir
from matchmind.runner import build_replay, default_cohorts, write_replay
from matchmind.sim.engine import simulate
from matchmind.sim.league import load_league
from matchmind.sim.scenarios import load_scenario


@pytest.fixture(scope="module")
def built():
    clubs = load_league(league_dir() / "league.json")
    sc = load_scenario(scenarios_dir() / "pressing-collapse.yaml")
    res = simulate("rt", clubs[sc.home], clubs[sc.away], seed=sc.seed, scenario=sc)
    return res, build_replay(res)


def test_replay_covers_every_default_cohort(built):
    res, replay = built
    assert [c.key for c in replay.cohorts] == [c.key for c in default_cohorts(res.meta)]
    keys = {o.cohort.key for o in replay.overlays if o.kind == "lower_third"}
    assert {c.key for c in replay.cohorts} == keys, "every cohort must receive the story overlays"
    assert len({c.language for c in replay.cohorts}) == 3


def test_the_scripted_story_is_told_in_every_language(built):
    _, replay = built
    pc = next(m for m in replay.moments if m["type"] == "pressure_collapse" and m["subjectTeam"] == "NOR")
    mine = [o for o in replay.overlays if o.momentId == pc["id"]]
    assert {o.cohort.language for o in mine} == {"en", "es", "tr"}
    assert all(o.provenance.verified and o.provenance.evidenceRef == pc["id"] for o in mine)
    assert pc["level"] == 0 and [t["agent"] for t in pc["trace"]][:3] == ["editor", "explainer", "verifier"]


def test_every_overlay_is_valid_unique_and_safe_as_a_document_id(built):
    _, replay = built
    ids = [o.id for o in replay.overlays]
    assert len(ids) == len(set(ids))
    assert not any(c in i for i in ids for c in "/\\?#")
    for o in replay.overlays:
        Overlay.model_validate(o.model_dump())


def test_all_narrative_text_passes_the_verifier(built):
    res, replay = built
    reg = Registry.from_meta(res.meta)
    packs = {m["id"]: m for m in replay.moments}
    for o in replay.overlays:
        if o.kind in ("lower_third", "ticker") and o.momentId in packs:
            issues = verify_text(f"{o.content.headline}. {o.content.body}", packs[o.momentId], o.cohort.language, reg)
            assert not [i for i in issues if i.severity == "error"], (o.id, [str(i) for i in issues])


def test_lower_thirds_do_not_overlap_per_cohort(built):
    _, replay = built
    by: dict[str, list[Overlay]] = {}
    for o in replay.overlays:
        if o.kind == "lower_third":
            by.setdefault(o.cohort.key, []).append(o)
    for items in by.values():
        spans = sorted((o.displayAt.matchMs, o.displayAt.matchMs + o.durationMs) for o in items)
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_stat_graphics_are_shared_across_modes(built):
    _, replay = built
    stat = [o for o in replay.overlays if o.kind in ("shot_card", "speed_badge", "momentum_bar")]
    assert stat and all(o.cohort.mode == "any" for o in stat)
    viewer = Cohort(mode="analyst", language="tr")
    assert any(o.cohort.covers(viewer) for o in stat)


def test_package_files_are_complete_and_loadable(built, tmp_path):
    res, replay = built
    out = write_replay(replay, res, tmp_path / "pkg")
    manifest = json.loads((out / "manifest.json").read_text())
    for name in manifest["files"]:
        assert (out / name).stat().st_size > 2
    assert manifest["chunks"] == len(list((out / "tracking").glob("*.json.gz")))
    meta = json.loads((out / "meta.json").read_text())
    assert meta["package"]["version"] == "1" and meta["matchId"] == "rt"
    events = json.loads((out / "events.json").read_text())
    ev_ids = {e["id"] for e in events}
    for m in replay.moments:
        assert set(m["eventIds"]) <= ev_ids, "every cited event must be in the package"


def test_building_twice_gives_identical_packages(built):
    res, replay = built
    again = build_replay(res)
    strip = lambda r: [(o.id, o.content.headline, o.content.body, o.displayAt.matchMs) for o in r.overlays]  # noqa: E731
    assert strip(again) == strip(replay)
