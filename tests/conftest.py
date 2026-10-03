import pytest

from matchmind.sim.engine import simulate
from matchmind.sim.league import generate_league


@pytest.fixture(scope="session")
def clubs():
    return generate_league()


@pytest.fixture(scope="session")
def match(clubs):
    """One full simulated match, shared across tests (about 3 seconds to build)."""
    return simulate("t0001", clubs["HAR"], clubs["NOR"], seed=42)
