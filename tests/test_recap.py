import asyncio

import pytest

from matchmind.agents import recap as R
from matchmind.agents import verify as V
from matchmind.agents.llm import Faults, OfflineChatClient
from matchmind.agents.team import AgentTeam
from matchmind.core.contracts import SUPPORTED_LANGUAGES, Cohort
from matchmind.core.paths import league_dir, scenarios_dir
from matchmind.intel.pipeline import interpret_match
from matchmind.intel.recap import build_pack, build_preview_pack, style_tags
from matchmind.sim.engine import simulate
from matchmind.sim.league import load_league
from matchmind.sim.scenarios import load_scenario


@pytest.fixture(scope="module")
def world():
    clubs = load_league(league_dir() / "league.json")
    sc = load_scenario(scenarios_dir() / "pressing-collapse.yaml")
    res = simulate("rc", clubs[sc.home], clubs[sc.away], seed=sc.seed, scenario=sc)
    ip, out = interpret_match(res)
    packs = {"preview": build_preview_pack(res.meta), "half_time": build_pack(ip, "half_time"), "full_time": build_pack(ip, "full_time")}
    return res, ip, {m["id"]: m for m in out.moments}, packs


COHORTS = [Cohort(mode=m, language=lang) for lang in SUPPORTED_LANGUAGES for m in ("analyst", "casual")]


@pytest.mark.parametrize("kind", ["preview", "half_time", "full_time"])
@pytest.mark.parametrize("cohort", COHORTS, ids=lambda c: c.key)
def test_every_recap_verifies(world, kind, cohort):
    res, _, moments, packs = world
    rc = R.render(packs[kind], cohort, moments)
    assert rc.headline and rc.summary and "{" not in rc.headline + rc.summary
    reg = V.Registry.from_meta(res.meta)
    issues = [i for i in V.verify_text(f"{rc.headline}. {rc.summary}", packs[kind], cohort.language, reg, "recap") if i.severity == "error"]
    assert not issues, [str(i) for i in issues]


def test_full_time_states_the_real_result_and_comeback(world):
    res, _, moments, packs = world
    pack = packs["full_time"]
    assert pack["facts"]["score"] == res.meta["score"]
    rc = R.render(pack, Cohort(mode="casual", language="en"), moments)
    final = list(res.meta["score"].values())
    assert f"{final[0]}-{final[1]}" in rc.headline
    if pack["facts"]["comeback"]:
        assert "goals down" in rc.summary


def test_half_time_only_counts_the_first_half(world):
    res, _, _, packs = world
    ht, ft = packs["half_time"], packs["full_time"]
    assert ht["detectedAt"]["matchMs"] < ft["detectedAt"]["matchMs"]
    assert sum(ht["facts"]["score"].values()) <= sum(ft["facts"]["score"].values())
    assert ht["metrics"][f"{res.meta['home']['id']}.passes"]["value"] < ft["metrics"][f"{res.meta['home']['id']}.passes"]["value"]


def test_player_of_the_match_is_a_real_participant(world):
    res, _, _, packs = world
    potm = packs["full_time"]["facts"]["potm"]
    assert potm and potm["id"] in {pid for s in ("home", "away") for pid in res.meta[s]["players"]}
    assert potm["goals"] >= 0 and potm["shots"] >= 0


def test_turning_point_prefers_decisive_stories(world):
    _, _, moments, packs = world
    tid = packs["full_time"]["facts"]["turningMoment"]
    if tid:
        assert moments[tid]["type"] in {"pressure_collapse", "pressure_surge", "red_card", "penalty", "tactical_shift", "momentum_swing"}


def test_preview_describes_styles_without_numbers_it_cannot_back(world):
    res, _, _, packs = world
    assert packs["preview"]["facts"]["styles"]["HAR"]
    assert style_tags({"press_intensity": 0.9, "press_height": 0.9, "directness": 0.1, "tempo": .5, "width": .5, "line_height": .5, "counter_bias": .1}) == ["press_high", "patient"]


def test_spanish_uses_singular_verbs_for_a_singular_team(world):
    _, _, moments, packs = world
    es = R.render(packs["preview"], Cohort(mode="casual", language="es"), moments).summary
    assert "presionan" not in es and "construyen" not in es


def test_no_pronouns_for_people(world):
    _, _, moments, packs = world
    for c in COHORTS:
        text = R.render(packs["full_time"], c, moments).summary.lower()
        if c.language == "en":
            assert not any(f" {w} " in f" {text} " for w in ("he", "she", "his", "her", "him"))


def _write(faults=None, kind="full_time", cohort=COHORTS[0], world_=None):
    res, ip, moments, packs = world_
    client = OfflineChatClient(faults or Faults())
    client.context["moments"] = moments
    reg = V.Registry.from_meta(res.meta)
    rc = asyncio.run(R.write_recap(AgentTeam(client), packs[kind], cohort, moments, reg))
    return rc, client


def test_recap_writer_agent_path_is_level_zero(world):
    rc, client = _write(world_=world)
    assert rc.provenance.fallbackLevel == 0 and rc.provenance.agents == ["recap_writer", "verifier"]
    assert "recap" in client.calls


def test_a_hallucinating_recap_writer_falls_back_to_the_template(world):
    rc, _ = _write(Faults(mode="hallucinate", tasks=frozenset({"recap"})), world_=world)
    assert rc.provenance.fallbackLevel == 2 and "99" not in rc.summary


def test_a_model_outage_still_produces_a_recap(world):
    rc, _ = _write(Faults(mode="error"), world_=world)
    assert rc.provenance.fallbackLevel == 2 and rc.summary


def test_the_preview_names_the_starting_formations_not_the_post_change_ones(clubs):
    from matchmind.intel.recap import build_preview_pack
    from matchmind.sim.engine import MatchSim

    m = MatchSim("fx", clubs["RED"], clubs["SAL"], seed=3)
    m._change_formation(0, "5-3-2")  # a tactical switch before the final whistle must not rewrite the preview
    meta = m._result().meta
    pack = build_preview_pack(meta)
    assert pack["facts"]["formations"] == {"RED": "4-4-2", "SAL": "4-1-4-1"}
