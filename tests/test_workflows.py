"""The GitHub Actions workflows must at least be valid YAML with the shape Actions expects.

A workflow GitHub cannot parse does not fail a step, it fails the whole run in 0 seconds with no log,
which is easy to miss. (A step name containing ": " once did exactly that.)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_yaml_with_jobs(path):
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict) and doc.get("name"), f"{path.name} needs a name"
    assert True in doc or "on" in doc, "a workflow needs a trigger (YAML reads the key `on` as True)"
    jobs = doc["jobs"]
    assert jobs
    for name, job in jobs.items():
        assert "runs-on" in job, f"{path.name}: job {name} has no runs-on"
        for step in job.get("steps", []):
            assert "uses" in step or "run" in step, f"{path.name}: a step in {name} does nothing"


def test_third_party_actions_are_pinned_to_commit_shas():
    import re

    for path in WORKFLOWS:
        for line in path.read_text().splitlines():
            m = re.search(r"uses:\s*([\w.-]+/[\w./-]+)@(\S+)", line)
            if m and not m.group(1).startswith(("actions/", "./")):
                assert re.fullmatch(r"[0-9a-f]{40}", m.group(2)), f"{path.name}: {m.group(1)} is not pinned to a commit SHA"
