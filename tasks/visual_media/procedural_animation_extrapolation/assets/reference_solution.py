"""A worked solution, written the way an agent would write one.

Not staged onto the VM. It exists so the task's positive control runs the real
grading path: the parameters below are what has to be recovered from the sixty
published frames, and the rest vertices are the ones the task publishes.

Keyframing every integer frame is deliberate. Frames 61 to 180 can only be keyed once
the rule is known, so baking is not a shortcut past recovering it, and a key on every
frame means interpolation between keys never applies.
"""

import math

import bpy

W_HUB, W_ARM = 0.073, 0.191
LX, LY, PHI = 0.041, 0.0655, 0.7
AX, AY = 2.35, 1.6
ARM_LEN, TIP_LEN = 1.25, 0.85
BREATHE_AMP, BREATHE_MULT = 0.18, 3.0
Z_AMP, Z_LO, Z_HI = 1.45, -0.31, 0.62

REST = {
    "arm": [
        [
            0.0,
            0.219999998808,
            -0.550000011921
        ],
        [
            0.0,
            0.219999998808,
            0.550000011921
        ],
        [
            0.109999999404,
            0.190525591373,
            -0.550000011921
        ],
        [
            0.109999999404,
            0.190525591373,
            0.550000011921
        ],
        [
            0.190525591373,
            0.109999999404,
            -0.550000011921
        ],
        [
            0.190525591373,
            0.109999999404,
            0.550000011921
        ],
        [
            0.219999998808,
            0.0,
            -0.550000011921
        ],
        [
            0.219999998808,
            0.0,
            0.550000011921
        ],
        [
            0.190525591373,
            -0.109999999404,
            -0.550000011921
        ],
        [
            0.190525591373,
            -0.109999999404,
            0.550000011921
        ],
        [
            0.109999999404,
            -0.190525591373,
            -0.550000011921
        ],
        [
            0.109999999404,
            -0.190525591373,
            0.550000011921
        ],
        [
            0.0,
            -0.219999998808,
            -0.550000011921
        ],
        [
            0.0,
            -0.219999998808,
            0.550000011921
        ],
        [
            -0.109999999404,
            -0.190525591373,
            -0.550000011921
        ],
        [
            -0.109999999404,
            -0.190525591373,
            0.550000011921
        ],
        [
            -0.190525591373,
            -0.109999999404,
            -0.550000011921
        ],
        [
            -0.190525591373,
            -0.109999999404,
            0.550000011921
        ],
        [
            -0.219999998808,
            0.0,
            -0.550000011921
        ],
        [
            -0.219999998808,
            0.0,
            0.550000011921
        ],
        [
            -0.190525591373,
            0.109999999404,
            -0.550000011921
        ],
        [
            -0.190525591373,
            0.109999999404,
            0.550000011921
        ],
        [
            -0.109999999404,
            0.190525591373,
            -0.550000011921
        ],
        [
            -0.109999999404,
            0.190525591373,
            0.550000011921
        ]
    ],
    "hub": [
        [
            -0.40000000596,
            -0.40000000596,
            -0.40000000596
        ],
        [
            -0.40000000596,
            -0.40000000596,
            0.40000000596
        ],
        [
            -0.40000000596,
            0.40000000596,
            -0.40000000596
        ],
        [
            -0.40000000596,
            0.40000000596,
            0.40000000596
        ],
        [
            0.40000000596,
            -0.40000000596,
            -0.40000000596
        ],
        [
            0.40000000596,
            -0.40000000596,
            0.40000000596
        ],
        [
            0.40000000596,
            0.40000000596,
            -0.40000000596
        ],
        [
            0.40000000596,
            0.40000000596,
            0.40000000596
        ]
    ],
    "tip": [
        [
            0.0,
            0.0,
            -0.340000003576
        ],
        [
            0.246024012566,
            -0.178744792938,
            -0.152053102851
        ],
        [
            -0.093970902264,
            -0.289217621088,
            -0.152053102851
        ],
        [
            -0.304104506969,
            0.0,
            -0.152053102851
        ],
        [
            -0.093970902264,
            0.289217621088,
            -0.152053102851
        ],
        [
            0.246024012566,
            0.178744792938,
            -0.152053102851
        ],
        [
            0.093970902264,
            -0.289217621088,
            0.152053102851
        ],
        [
            -0.246024012566,
            -0.178744792938,
            0.152053102851
        ],
        [
            -0.246024012566,
            0.178744792938,
            0.152053102851
        ],
        [
            0.093970902264,
            0.289217621088,
            0.152053102851
        ],
        [
            0.304104506969,
            0.0,
            0.152053102851
        ],
        [
            0.0,
            0.0,
            0.340000003576
        ]
    ]
}


def state(f):
    """Location and Z rotation of each body at frame f."""
    hub_x = AX * math.sin(LX * f)
    hub_y = AY * math.sin(LY * f + PHI)
    hub_rot, arm_rot = W_HUB * f, W_ARM * f
    arm_x = hub_x + ARM_LEN * math.cos(hub_rot)
    arm_y = hub_y + ARM_LEN * math.sin(hub_rot)
    reach = TIP_LEN * (1.0 + BREATHE_AMP * math.sin(BREATHE_MULT * arm_rot))
    return {
        "hub": ((hub_x, hub_y, 0.0), (0.0, 0.0, hub_rot)),
        "arm": ((arm_x, arm_y, 0.0), (0.0, 0.0, hub_rot + arm_rot)),
        "tip": ((arm_x + reach * math.cos(hub_rot + arm_rot),
                 arm_y + reach * math.sin(hub_rot + arm_rot),
                 min(Z_HI, max(Z_LO, Z_AMP * math.sin(arm_rot)))), (0.0, 0.0, arm_rot)),
    }


def build():
    """Create the three bodies and key their motion over frames 1..180."""
    for name, verts in REST.items():
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in verts], [], [])
        me.update()
        bpy.context.collection.objects.link(bpy.data.objects.new(name, me))
    for f in range(1, 181):
        for name, (loc, rot) in state(f).items():
            o = bpy.data.objects[name]
            o.location = loc
            o.rotation_euler = rot
            o.keyframe_insert("location", frame=f)
            o.keyframe_insert("rotation_euler", frame=f)
