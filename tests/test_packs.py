"""Match packs: a simulation stored once and played from storage, with the feed and the chunks it would have had straight from the simulation."""

from __future__ import annotations

import json

import pytest

from matchmind.live import feed
from matchmind.live.blobs import MemoryBlobs
from matchmind.live.packs import read_pack, write_pack
from matchmind.tracking.frames import encode_chunk, iter_chunks


@pytest.fixture(scope="module")
def stored(match):
    blobs = MemoryBlobs()
    size = write_pack(blobs, "s1/f01", match)
    return blobs, size


def test_a_pack_is_a_few_megabytes_and_has_four_parts(stored):
    blobs, size = stored
    assert sorted(n.split("/")[-1] for n in blobs.puts) == ["events.json.gz", "meta.json", "slots.json", "tracking.bin.gz"]
    assert 1_000_000 < size < 4_000_000


def test_the_feed_from_a_pack_is_the_feed_from_the_simulation(match, stored):
    pack = read_pack(stored[0], "s1/f01")
    assert pack is not None and pack.match_id == match.meta["matchId"]
    assert json.dumps(pack.feed(), sort_keys=True) == json.dumps(feed.build_feed(match, physical="chunks"), sort_keys=True)


def test_the_chunks_from_a_pack_are_the_chunks_from_the_simulation_byte_for_byte(match, stored):
    pack = read_pack(stored[0], "s1/f01")
    assert pack is not None and len(pack.chunks()) == len(match.chunk_slots) == pack.n_chunks
    for ch, ref in zip(range(pack.n_chunks), iter_chunks(match), strict=True):
        assert encode_chunk(pack.chunk(ch)) == encode_chunk(ref), ch  # both rounded to 0.1 m, so they agree exactly
    end_ms, name, data = pack.chunks()[2]
    assert end_ms == 15_000 and name == f"{match.meta['matchId']}/00002.json.gz" and data == encode_chunk(next(c for c in iter_chunks(match) if c.index == 2))


def test_a_pack_can_be_played_under_another_match_id(match, stored):
    pack = read_pack(stored[0], "s1/f01")
    assert pack is not None
    _, name, data = pack.chunks("live-x-1")[0]
    assert name == "live-x-1/00000.json.gz"
    import gzip

    assert json.loads(gzip.decompress(data))["matchId"] == "live-x-1"


def test_a_pack_that_is_missing_a_part_is_not_played(stored):
    blobs, _ = stored
    partial = MemoryBlobs()
    for n in ("meta.json", "events.json.gz"):
        partial.put(f"p/{n}", blobs.get(f"s1/f01/{n}") or b"")
    assert read_pack(partial, "p") is None and read_pack(MemoryBlobs(), "nothing") is None
