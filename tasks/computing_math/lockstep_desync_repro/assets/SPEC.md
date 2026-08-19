# Lane Siege v1: normative simulation specification

This document is the contract. Where the starter build in `input/starter/sim.py`
disagrees with this document, the starter is wrong.

A conforming simulator, given a replay's `seed` and its command stream, must
produce the same state hash as the reference at every checkpoint tick, for every
replay, bit for bit.

---

## 1. Interface

```
python3 sim.py <replay.json>
```

writes one line per checkpoint tick to stdout, in ascending tick order:

```
<tick> <16 lowercase hex digits>
```

Nothing else on those lines. Other lines on stdout are ignored by the grader.
Exit status must be 0.

A replay file is:

| field | meaning |
|---|---|
| `version` | always `1` |
| `seed` | the simulation RNG seed |
| `ticks` | number of ticks to simulate, always `9000` |
| `checkpoints` | ascending tick numbers at which to emit a hash |
| `commands` | `[tick, hero_slot, code, arg]` rows, ascending by `(tick, hero_slot)` |

`checkpoints` is read from the replay file. It is not a fixed list, and a
submission that assumes one will fail.

---

## 2. Numbers

Every simulation value is a Q16.16 fixed-point number held in a **signed 32-bit
two's-complement register**. `ONE = 65536` represents 1.0. There is no floating
point anywhere in the simulation.

- `wrap32(x)` reduces an arbitrary integer to that register:
  `((x + 2^31) & 0xFFFFFFFF) - 2^31`.
- `tdiv(n, d)` is integer division **truncating toward zero**, C99 semantics.
  For negative operands this is not the same as a floored division: `tdiv(-99, 10)`
  is `-9`, not `-10`.
- `fx_mul(a, b) = wrap32(tdiv(a * b, ONE))`. The product is formed at full width
  and only the result is reduced to 32 bits.

Every arithmetic result that is stored into simulation state passes through
`wrap32`. Intermediates may be computed at full width.

---

## 3. Constants

All values are raw Q16.16 integers. Nothing here is rounded from a decimal at
run time.

| name | value | |
|---|---|---|
| `ONE` | 65536 | 1.0 |
| `LANE_LEN` | 268435456 | 4096 units |
| `TICKS_PER_MATCH` | 9000 | |
| `TOWER_HP` | 91750400 | 1400 units |
| `TOWER_ATK` | 3932160 | 60 units |
| `TOWER_ARMOR` | 2621440 | 40 units |
| `TOWER_RANGE` | 32768000 | 500 units |
| `TOWER_PERIOD` | 30 | ticks |
| `MINION_MELEE_HP` | 9830400 | 150 units |
| `MINION_MELEE_ATK` | 1179648 | 18 units |
| `MINION_RANGED_HP` | 7208960 | 110 units |
| `MINION_RANGED_ATK` | 917504 | 14 units |
| `MINION_ARMOR` | 327680 | 5 units |
| `MINION_MELEE_RANGE` | 7864320 | 120 units |
| `MINION_RANGED_RANGE` | 19660800 | 300 units |
| `MINION_SPEED` | 72089 | units per tick |
| `MINION_PERIOD` | 20 | ticks |
| `HERO_HP` | 58982400 | 900 units |
| `HERO_ATK` | 3604480 | 55 units |
| `HERO_ARMOR` | 1310720 | 20 units |
| `HERO_RANGE` | 17039360 | 260 units |
| `HERO_SPEED` | 104857 | units per tick |
| `HERO_PERIOD` | 18 | ticks |
| `HERO_RESPAWN` | 300 | ticks |
| `HERO_REGEN` | 3932 | per tick |
| `HERO_REGEN_HOME` | 58982 | per tick |
| `HOME_RADIUS` | 19660800 | 300 units |
| `CRIT_PERCENT` | 15 | |
| `WAVE_PERIOD` | 300 | ticks |
| `WAVE_LAST_TICK` | 8700 | |
| `WAVE_BACK_OFFSET` | 1966080 | 30 units |
| `MOMENTUM_DIV` | 4096 | |
| `MOMENTUM_CAP` | 524288 | 8 units |
| `GOLD_MINION` | 25 | |
| `GOLD_HERO` | 150 | |
| `GOLD_TOWER` | 200 | |
| `GOLD_ATK_STEP` | 100 | |
| `ATK_PER_STEP` | 131072 | 2 units |
| `BOLT_CD` | 90 | ticks |
| `BOLT_MULT` | 98304 | 1.5 |
| `BOLT_SPEED` | 393216 | 6 units per tick |
| `PROJ_HIT_RADIUS` | 524288 | 8 units |
| `SHRED_CD` | 150 | ticks |
| `SHRED_AMOUNT` | 812646 | |
| `SHRED_TICKS` | 240 | ticks |
| `WARD_CD` | 300 | ticks |
| `WARD_FRACTION` | 16384 | 0.25 |
| `WARD_TICKS` | 180 | ticks |

Tower positions, indexed `[team][tier]` where tier 0 is the forward tower and
tier 1 the home tower:

| | tier 0 | tier 1 |
|---|---|---|
| team 0 | 100663296 (1536 units) | 33554432 (512 units) |
| team 1 | 167772160 (2560 units) | 234881024 (3584 units) |

Entity kinds: `TOWER = 0`, `MINION = 1`, `HERO = 2`, `PROJECTILE = 3`.

Command codes: `HOLD = 0`, `PUSH = 1`, `RETREAT = 2`, `BOLT = 3`, `SHRED = 4`,
`WARD = 5`, `LANE = 6`.

---

## 4. Random number generator

One global xorshift32 stream. Its consumption order is part of the spec: a
simulator that draws the same values in a different order is not conforming.

```
state = seed & 0xFFFFFFFF ; if state == 0: state = 0x9E3779B9
next_u32():
    x = state
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= x >> 17
    x ^= (x << 5) & 0xFFFFFFFF
    state = x
    return x
range(n) = next_u32() % n
```

The stream is consumed in exactly one place: the crit roll in the attack phase
(section 6.5).

---

## 5. World construction

Entity ids are assigned from a counter starting at 1, incremented on every
creation including projectiles. Ids are never reused.

Entities are created before tick 1, in this exact order:

1. Towers: `for lane in (0, 1): for team in (0, 1): for tier in (0, 1)`, so
   eids 1 to 8.
2. Heroes: `for team in (0, 1): for idx in (0, 1)`, so eids 9 to 12. Hero
   `(team, idx)` starts in lane `idx`, at `TOWER_POS[team][1]`. Hero slot in the
   replay command stream is `team * 2 + idx`.

Non-projectile entities also belong to a per-lane container in creation order.
An entity is appended to its lane's container when created or when it changes
lane; it is removed with a **swap-remove** (overwrite with the last element,
then drop the last) when it dies. The container order is therefore not the eid
order, and nothing in the rules may depend on it. See section 6.4.

Field initialisation: `hp = max_hp`, `atk = base_atk`, `armor = base_armor`,
everything else zero, `alive = true`, `stance = HOLD`.

Team 0 advances in the `+` direction along a lane, team 1 in the `-` direction.

---

## 6. Tick

A tick is the following eight phases in this order. Tick numbering starts at 1.

Wherever a phase says "in ascending eid order", that is the order over **all**
entities in the simulation, not over a lane container.

### 6.1 Input

Apply this tick's commands in the order they appear in the replay. A command
addressed to a dead hero is discarded.

- `HOLD` / `PUSH` / `RETREAT`: set the hero's stance.
- `LANE`: remove the hero from its lane container, set `lane = arg & 1`, set
  `pos = TOWER_POS[team][1]`, append to the new lane container.
- `BOLT`, only if ability cooldown 0: acquire a target (section 6.4). If there
  is one, create a projectile at the hero's position with
  `dmg = fx_mul(hero.atk, BOLT_MULT)`, `speed = BOLT_SPEED`, owner and target
  recorded, and set the cooldown to `BOLT_CD`. With no target, nothing happens
  and the cooldown is not set.
- `SHRED`, only if cooldown 0: acquire a target. If there is one, subtract
  `SHRED_AMOUNT` from its armor, increment its shred stack count, set its shred
  timer to `SHRED_TICKS`, and set the cooldown to `SHRED_CD`. Stacks add: a
  second cast subtracts `SHRED_AMOUNT` again and restarts the timer.
- `WARD`, only if cooldown 0: set the hero's shield to
  `fx_mul(hero.max_hp, WARD_FRACTION)`, its shield timer to `WARD_TICKS`, and
  the cooldown to `WARD_CD`.

Acquisition inside this phase uses the lane containers as they stand at that
moment, so a `LANE` command earlier in the same tick is visible to a later one.

### 6.2 Timers

In ascending eid order, skipping projectiles.

If the entity is dead: if it is a hero with a positive respawn timer, decrement
it, and on reaching 0 revive it with full hp at `TOWER_POS[team][1]`, attack
cooldown 0, no target, appended to its lane container. Then continue to the next
entity.

Otherwise, in this order:

1. Decrement the attack cooldown if positive.
2. If the entity is a minion, recompute its attack:
   `bonus = tdiv(team_dmg[team], MOMENTUM_DIV)`, clamped to `[0, MOMENTUM_CAP]`,
   then `atk = wrap32(base_atk + bonus)`.
3. If the shield timer is positive, decrement it; on reaching 0 set the shield
   to 0.
4. If the shred timer is positive, decrement it; on reaching 0 add
   `SHRED_AMOUNT * stacks` back to armor and clear the stack count.
5. If the entity is a hero:
   - if `hp < max_hp`, add `HERO_REGEN_HOME` when the hero is within
     `HOME_RADIUS` of `TOWER_POS[team][1]` and `HERO_REGEN` otherwise, clamped
     at `max_hp`;
   - decrement each of the three ability cooldowns if positive;
   - `atk = wrap32(base_atk + ATK_PER_STEP * (gold // GOLD_ATK_STEP))`, floored
     integer division of a non-negative gold total.

Steps 3 and 4 happen here, **before** the attack phase. An effect whose timer
reaches 0 on this tick does not apply during this tick's attacks.

Because a dead entity leaves this phase at the first branch, every timer it
carries is frozen while it is dead. A hero that dies with 90 ticks of shred left
respawns still carrying 90 ticks of shred and the matching armor debt. `gold`,
`dmg_dealt`, `base_atk` and `base_armor` also survive death unchanged; only
`hp`, `pos`, `atk_cd`, `target`, `shield` and `shield_ticks` are reset by the
death and respawn rules.

### 6.3 Projectiles

In ascending eid order, for each live projectile:

- If its target no longer exists or is not alive, the projectile expires with no
  effect.
- Otherwise let `delta = target.pos - projectile.pos`. If `|delta| <=
  PROJ_HIT_RADIUS`, apply damage (section 6.6) from the projectile's **owner** to
  the target with base `dmg` and no crit, and the projectile expires. Otherwise
  move the projectile by `speed` toward the target.

### 6.4 Acquire and move

Compute, once for this phase, each lane's candidate order: **the lane container
sorted by ascending eid**.

Then in ascending eid order, for every live non-projectile entity:

1. Acquire a target: among candidates in the entity's lane, in that ascending
   eid order, skipping dead entities and same-team entities, take the one whose
   `|other.pos - self.pos|` is smallest and at most the entity's range. Ties are
   broken by the **lowest eid**, which is what the ascending order plus a strict
   less-than comparison gives. Record it as the entity's target for this tick,
   or 0.
2. If the entity has a target, or has zero speed, it does not move.
3. A hero whose stance is `HOLD` does not move. A hero whose stance is `RETREAT`
   moves in the direction opposite to its team's; anything else moves in its
   team's direction.
4. `pos = wrap32(pos + sign * speed)`, then clamped to `[0, LANE_LEN]`.

The sort is not an optimisation detail. A simulator that walks the lane
container in storage order will agree with this one until the first swap-remove
reorders a container, and disagree afterwards whenever two candidates are
equidistant.

### 6.5 Attack

In ascending eid order, for every live non-projectile entity whose attack
cooldown is 0 and whose recorded target is not 0:

1. Draw `crit = rng.range(100) < CRIT_PERCENT`. **The draw happens here,
   unconditionally**, before the target is inspected.
2. Set the attack cooldown to the entity's period.
3. Look up the target. If it no longer exists, is not alive, **or has hp <= 0**,
   the attack is wasted: no damage, but the draw and the cooldown above still
   happened.
4. Otherwise apply damage (section 6.6) with base `atk` and the drawn crit.

A target reduced to non-positive hp earlier in this same phase is still flagged
alive, because deaths are not resolved until section 6.7. Step 3 is what makes
those attacks whiff. Moving the draw after that check changes the random stream
for every subsequent attack in the match.

### 6.6 Damage

```
num = base * 100
if crit: num = num * 2
den = 100 + tdiv(target.armor, ONE)
if den < 1: den = 1
dmg = wrap32(tdiv(num, den))
if dmg < 0: dmg = 0

source.dmg_dealt   = wrap32(source.dmg_dealt + dmg)
team_dmg[source.team] = wrap32(team_dmg[source.team] + dmg)

if target.shield > 0:
    absorbed = min(dmg, target.shield)
    target.shield = wrap32(target.shield - absorbed)
    dmg = wrap32(dmg - absorbed)
if dmg > 0:
    target.hp = wrap32(target.hp - dmg)
    target.last_damager = source.eid
```

`team_dmg` is a two-entry scoreboard held in the same signed 32-bit register as
everything else. Over a full match it wraps, and section 6.2 step 2 reads it, so
the wraparound is observable in play and not only in the hash. `tdiv(target.armor,
ONE)` is the only place a negative numerator reaches the division, and armor only
goes negative under stacked shred.

### 6.7 Deaths

In ascending eid order, for every live non-projectile entity with `hp <= 0`:
clear its alive flag; if `last_damager` names a live-or-dead hero, award that
hero `GOLD_MINION`, `GOLD_HERO` or `GOLD_TOWER` by the dead entity's kind;
swap-remove it from its lane container. A dead hero gets `respawn_ticks =
HERO_RESPAWN` and loses its shield and shield timer.

### 6.8 Wave spawn and cleanup

If `tick % WAVE_PERIOD == 0` and `tick <= WAVE_LAST_TICK`, spawn a wave:
`for lane in (0, 1): for team in (0, 1): for idx in 0..3`. Indices 0 and 1 are
melee, 2 and 3 are ranged. A minion spawns at the team's base end (`0` for team
0, `LANE_LEN` for team 1) offset by `WAVE_BACK_OFFSET` toward midfield for the
ranged pair and by nothing for the melee pair. The two minions of a pair
therefore start at exactly the same position and, having equal speed, stay there.

Then delete every expired projectile from the entity table. Their eids are not
reused.

Finally, if the tick is a checkpoint, emit the hash.

---

## 7. State hash

FNV-1a 64-bit over a byte string, printed as 16 lowercase hex digits.

```
h = 0xCBF29CE484222325
for each byte b: h = ((h ^ b) * 0x100000001B3) mod 2^64
```

The byte string is built in ascending eid order over the entity table. A dead
entity is included only if it is a hero. For each included entity, append these
fields, each as its low 32 bits, little endian:

```
eid, kind, team, lane, pos, hp, atk, armor, atk_cd, shield, shield_ticks,
shred_stacks, shred_ticks, gold, dmg_dealt, target, alive (1 or 0),
respawn_ticks, ability_cd[0], ability_cd[1], ability_cd[2]
```

Then append, in this order: `team_dmg[0]`, `team_dmg[1]`, the RNG state, the
tick number, and the next unused eid.

Projectiles that are still in flight are included by the same rule (they are
alive and not heroes, so they are included); their unused fields are zero, and
their `pos` is meaningful.
