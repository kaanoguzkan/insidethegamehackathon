"""Broadcast-style pitch graphics: renderer-agnostic geometry from interpreter facts."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from matchmind.agents import producer
from matchmind.analytics import load_models
from matchmind.core.contracts import Cohort, Overlay
from matchmind.core.paths import league_dir
from matchmind.intel.baselines import load_baselines
from matchmind.intel.pipeline import interpret_match
from matchmind.intel.xt import XTGrid

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "overlay.schema.json").read_text())


@pytest.fixture(scope="module")
def interp(match):
    ip, out = interpret_match(match, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"), models=load_models())
    return ip, out


@pytest.fixture(scope="module")
def graphics(interp):
    ip, out = interp
    names = {pid: p["name"] for pid, p in ip.players.items()} | ip.club_short
    out_by_lang = {}
    for lang in ("en", "es", "tr"):
        c = Cohort(mode="any", language=lang)
        out_by_lang[lang] = [g for f in out.facts if (g := producer.graphic_overlay(f, c, names)) is not None]
    return out_by_lang


def test_graphics_are_produced_for_offsides_runs_line_breaks_and_shots(graphics, interp):
    kinds = {g.graphic.type for g in graphics["en"]}
    assert {"offside_line", "run", "shot_trace"} <= kinds
    assert all(g.kind == "pitch_graphic" and g.anchor.type == "pitch" for g in graphics["en"])
    assert len(graphics["en"]) == len(graphics["es"]) == len(graphics["tr"])


def test_geometry_is_in_pitch_metres(graphics):
    for g in graphics["en"]:
        assert g.graphic.shapes
        for sh in g.graphic.shapes:
            assert sh.points
            for p in sh.points:
                assert -1 <= p.x <= 106 and -1 <= p.y <= 69, (g.graphic.type, p)
            if sh.shape in ("line", "arrow"):
                assert len(sh.points) >= 2


def test_the_offside_line_is_a_vertical_line_with_the_offender_beyond_it(graphics, interp):
    ip, out = interp
    offs = [g for g in graphics["en"] if g.graphic.type == "offside_line"]
    assert offs
    facts = {f["id"]: f for f in out.facts if f["type"] == "offside_graphic"}
    for g in offs:
        line, mark = g.graphic.shapes
        assert line.points[0].x == line.points[1].x and {line.points[0].y, line.points[1].y} == {0.0, 68.0}
        assert mark.shape == "circle"
        f = facts[g.factId]
        team_dir_right = f["values"]["receiverX"] > f["values"]["lineX"]
        assert (mark.points[0].x > line.points[0].x) == team_dir_right
        assert f["values"]["marginM"] >= -0.5, "the receiver was level with or beyond the line"


def test_captions_are_localized(graphics):
    en = next(g for g in graphics["en"] if g.graphic.type == "offside_line")
    tr = next(g for g in graphics["tr"] if g.id.replace(".tr.", ".en.") == en.id.replace(".tr.", ".en."))
    assert en.content.headline == "Offside line" and tr.content.headline == "Ofsayt çizgisi"
    assert all("{" not in g.content.headline + g.content.body for lang in graphics.values() for g in lang)


def test_overlays_with_graphics_validate_against_the_schema(graphics):
    for g in graphics["en"][:20]:
        jsonschema.validate(g.model_dump(mode="json"), SCHEMA)
        Overlay.model_validate(g.model_dump(mode="json"))


def test_graphics_share_one_lane_so_they_cannot_pile_up(graphics):
    out = producer.resolve_collisions(list(graphics["en"]))
    ordered = sorted(out, key=lambda o: o.displayAt.matchMs)
    for a, b in zip(ordered, ordered[1:], strict=False):
        if a.kind == "pitch_graphic" and b.kind == "pitch_graphic":
            assert b.displayAt.matchMs >= a.displayAt.matchMs + a.durationMs or b.kind == "ticker"


def test_run_graphics_point_the_way_the_runner_went(interp, graphics):
    ip, out = interp
    facts = {f["id"]: f for f in out.facts if f["type"] == "run_card"}
    for g in graphics["en"]:
        if g.graphic.type == "run":
            a, b = g.graphic.shapes[0].points
            f = facts[g.factId]
            assert [a.x, a.y] == f["values"]["from"] and [b.x, b.y] == f["values"]["to"]
