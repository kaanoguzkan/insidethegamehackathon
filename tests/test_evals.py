import pytest

from matchmind.core.paths import replays_dir
from matchmind.evals import GATES, evaluate_all, gate, number_density, readability


@pytest.fixture(scope="module")
def reports():
    return evaluate_all(replays_dir())


def test_every_committed_package_passes_every_quality_gate(reports):
    assert len(reports) >= 3
    fails = [f for r in reports for f in gate(r)]
    assert not fails, fails


def test_personalization_is_real_not_cosmetic(reports):
    for r in reports:
        s = r["personaSeparation"]
        assert s["pairs"] > 10
        assert s["analyst_number_density"] > 2 * s["casual_number_density"], "analyst text should be far denser in numbers"


def test_a_gate_actually_trips_when_quality_drops(reports):
    bad = {**reports[0], "numericFidelity": 0.97}
    assert any("numericFidelity" in f for f in gate(bad))
    bad = {**reports[0], "honesty": {"mixedEvidenceMoments": 2, "admitted": 1, "rate": 0.5}}
    assert any("not admitted" in f for f in gate(bad))
    assert set(GATES) == {"numericFidelity", "verificationRate", "languageCorrectness"}


def test_helper_metrics_behave():
    assert number_density("12 shots and 3 goals") > number_density("lots of shots and goals") == 0
    assert readability("Northbridge's counter-pressing structure collapsed.") > readability("They gave up.")
