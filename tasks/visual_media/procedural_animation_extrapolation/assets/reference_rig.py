"""The rig that generated the animation. Never staged onto the VM.

Three rigid bodies. Every rule below is a pure function of the frame number, so the
motion is bit-reproducible and nothing chaotic can punish a correct reimplementation,
and every rule is exercised inside the visible window so none of them has to be
guessed. What is not given away is the structure: which body follows which, at what
rates, that the tip's reach breathes at a multiple of the arm's spin, and that its
height is clamped to a band that is not centred on zero.

Frames 1..60 are published. Frames 61..180 are graded.
"""

import math

W_HUB, W_ARM = 0.0730, 0.1910      # turn rates, radians per frame
LX, LY = 0.0410, 0.0655            # the hub's Lissajous rates
PHI = 0.7                          # the hub's y phase offset
AX, AY = 2.35, 1.60                # the hub's Lissajous amplitudes
ARM_LEN = 1.25                     # hub to arm
TIP_LEN = 0.85                     # arm to tip, before breathing
BREATHE_AMP, BREATHE_MULT = 0.18, 3.0   # the tip's reach breathes on the arm's spin
Z_AMP = 1.45                       # the tip's free vertical swing
Z_LO, Z_HI = -0.31, 0.62           # the band it is clamped to, deliberately off centre

BODIES = ("arm", "hub", "tip")


def state(f: int) -> dict:
    """Location and Z rotation of each body at frame ``f``."""
    hub_x = AX * math.sin(LX * f)
    hub_y = AY * math.sin(LY * f + PHI)
    hub_rot = W_HUB * f
    arm_rot = W_ARM * f

    arm_x = hub_x + ARM_LEN * math.cos(hub_rot)
    arm_y = hub_y + ARM_LEN * math.sin(hub_rot)

    reach = TIP_LEN * (1.0 + BREATHE_AMP * math.sin(BREATHE_MULT * arm_rot))
    tip_x = arm_x + reach * math.cos(hub_rot + arm_rot)
    tip_y = arm_y + reach * math.sin(hub_rot + arm_rot)
    tip_z = min(Z_HI, max(Z_LO, Z_AMP * math.sin(arm_rot)))

    return {"hub": ((hub_x, hub_y, 0.0), (0.0, 0.0, hub_rot)),
            "arm": ((arm_x, arm_y, 0.0), (0.0, 0.0, hub_rot + arm_rot)),
            "tip": ((tip_x, tip_y, tip_z), (0.0, 0.0, arm_rot))}


def world_vertices(rest: dict, f: int) -> list:
    """Flat world-space vertex list at frame ``f``, bodies in the graded order.

    Kept free of Blender so the reference can be checked without it. The transform is
    a Z rotation then a translation, which is what setting ``location`` and
    ``rotation_euler`` on an object with no parent produces.
    """
    s = state(f)
    out = []
    for name in BODIES:
        (tx, ty, tz), (_, _, rz) = s[name]
        c, sn = math.cos(rz), math.sin(rz)
        for vx, vy, vz in rest[name]:
            out.extend([c * vx - sn * vy + tx, sn * vx + c * vy + ty, vz + tz])
    return out
