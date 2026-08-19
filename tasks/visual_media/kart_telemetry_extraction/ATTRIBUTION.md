# Third-party attribution

## SuperTuxKart

Every video in this task's data is a screen recording of
[SuperTuxKart](https://supertuxkart.net/) 1.5 running in profile mode, and the
ground-truth labels are the per-kart counter table SuperTuxKart prints itself at
the end of that mode. No frame and no number here is authored by the task; both
come out of the game.

- Upstream: <https://github.com/supertuxkart/stk-code>
- Version: SuperTuxKart 1.5 (`run_game.sh` from the official Linux build)
- Invocation: `--profile-laps=4 --track=<track> --numkarts=6 --difficulty=3
  --kart=tux --ai=<the other five>`, captured with `ffmpeg` `x11grab` under `Xvfb`
  with software GL.

### Licensing

SuperTuxKart's **game code** is distributed under the GNU General Public License,
version 3 or later. Its **artwork, tracks, karts, music and sound** are contributed
under a mix of free-culture licences, predominantly Creative Commons
Attribution-ShareAlike (CC-BY-SA 3.0/4.0), with per-asset credits in the upstream
`data/CREDITS` file.

The recordings shipped as task data are audiovisual captures of that artwork, so
they carry the artwork's terms rather than the code's. Anyone redistributing this
task's data should:

1. keep this attribution file alongside it;
2. preserve the upstream `data/CREDITS` credits for the twelve tracks used
   (`cocoa_temple`, `cornfield_crossing`, `fortmagma`, `gran_paradiso_island`,
   `hacienda`, `lighthouse`, `olivermath`, `ravenbridge_mansion`, `sandtrack`,
   `scotland`, `snowmountain`, `stk_enterprise`) and the six karts used
   (`tux`, `gnu`, `adiumy`, `amanda`, `beastie`, `kiki`); and
3. license the recordings under CC-BY-SA on the same terms, since ShareAlike
   propagates to derivative audiovisual works.

Audio is stripped from every file (`-an`), so no music or sound asset is
redistributed here; the recordings are video only.

No SuperTuxKart source code is vendored into this repository, and the game is not
installed on the task VM. The agent receives only the recordings.

## Recording and corpus construction

The races were recorded and the ground truth extracted by the task author using a
generator written for a separate project, then re-encoded to 960x540 at CRF 32 for
this task. The task ships the encoder settings and the label extraction in
`NOTES.md` so the corpus can be rebuilt from a fresh set of recordings.
