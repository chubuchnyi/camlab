# Local changes to the vendored three.js files

`SHA256SUMS` pins these so a silent swap fails a test. Anything listed here is a change **we**
made, so the pin no longer means "pristine upstream" for that file — it means "the upstream build
plus exactly this". Re-vendoring drops these; reapply them or the behaviour they buy goes away
with nothing failing except the checksum.

`tests/test_server_contract.py::test_the_vendored_patches_are_still_applied` asserts each one is
present, which is the half a checksum cannot do: a checksum catches an unexpected change and says
nothing about an expected one going missing.

## TransformControls.js — `rotationSpeed`

Upstream has `rotationSnap`, which quantises the rotation *after* the fact, and no way at all to
slow the hand down. `ROTATION_SPEED` is a `const` local to `_onPointerMove`.

Aiming a camera 70 m from the pitch is a tenth-of-a-degree job — at a 3000 px focal, 0.1° moves
the overlay about 5 px, which is the scale the eye is being asked to judge at. At the stock speed
a short drag turns through whole degrees and overshoots every time.

Two lines: a `defineProperty( 'rotationSpeed', 1 )` beside the other knobs, and `ROTATION_SPEED`
multiplied by it. `1` is upstream's behaviour exactly, so the patch is inert until something sets
it. `pitch_view.js` sets 0.25, and 0.05 while Alt is held.
