"""The five deviations that turn the reference simulator into the agent's starter.

Each deviation is a real lockstep desync class. Every patch is a literal string
replacement asserted to apply exactly once, so the starter provably differs from
the reference in exactly these five places and nowhere else.

Deviation classes, in the order a debugger is likely to meet them:

  B2  candidate ordering        target acquisition walks the lane container in
                                storage order instead of ascending entity id, so
                                a distance tie resolves to whichever entity a
                                previous swap-remove happened to leave in front.
  B3  RNG consumption order     an attack whose cached target already died this
                                tick returns before drawing its crit value and
                                before arming its cooldown, so the shared random
                                stream falls out of step.
  B5  effect expiry phase       shield and armor-shred expiry is processed after
                                the attack phase instead of before it, so an
                                effect that should have ended still applies for
                                one more tick.
  B1  division rounding         integer division floors instead of truncating
                                toward zero, which only shows once an operand
                                goes negative with a remainder.
  B4  register width            the team damage scoreboard accumulates in an
                                unbounded integer instead of a 32-bit register,
                                so it never wraps.
"""

from __future__ import annotations

STARTER_HEADER = '''"""Lane Siege v1 simulator (starter).

This build does not reproduce recorded replays. It is the starting point for
the task: see input/SPEC.md for the normative rules and input/replays/ for the
recorded matches it fails to reproduce.

CLI contract:

    python3 sim.py <replay.json>

writes one line per checkpoint tick to stdout:

    <tick> <16-hex-digit state hash>
"""
'''

PATCHES: list[tuple[str, str, str]] = [
    (
        "B1",
        '''def tdiv(n: int, d: int) -> int:
    """Integer division truncating toward zero (C99 semantics, not Python floor)."""
    q = abs(n) // abs(d)
    return -q if (n < 0) != (d < 0) else q''',
        '''def tdiv(n: int, d: int) -> int:
    """Integer division."""
    return n // d''',
    ),
    (
        "B2",
        '''        return [sorted(lane, key=lambda o: o.eid) for lane in self.lanes]''',
        '''        return [list(lane) for lane in self.lanes]''',
    ),
    (
        "B3",
        '''            crit = self.rng.range(100) < CRIT_PERCENT
            e.atk_cd = e.atk_period
            dst = self.entities.get(e.target)
            if dst is None or not dst.alive or dst.hp <= 0:
                continue
            self._damage(e, dst, e.atk, crit)''',
        '''            dst = self.entities.get(e.target)
            if dst is None or not dst.alive or dst.hp <= 0:
                continue
            crit = self.rng.range(100) < CRIT_PERCENT
            e.atk_cd = e.atk_period
            self._damage(e, dst, e.atk, crit)''',
    ),
    (
        "B4",
        '''        self.team_dmg[src.team] = wrap32(self.team_dmg[src.team] + dmg)''',
        '''        self.team_dmg[src.team] = self.team_dmg[src.team] + dmg''',
    ),
    (
        "B5a",
        '''            if e.shield_ticks > 0:
                e.shield_ticks -= 1
                if e.shield_ticks == 0:
                    e.shield = 0
            if e.shred_ticks > 0:
                e.shred_ticks -= 1
                if e.shred_ticks == 0:
                    e.armor = wrap32(e.armor + SHRED_AMOUNT * e.shred_stacks)
                    e.shred_stacks = 0
            if e.kind == KIND_HERO:''',
        '''            if e.kind == KIND_HERO:''',
    ),
    (
        "B5b",
        '''    def _phase_projectiles(self) -> None:''',
        '''    def _phase_expiry(self) -> None:
        for eid in sorted(self.entities):
            e = self.entities[eid]
            if e.kind == KIND_PROJ or not e.alive:
                continue
            if e.shield_ticks > 0:
                e.shield_ticks -= 1
                if e.shield_ticks == 0:
                    e.shield = 0
            if e.shred_ticks > 0:
                e.shred_ticks -= 1
                if e.shred_ticks == 0:
                    e.armor = wrap32(e.armor + SHRED_AMOUNT * e.shred_stacks)
                    e.shred_stacks = 0

    def _phase_projectiles(self) -> None:''',
    ),
    (
        "B5c",
        '''        self._phase_attack()
        self._phase_deaths()''',
        '''        self._phase_attack()
        self._phase_expiry()
        self._phase_deaths()''',
    ),
]

# Which patches belong to which named deviation, for per-bug isolation studies.
GROUPS: dict[str, tuple[str, ...]] = {
    "B1": ("B1",),
    "B2": ("B2",),
    "B3": ("B3",),
    "B4": ("B4",),
    "B5": ("B5a", "B5b", "B5c"),
}


def apply(source: str, only: tuple[str, ...] | None = None) -> str:
    """Return ``source`` with the selected patches applied.

    ``only`` selects patch ids; the default applies all of them. Every selected
    patch must match exactly once, otherwise the reference has drifted away from
    the patch table and the build must fail rather than ship a starter that
    differs in unintended places.
    """
    out = source
    for pid, old, new in PATCHES:
        if only is not None and pid not in only:
            continue
        count = out.count(old)
        if count != 1:
            raise AssertionError(f"patch {pid}: expected exactly 1 match, found {count}")
        out = out.replace(old, new)
    return out


def make_starter(reference_source: str) -> str:
    """Full starter: all deviations applied, reference docstring swapped out."""
    body = apply(reference_source)
    _head, sep, rest = body.partition('"""')
    if not sep:
        raise AssertionError("reference source has no module docstring to replace")
    _doc, sep2, tail = rest.partition('"""')
    if not sep2:
        raise AssertionError("reference module docstring is not terminated")
    return STARTER_HEADER + tail.lstrip("\n")
