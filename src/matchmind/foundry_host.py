"""Package the newsroom as a Microsoft Foundry hosted agent and upload it.

    matchmind foundry-host            # build the zip, create a new version, wait until it is active

The zip holds ``foundry/hosted/main.py`` (the entry point), its ``requirements.txt`` (Foundry installs them: remote build),
the ``matchmind`` package and each replay package's ``moments.json`` and ``meta.json``, a few MB in all. Foundry runs it
on Python 3.13 and calls it at ``<project>/agents/<name>/endpoint/protocols/openai/responses`` (protocol 2.0.0).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

NAME = "matchmind-newsroom"
ROOT = Path(__file__).resolve().parents[2]


def build_zip(out: Path | None = None) -> Path:
    """Zip the entry point, requirements, package and replay moments. Deterministic order, no bytecode."""
    out = out or Path(tempfile.mkdtemp()) / f"{NAME}.zip"
    files: list[tuple[Path, str]] = [(ROOT / "foundry/hosted/main.py", "main.py"), (ROOT / "foundry/hosted/requirements.txt", "requirements.txt")]
    for p in sorted((ROOT / "src/matchmind").rglob("*.py")):
        files.append((p, f"src/matchmind/{p.relative_to(ROOT / 'src/matchmind').as_posix()}"))
    for d in sorted((ROOT / "data/replays").iterdir()):
        for name in ("moments.json", "meta.json"):
            if (d / name).exists():
                files.append((d / name, f"data/replays/{d.name}/{name}"))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in files:
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))  # a fixed time: the same files give the same hash
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o100644 << 16  # a regular file, mode 644: the extractor checks the type bits
            z.writestr(info, src.read_bytes())
    return out


def deploy(endpoint: str | None = None, model: str | None = None, wait_s: int = 600) -> dict[str, Any]:
    """Upload a new version of the hosted agent and wait until Foundry reports it active (or failed)."""
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import (
        CodeConfiguration,
        HostedAgentDefinition,
        ProtocolVersionRecord,
    )
    from azure.identity import DefaultAzureCredential

    endpoint = endpoint or os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = model or os.environ.get("MATCHMIND_LLM_MODEL", "gpt-4.1-mini")
    zpath = build_zip()
    definition = HostedAgentDefinition(
        cpu="1", memory="2Gi",
        environment_variables={"FOUNDRY_PROJECT_ENDPOINT": endpoint, "MATCHMIND_LLM_MODEL": model, "MATCHMIND_LLM": "foundry", "MATCHMIND_AGENT_TIMEOUT_S": "30"},
        code_configuration=CodeConfiguration(runtime="python_3_13", entry_point=["python", "main.py"], dependency_resolution="remote_build"),
        protocol_versions=[ProtocolVersionRecord(protocol="responses", version="2.0.0")],
    )
    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    with zpath.open("rb") as f:
        v = project.agents.create_version_from_code(
            NAME, definition=definition, code=f, description="The MatchMind newsroom: verified, personalized overlays for chosen moments.",
            metadata={"app": "matchmind", "zipSha256": hashlib.sha256(zpath.read_bytes()).hexdigest()[:32]},
        )
    version, status, t0 = str(v.version), str(getattr(v, "status", "")), time.monotonic()
    while "active" not in status.lower() and "fail" not in status.lower() and time.monotonic() - t0 < wait_s:
        time.sleep(10)
        status = str(project.agents.get_version(agent_name=NAME, agent_version=version).status)
    shutil.rmtree(zpath.parent, ignore_errors=True)
    return {"name": NAME, "version": version, "status": status, "zipBytes": zpath.stat().st_size if zpath.exists() else None}
