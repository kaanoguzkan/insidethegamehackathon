import json
from pathlib import Path

import jsonschema
import pytest

from matchmind.core.contracts import Cohort, Overlay, Profile, schema_models

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


@pytest.mark.parametrize("name,model", sorted(schema_models().items()))
def test_committed_schema_matches_the_model(name, model):
    """If a contract changes, regenerate with `matchmind export-schemas` and commit the result."""
    committed = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    assert committed == json.loads(json.dumps(model.model_json_schema(), sort_keys=True))


def test_a_real_overlay_validates_against_its_json_schema():
    from matchmind.core.contracts import DisplayAt, OverlayContent

    o = Overlay(id="x", matchId="m", kind="lower_third", displayAt=DisplayAt(matchMs=1), cohort=Cohort(), content=OverlayContent(headline="h"))
    schema = json.loads((SCHEMAS / "overlay.schema.json").read_text())
    jsonschema.validate(o.model_dump(mode="json"), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**o.model_dump(mode="json"), "kind": "mystery"}, schema)


def test_profile_maps_to_a_cohort_and_cohorts_cover_viewers():
    p = Profile(profileId="a", mode="casual", language="es", perspective="HAR")
    assert p.cohort().key == "casual/es/HAR/-"
    shared = Cohort(mode="any", language="es")
    assert shared.covers(p.cohort())
    assert not Cohort(mode="any", language="en").covers(p.cohort())
    assert Cohort(mode="casual", language="es", perspective="HAR").covers(p.cohort())
    assert not Cohort(mode="analyst", language="es").covers(p.cohort())
    assert not Cohort(mode="casual", language="es", perspective="NOR").covers(p.cohort())
    focus = Cohort(mode="casual", language="es", focusPlayer="HAR-09")
    assert not focus.covers(p.cohort())
