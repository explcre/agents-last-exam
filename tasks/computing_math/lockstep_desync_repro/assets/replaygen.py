"""Generate Lane Siege replays by driving the reference simulator with a scripted policy.

A replay is the recorded command stream only. Replaying it open loop through the
reference simulator must reproduce the recording bit for bit; build_data.py
asserts that for every replay it ships.

The policy RNG is a separate stream from the simulation RNG. Touching the
simulation RNG here would make the recorded commands depend on the simulation's
own random draws in a way the replay could not reproduce.
"""

from __future__ import annotations

import sim_reference as R


class PolicyRng:
    """Same xorshift32 as the simulation, on an independent stream."""

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF or 0x2545F491

    def next_u32(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x

    def range(self, n: int) -> int:
        return self.next_u32() % n


def _policy_commands(sim: R.Sim, prng: PolicyRng, stance: list[int], tick: int) -> list[list[int]]:
    """Decide this tick's commands. Deterministic given (sim state, prng, tick)."""
    out: list[list[int]] = []
    for slot, hero in enumerate(sim.heroes):
        if not hero.alive:
            continue
        has_target = hero.target != 0
        low = hero.hp * 10 < hero.max_hp * 4

        if tick % 60 == 0:
            if low:
                want = R.CMD_RETREAT
            elif hero.hp * 10 > hero.max_hp * 7:
                want = R.CMD_PUSH if prng.range(10) < 9 else R.CMD_HOLD
            else:
                want = stance[slot]
            if want != stance[slot]:
                stance[slot] = want
                out.append([tick, slot, want, 0])

        if has_target and hero.ability_cd[0] == 0:
            out.append([tick, slot, R.CMD_BOLT, 0])
        # Shred is cast on cooldown whenever a target is in range. Repeated
        # stacks are what drive an entity's armor negative, which is the only
        # way the negative-operand division path is ever exercised.
        if has_target and hero.ability_cd[1] == 0:
            out.append([tick, slot, R.CMD_SHRED, 0])
        if hero.ability_cd[2] == 0 and hero.hp * 10 < hero.max_hp * 6:
            out.append([tick, slot, R.CMD_WARD, 0])

        if tick % 900 == 0 and prng.range(3) == 0:
            out.append([tick, slot, R.CMD_LANE, prng.range(2)])
    return out


def generate(seed: int, policy_seed: int, ticks: int = R.TICKS_PER_MATCH) -> dict:
    """Record one replay. Returns the replay dict; hashes are computed separately."""
    sim = R.Sim(seed)
    prng = PolicyRng(policy_seed)
    stance = [R.CMD_HOLD] * 4
    commands: list[list[int]] = []
    for t in range(1, ticks + 1):
        cmds = _policy_commands(sim, prng, stance, t)
        commands.extend(cmds)
        sim.step(cmds)
    return {
        "version": 1,
        "seed": seed,
        "policy_seed": policy_seed,
        "ticks": ticks,
        "checkpoints": list(R.CHECKPOINTS),
        "commands": commands,
    }
