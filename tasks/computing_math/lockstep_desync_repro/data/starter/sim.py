"""Lane Siege v1 simulator (starter).

This build does not reproduce recorded replays. It is the starting point for
the task: see input/SPEC.md for the normative rules and input/replays/ for the
recorded matches it fails to reproduce.

CLI contract:

    python3 sim.py <replay.json>

writes one line per checkpoint tick to stdout:

    <tick> <16-hex-digit state hash>
"""
from __future__ import annotations

import json
import sys

# --- fixed-point core ---------------------------------------------------------

ONE = 65536
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1


def wrap32(x: int) -> int:
    """Reduce an arbitrary integer to a signed 32-bit two's-complement value."""
    return ((x + 2**31) & 0xFFFFFFFF) - 2**31


def tdiv(n: int, d: int) -> int:
    """Integer division."""
    return n // d


def fx_mul(a: int, b: int) -> int:
    return wrap32(tdiv(a * b, ONE))


# --- deterministic RNG --------------------------------------------------------


class Xorshift32:
    """xorshift32. One global stream; consumption order is part of the spec."""

    __slots__ = ("state",)

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF
        if self.state == 0:
            self.state = 0x9E3779B9

    def next_u32(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x

    def range(self, n: int) -> int:
        return self.next_u32() % n


# --- constants (all Q16.16 raw integers; see SPEC.md section 3) ---------------

LANE_LEN = 4096 * ONE
TICKS_PER_MATCH = 9000
# Scored checkpoints: a uniform eighth-of-match grid, deliberately not placed
# relative to where any particular deviation happens to fire.
CHECKPOINTS = (1125, 2250, 3375, 4500, 5625, 6750, 7875, 9000)
# Gate checkpoints: a different tick set, published nowhere. The gate re-runs the
# agent-visible replays on these ticks so a submission that hard-codes the
# published hashes fails the gate instead of passing it.
# The gate covers the first ~44% of a match. Measured over all eight replays,
# four of the five deviations first diverge by tick 3500 and the fifth no earlier
# than 7575, so the gate certifies that a submission reproduces the opening of
# every visible match while leaving the late-match deviation to the held-out
# score. Ticks are off the 25-tick grid of the published trace, otherwise the
# trace would hand over the gate hashes for the traced replay.
GATE_CHECKPOINTS = (1013, 1447, 1889, 2311, 2753, 3187, 3623, 3989)

KIND_TOWER, KIND_MINION, KIND_HERO, KIND_PROJ = 0, 1, 2, 3

TOWER_HP = 1400 * ONE
TOWER_ATK = 60 * ONE
TOWER_ARMOR = 40 * ONE
TOWER_RANGE = 500 * ONE
TOWER_PERIOD = 30

MINION_MELEE_HP = 150 * ONE
MINION_MELEE_ATK = 18 * ONE
MINION_RANGED_HP = 110 * ONE
MINION_RANGED_ATK = 14 * ONE
MINION_ARMOR = 5 * ONE
MINION_MELEE_RANGE = 120 * ONE
MINION_RANGED_RANGE = 300 * ONE
MINION_SPEED = 72089  # 1.1 units/tick
MINION_PERIOD = 20

HERO_HP = 900 * ONE
HERO_ATK = 55 * ONE
HERO_ARMOR = 20 * ONE
HERO_RANGE = 260 * ONE
HERO_SPEED = 104857  # 1.6 units/tick
HERO_PERIOD = 18
HERO_RESPAWN = 300
HERO_REGEN = 3932          # 0.06 hp/tick anywhere
HERO_REGEN_HOME = 58982    # 0.90 hp/tick within HOME_RADIUS of the tier-2 tower
HOME_RADIUS = 300 * ONE

CRIT_PERCENT = 15
WAVE_PERIOD = 300
WAVE_LAST_TICK = 8700
WAVE_BACK_OFFSET = 30 * ONE

MOMENTUM_DIV = 4096
MOMENTUM_CAP = 8 * ONE

GOLD_MINION = 25
GOLD_HERO = 150
GOLD_TOWER = 200
GOLD_ATK_STEP = 100  # gold per +ATK_PER_STEP
ATK_PER_STEP = 2 * ONE

BOLT_CD = 90
BOLT_MULT = 98304  # 1.5 in Q16.16
BOLT_SPEED = 393216  # 6.0 units/tick
PROJ_HIT_RADIUS = 8 * ONE

SHRED_CD = 150
SHRED_AMOUNT = 812646  # 12.4 units, chosen so armor lands on a fraction
SHRED_TICKS = 240

WARD_CD = 300
WARD_FRACTION = 16384  # 0.25 in Q16.16
WARD_TICKS = 180

CMD_HOLD, CMD_PUSH, CMD_RETREAT, CMD_BOLT, CMD_SHRED, CMD_WARD, CMD_LANE = range(7)

# Tower positions along the lane, per team, tier1 (forward) then tier2 (home).
TOWER_POS = {0: (1536 * ONE, 512 * ONE), 1: (2560 * ONE, 3584 * ONE)}


class Entity:
    __slots__ = (
        "ability_cd",
        "alive",
        "armor",
        "atk",
        "atk_cd",
        "atk_period",
        "atk_range",
        "base_armor",
        "base_atk",
        "dmg_dealt",
        "eid",
        "gold",
        "hp",
        "kind",
        "lane",
        "last_damager",
        "max_hp",
        "pos",
        "proj_dmg",
        "proj_owner",
        "proj_target",
        "respawn_ticks",
        "shield",
        "shield_ticks",
        "shred_stacks",
        "shred_ticks",
        "speed",
        "stance",
        "target",
        "team",
    )

    def __init__(self, eid: int, kind: int, team: int, lane: int, pos: int):
        self.eid = eid
        self.kind = kind
        self.team = team
        self.lane = lane
        self.pos = pos
        self.hp = 0
        self.max_hp = 0
        self.atk = 0
        self.base_atk = 0
        self.armor = 0
        self.base_armor = 0
        self.atk_range = 0
        self.speed = 0
        self.atk_cd = 0
        self.atk_period = 0
        self.alive = True
        self.target = 0
        self.shield = 0
        self.shield_ticks = 0
        self.shred_stacks = 0
        self.shred_ticks = 0
        self.gold = 0
        self.dmg_dealt = 0
        self.ability_cd = [0, 0, 0]
        self.respawn_ticks = 0
        self.last_damager = 0
        self.proj_dmg = 0
        self.proj_target = 0
        self.proj_owner = 0
        self.stance = CMD_HOLD


def _fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _i32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, "little")


class Sim:
    def __init__(self, seed: int):
        self.rng = Xorshift32(seed)
        self.tick = 0
        self.next_eid = 1
        self.entities: dict[int, Entity] = {}
        self.lanes: list[list[Entity]] = [[], []]
        # Scoreboard telemetry, held in a signed 32-bit register like every
        # other simulation value. It is part of the state hash, so its
        # wraparound is observable.
        self.team_dmg: list[int] = [0, 0]
        self.heroes: list[Entity] = []
        self._spawn_towers()
        self._spawn_heroes()

    # -- construction ---------------------------------------------------------

    def _new(self, kind: int, team: int, lane: int, pos: int) -> Entity:
        e = Entity(self.next_eid, kind, team, lane, pos)
        self.next_eid += 1
        self.entities[e.eid] = e
        if kind != KIND_PROJ:
            self.lanes[lane].append(e)
        return e

    def _spawn_towers(self) -> None:
        for lane in (0, 1):
            for team in (0, 1):
                for tier in (0, 1):
                    e = self._new(KIND_TOWER, team, lane, TOWER_POS[team][tier])
                    e.hp = e.max_hp = TOWER_HP
                    e.atk = e.base_atk = TOWER_ATK
                    e.armor = e.base_armor = TOWER_ARMOR
                    e.atk_range = TOWER_RANGE
                    e.atk_period = TOWER_PERIOD

    def _spawn_heroes(self) -> None:
        for team in (0, 1):
            for idx in (0, 1):
                e = self._new(KIND_HERO, team, idx, TOWER_POS[team][1])
                e.hp = e.max_hp = HERO_HP
                e.atk = e.base_atk = HERO_ATK
                e.armor = e.base_armor = HERO_ARMOR
                e.atk_range = HERO_RANGE
                e.speed = HERO_SPEED
                e.atk_period = HERO_PERIOD
                self.heroes.append(e)

    def _spawn_wave(self) -> None:
        for lane in (0, 1):
            for team in (0, 1):
                base = 0 if team == 0 else LANE_LEN
                sign = 1 if team == 0 else -1
                for idx in range(4):
                    melee = idx < 2
                    off = 0 if melee else WAVE_BACK_OFFSET
                    e = self._new(KIND_MINION, team, lane, base + sign * off)
                    e.hp = e.max_hp = MINION_MELEE_HP if melee else MINION_RANGED_HP
                    e.atk = e.base_atk = MINION_MELEE_ATK if melee else MINION_RANGED_ATK
                    e.armor = e.base_armor = MINION_ARMOR
                    e.atk_range = MINION_MELEE_RANGE if melee else MINION_RANGED_RANGE
                    e.speed = MINION_SPEED
                    e.atk_period = MINION_PERIOD

    # -- rules ----------------------------------------------------------------

    def _dir(self, team: int) -> int:
        return 1 if team == 0 else -1

    def _ordered(self) -> list[list[Entity]]:
        """Per-lane candidate order for target acquisition: ascending eid."""
        return [list(lane) for lane in self.lanes]

    def _acquire(self, e: Entity, ordered: list[list[Entity]]) -> int:
        """Nearest alive enemy in the same lane within range; ties by lowest eid.

        Candidates are visited in ascending eid order and compared with a strict
        less-than, which makes the lowest eid win a distance tie.
        """
        best_eid = 0
        best_d = -1
        for other in ordered[e.lane]:
            if not other.alive or other.team == e.team:
                continue
            d = other.pos - e.pos
            if d < 0:
                d = -d
            if d > e.atk_range:
                continue
            if best_d < 0 or d < best_d:
                best_d = d
                best_eid = other.eid
        return best_eid

    def _damage(self, src: Entity, dst: Entity, base: int, crit: bool) -> None:
        num = base * 100
        if crit:
            num = num * 2
        den = 100 + tdiv(dst.armor, ONE)
        den = max(den, 1)
        dmg = wrap32(tdiv(num, den))
        dmg = max(dmg, 0)
        src.dmg_dealt = wrap32(src.dmg_dealt + dmg)
        self.team_dmg[src.team] = self.team_dmg[src.team] + dmg
        if dst.shield > 0:
            absorbed = min(dst.shield, dmg)
            dst.shield = wrap32(dst.shield - absorbed)
            dmg = wrap32(dmg - absorbed)
        if dmg > 0:
            dst.hp = wrap32(dst.hp - dmg)
            dst.last_damager = src.eid

    def _phase_input(self, cmds: list[list[int]]) -> None:
        for _t, slot, code, arg in cmds:
            hero = self.heroes[slot]
            if not hero.alive:
                continue
            if code in (CMD_HOLD, CMD_PUSH, CMD_RETREAT):
                hero.stance = code
            elif code == CMD_LANE:
                self.lanes[hero.lane].remove(hero)
                hero.lane = arg & 1
                hero.pos = TOWER_POS[hero.team][1]
                self.lanes[hero.lane].append(hero)
            elif code == CMD_BOLT and hero.ability_cd[0] == 0:
                tgt = self._acquire(hero, self._ordered())
                if tgt:
                    p = self._new(KIND_PROJ, hero.team, hero.lane, hero.pos)
                    p.proj_dmg = fx_mul(hero.atk, BOLT_MULT)
                    p.proj_target = tgt
                    p.proj_owner = hero.eid
                    p.speed = BOLT_SPEED
                    hero.ability_cd[0] = BOLT_CD
            elif code == CMD_SHRED and hero.ability_cd[1] == 0:
                tgt = self._acquire(hero, self._ordered())
                if tgt:
                    dst = self.entities[tgt]
                    dst.armor = wrap32(dst.armor - SHRED_AMOUNT)
                    dst.shred_stacks += 1
                    dst.shred_ticks = SHRED_TICKS
                    hero.ability_cd[1] = SHRED_CD
            elif code == CMD_WARD and hero.ability_cd[2] == 0:
                hero.shield = fx_mul(hero.max_hp, WARD_FRACTION)
                hero.shield_ticks = WARD_TICKS
                hero.ability_cd[2] = WARD_CD

    def _phase_timers(self) -> None:
        for eid in sorted(self.entities):
            e = self.entities[eid]
            if e.kind == KIND_PROJ:
                continue
            if not e.alive:
                if e.kind == KIND_HERO and e.respawn_ticks > 0:
                    e.respawn_ticks -= 1
                    if e.respawn_ticks == 0:
                        e.alive = True
                        e.hp = e.max_hp
                        e.pos = TOWER_POS[e.team][1]
                        e.atk_cd = 0
                        e.target = 0
                        self.lanes[e.lane].append(e)
                continue
            if e.atk_cd > 0:
                e.atk_cd -= 1
            if e.kind == KIND_MINION:
                bonus = tdiv(self.team_dmg[e.team], MOMENTUM_DIV)
                if bonus < 0:
                    bonus = 0
                elif bonus > MOMENTUM_CAP:
                    bonus = MOMENTUM_CAP
                e.atk = wrap32(e.base_atk + bonus)
            if e.kind == KIND_HERO:
                if e.hp < e.max_hp:
                    d = e.pos - TOWER_POS[e.team][1]
                    near = (d if d >= 0 else -d) <= HOME_RADIUS
                    hp = wrap32(e.hp + (HERO_REGEN_HOME if near else HERO_REGEN))
                    e.hp = min(hp, e.max_hp)
                for i in range(3):
                    if e.ability_cd[i] > 0:
                        e.ability_cd[i] -= 1
                e.atk = wrap32(e.base_atk + ATK_PER_STEP * (e.gold // GOLD_ATK_STEP))

    def _phase_expiry(self) -> None:
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

    def _phase_projectiles(self) -> None:
        for eid in sorted(self.entities):
            p = self.entities[eid]
            if p.kind != KIND_PROJ or not p.alive:
                continue
            dst = self.entities.get(p.proj_target)
            if dst is None or not dst.alive:
                p.alive = False
                continue
            delta = dst.pos - p.pos
            step = p.speed if delta >= 0 else -p.speed
            if (delta if delta >= 0 else -delta) <= PROJ_HIT_RADIUS:
                owner = self.entities[p.proj_owner]
                self._damage(owner, dst, p.proj_dmg, False)
                p.alive = False
            else:
                p.pos = wrap32(p.pos + step)

    def _phase_move(self) -> None:
        ordered = self._ordered()
        for eid in sorted(self.entities):
            e = self.entities[eid]
            if e.kind == KIND_PROJ or not e.alive:
                continue
            e.target = self._acquire(e, ordered)
            if e.target or e.speed == 0:
                continue
            if e.kind == KIND_HERO and e.stance == CMD_HOLD:
                continue
            sign = self._dir(e.team)
            if e.kind == KIND_HERO and e.stance == CMD_RETREAT:
                sign = -sign
            pos = wrap32(e.pos + sign * e.speed)
            pos = max(pos, 0)
            pos = min(pos, LANE_LEN)
            e.pos = pos

    def _phase_attack(self) -> None:
        for eid in sorted(self.entities):
            e = self.entities[eid]
            if e.kind == KIND_PROJ or not e.alive or e.atk_cd != 0 or not e.target:
                continue
            dst = self.entities.get(e.target)
            if dst is None or not dst.alive or dst.hp <= 0:
                continue
            crit = self.rng.range(100) < CRIT_PERCENT
            e.atk_cd = e.atk_period
            self._damage(e, dst, e.atk, crit)

    def _phase_deaths(self) -> None:
        for eid in sorted(self.entities):
            e = self.entities[eid]
            if not e.alive or e.kind == KIND_PROJ or e.hp > 0:
                continue
            e.alive = False
            killer = self.entities.get(e.last_damager)
            if killer is not None and killer.kind == KIND_HERO:
                if e.kind == KIND_MINION:
                    killer.gold += GOLD_MINION
                elif e.kind == KIND_HERO:
                    killer.gold += GOLD_HERO
                else:
                    killer.gold += GOLD_TOWER
            lane = self.lanes[e.lane]
            i = lane.index(e)
            lane[i] = lane[-1]
            lane.pop()
            if e.kind == KIND_HERO:
                e.respawn_ticks = HERO_RESPAWN
                e.shield = 0
                e.shield_ticks = 0

    def _phase_cleanup(self) -> None:
        for eid in [k for k, v in self.entities.items() if v.kind == KIND_PROJ and not v.alive]:
            del self.entities[eid]

    # -- driver ---------------------------------------------------------------

    def step(self, cmds: list[list[int]]) -> None:
        self.tick += 1
        self._phase_input(cmds)
        self._phase_timers()
        self._phase_projectiles()
        self._phase_move()
        self._phase_attack()
        self._phase_expiry()
        self._phase_deaths()
        if self.tick % WAVE_PERIOD == 0 and self.tick <= WAVE_LAST_TICK:
            self._spawn_wave()
        self._phase_cleanup()

    def hash_state(self) -> str:
        buf = bytearray()
        for eid in sorted(self.entities):
            e = self.entities[eid]
            if not e.alive and e.kind != KIND_HERO:
                continue
            buf += _i32(e.eid)
            buf += _i32(e.kind)
            buf += _i32(e.team)
            buf += _i32(e.lane)
            buf += _i32(e.pos)
            buf += _i32(e.hp)
            buf += _i32(e.atk)
            buf += _i32(e.armor)
            buf += _i32(e.atk_cd)
            buf += _i32(e.shield)
            buf += _i32(e.shield_ticks)
            buf += _i32(e.shred_stacks)
            buf += _i32(e.shred_ticks)
            buf += _i32(e.gold)
            buf += _i32(e.dmg_dealt)
            buf += _i32(e.target)
            buf += _i32(1 if e.alive else 0)
            buf += _i32(e.respawn_ticks)
            for c in e.ability_cd:
                buf += _i32(c)
        buf += _i32(self.team_dmg[0])
        buf += _i32(self.team_dmg[1])
        buf += _i32(self.rng.state)
        buf += _i32(self.tick)
        buf += _i32(self.next_eid)
        return f"{_fnv1a64(bytes(buf)):016x}"


def run(replay: dict) -> list[tuple[int, str]]:
    sim = Sim(replay["seed"])
    by_tick: dict[int, list[list[int]]] = {}
    for c in replay["commands"]:
        by_tick.setdefault(c[0], []).append(c)
    checkpoints = set(replay["checkpoints"])
    out = []
    for t in range(1, replay["ticks"] + 1):
        sim.step(by_tick.get(t, []))
        if t in checkpoints:
            out.append((t, sim.hash_state()))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: sim.py <replay.json>\n")
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        replay = json.load(fh)
    for tick, digest in run(replay):
        sys.stdout.write(f"{tick} {digest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
