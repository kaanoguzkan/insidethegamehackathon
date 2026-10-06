"""The printable match report: it builds from a committed replay package and says what the data says."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from matchmind.core.paths import replays_dir
from matchmind.report import build_report
from matchmind.sim import tactics as TA


@pytest.fixture(scope="module")
def pdf(tmp_path_factory) -> tuple[PdfReader, str, dict]:
    pkg = replays_dir() / "pressing-collapse"
    out = build_report(pkg, tmp_path_factory.mktemp("rep") / "r.pdf")
    reader = PdfReader(str(out))
    text = "\n".join(p.extract_text() for p in reader.pages)
    return reader, text, json.loads((pkg / "meta.json").read_text())


def test_the_report_is_a_real_multi_page_pdf(pdf):
    reader, text, _ = pdf
    assert len(reader.pages) >= 12
    assert reader.metadata.title.startswith("Harbour City v Northbridge")


def test_it_has_every_part(pdf):
    _, text, _ = pdf
    for heading in ("The story of the match", "Tactics: the same team with and without the ball", "Every position, and who played it",
                    "The analytics, view by view", "Every player", "All nine formations compared", "What to trust"):
        assert heading in text, heading


def test_every_position_and_player_in_the_lineup_is_explained(pdf):
    _, text, meta = pdf
    flat = " ".join(text.split())
    for side in ("home", "away"):
        team = meta[side]
        for pid in team["lineup"]:
            assert team["players"][pid]["name"] in flat, f"{pid} is missing from the position tables"
        for role in ["GK", *TA.roles(team["startFormation"])]:
            assert role in flat
    assert "Goalkeeper" in flat and "Centre-back" in flat and "Striker" in flat


def test_each_phase_and_each_analytics_view_is_covered(pdf):
    _, text, _ = pdf
    flat = " ".join(text.split())
    for phase in ("Build-up", "Settled attack", "Press", "Mid block", "Low block"):
        assert phase in flat
    for view in ("Win probability", "Shots and expected goals", "Possession value", "Space and pitch control", "Packing and line-breaking passes",
                 "Passing networks", "Off-ball runs", "Physical load", "Transitions and pressing", "Set pieces", "Goalkeepers", "Season context"):
        assert view in flat, view
    assert "no number in this report was written" in flat.lower().replace("\n", " ") or "no number in this report" in flat


def test_the_numbers_match_the_package(pdf):
    _, text, meta = pdf
    pkg = replays_dir() / "pressing-collapse"
    a = json.loads((pkg / "analytics.json").read_text())
    flat = " ".join(text.split())
    h, aw = meta["home"]["id"], meta["away"]["id"]
    assert f"{a['shots']['teams'][h]['xg']:.2f}" in flat and f"{a['shots']['teams'][aw]['xg']:.2f}" in flat
    assert f"{meta['score'][h]} - {meta['score'][aw]}" in flat


def test_the_committed_replays_ship_a_report():
    for pkg in Path(replays_dir()).iterdir():
        if (pkg / "meta.json").exists():
            assert (pkg / "report.pdf").exists(), f"{pkg.name}: run matchmind build-pdf"
