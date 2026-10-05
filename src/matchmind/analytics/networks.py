"""Passing networks: who passes to whom, and from where.

Nodes sit at a player's average pass position (attack frame, so both teams read left to right) and
are sized by passes made. Edges are completed passes between a pair. Like the networks on Opta's and
Wyscout's match pages, this shows the team's shape in possession and who carries the build-up.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np


def passing_network(
    events: list[dict], club: str, players: dict[str, dict], t0: int = 0, t1: int = 10**12, min_edge: int = 2,
) -> dict:
    nodes: dict[str, list[tuple[float, float]]] = defaultdict(list)
    made: Counter = Counter()
    edges: Counter = Counter()
    lengths: list[float] = []
    for e in events:
        if e["type"] != "pass" or e.get("team") != club or not (t0 < e["_ms"] <= t1) or "_ax" not in e:
            continue
        p = e["player"]
        made[p] += 1
        nodes[p].append((e["_ax"], e["_ay"]))
        if e.get("outcome") == "complete" and e.get("receiver") and "_eax" in e:
            edges[(p, e["receiver"])] += 1
            nodes[e["receiver"]].append((e["_eax"], e["_eay"]))
            lengths.append(float(np.hypot(e["_eax"] - e["_ax"], e["_eay"] - e["_ay"])))
    out_nodes = []
    for pid, pts in nodes.items():
        if made[pid] == 0 and len(pts) < 3:
            continue
        arr = np.array(pts)
        out_nodes.append({
            "id": pid, "name": players.get(pid, {}).get("name"), "pos": players.get(pid, {}).get("pos"),
            "x": round(float(arr[:, 0].mean()), 1), "y": round(float(arr[:, 1].mean()), 1), "passes": int(made[pid]),
        })
    out_nodes.sort(key=lambda n: -n["passes"])
    keep = {n["id"] for n in out_nodes}
    pair: Counter = Counter()
    for (a, b), n in edges.items():
        pair[tuple(sorted((a, b)))] += n
    out_edges = [
        {"a": a, "b": b, "n": n} for (a, b), n in pair.most_common() if n >= min_edge and a in keep and b in keep
    ]
    strongest = out_edges[0] if out_edges else None
    return {
        "club": club,
        "nodes": out_nodes,
        "edges": out_edges,
        "stats": {
            "completedPasses": int(sum(edges.values())),
            "avgPassLengthM": round(float(np.mean(lengths)), 1) if lengths else None,
            "strongestLink": strongest,
            "avgX": round(float(np.mean([n["x"] for n in out_nodes])), 1) if out_nodes else None,
        },
    }
