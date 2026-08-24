# Third-party attribution

## Blender

The animation is authored, evaluated and graded with
[Blender](https://www.blender.org/), which is free software under the GNU GPL. No
Blender source is redistributed here; the task's package installs the official
`blender-5.0.1-linux-x64` build from the Blender Foundation's own download server,
pinned by SHA-256.

- Upstream: <https://projects.blender.org/blender/blender>
- Version: 5.0.1, the same version the benchmark's Windows image bakes as
  `blender-5.0.1`
- Licence: GNU GPL v3-or-later

## The animation itself

The rig, the motion rule, the meshes and every published and held-out frame are
original to this task. Nothing is derived from a third-party scene, model or capture.
The rest meshes are Blender's own primitives (cube, cylinder, icosphere) evaluated once
and shipped as explicit vertex coordinates, so a submission never has to guess
primitive parameters and grading does not depend on how a version of Blender happens to
generate them.
