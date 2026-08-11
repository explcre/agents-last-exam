"""Per-deviation first-divergence measurement, used to place the checkpoints.

Placement matters: the checkpoint ticks decide what an unmodified starter scores
and whether partial credit forms a ladder rather than a cliff. Run this whenever
the rules or the balance constants change.

    python3 diagnose.py [n_replays]
"""

from __future__ import annotations

import pathlib
import sys
import types

import bugs
import replaygen as G
import sim_reference as R

REF_SRC = pathlib.Path(__file__).with_name("sim_reference.py").read_text(encoding="utf-8")
DENSE = list(range(25, R.TICKS_PER_MATCH + 1, 25))

# Seed pairs for the shipped replay set. Index 0-2 are agent visible, 3-7 held out.
SEEDS: list[tuple[int, int]] = [
    (0x1234ABCD, 0x00C0FFEE),
    (0x0BADC0DE, 0x005EED01),
    (0x51DE1CE5, 0x00A11CE0),
    (0x7E571234, 0x00FACADE),
    (0x2B1D5EED, 0x00D15EA5),
    (0x600D5EED, 0x00BEEF01),
    (0x1A2B3C4D, 0x00C0DE99),
    (0x0FEDCBA9, 0x00ABCDEF),
]


def load_module(src: str, name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    exec(compile(src, name, "exec"), mod.__dict__)  # noqa: S102 - loading a patched build is the point
    return mod


def hashes(mod: types.ModuleType, replay: dict, ticks: list[int]) -> dict[int, str]:
    sim = mod.Sim(replay["seed"])
    by_tick: dict[int, list[list[int]]] = {}
    for c in replay["commands"]:
        by_tick.setdefault(c[0], []).append(c)
    want = set(ticks)
    out: dict[int, str] = {}
    for t in range(1, replay["ticks"] + 1):
        sim.step(by_tick.get(t, []))
        if t in want:
            out[t] = sim.hash_state()
    return out


def first_divergence(mod_hashes: dict[int, str], ref_hashes: dict[int, str]) -> int | None:
    for t in sorted(ref_hashes):
        if mod_hashes.get(t) != ref_hashes[t]:
            return t
    return None


def main(argv: list[str]) -> int:
    n = int(argv[1]) if len(argv) > 1 else 3
    variants = {name: load_module(bugs.apply(REF_SRC, only=ids), f"m_{name}")
                for name, ids in bugs.GROUPS.items()}
    variants["ALL"] = load_module(bugs.make_starter(REF_SRC), "m_all")

    print(f"{'replay':>7} " + " ".join(f"{k:>6}" for k in variants))
    agg: dict[str, list[int | None]] = {k: [] for k in variants}
    for i in range(n):
        seed, pseed = SEEDS[i]
        replay = G.generate(seed, pseed)
        replay["checkpoints"] = DENSE
        ref = hashes(R, replay, DENSE)
        row = []
        for name, mod in variants.items():
            t = first_divergence(hashes(mod, replay, DENSE), ref)
            agg[name].append(t)
            row.append("never" if t is None else str(t))
        print(f"{i:>7} " + " ".join(f"{v:>6}" for v in row))

    print()
    for name, ticks in agg.items():
        fired = [t for t in ticks if t is not None]
        status = f"fires in {len(fired)}/{len(ticks)}"
        if fired:
            status += f", earliest {min(fired)}, latest {max(fired)}"
        print(f"  {name:<4} {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
