# Mecanum turning implementation plan

Goal: test left/right in-place turns in vehicle_testing before firmware integration.

Design: use the confirmed physical FR/FL/RL/RR mapping. Left means right wheels
forward and left wheels backward; right reverses that pattern. Preserve per-wheel
inversion and the existing PWM-off/direction/PWM-on/stop sequence. Firmware and
the original individual-wheel tests stay untouched.

Approaches: time calibration works with the currently tested PWM output; IMU or
encoder feedback requires additional verified hardware. Use time calibration for
this test phase. It estimates angles and does not measure chassis heading.

Interface: `turn_left(angle)`, `turn_right(angle)`, and `turn(direction, angle)`.
CLI: `trai <degrees>` / `phai <degrees>`, queued until `chay`, mixed with the existing
timed move/pause commands. Degrees must be positive and finite. Turns use a fixed
TURN_SPEED=0.3, independent of forward/backward speed. Left and right each have
a seconds-per-degree setting initially 0.0133, borrowed from old source and
explicitly uncalibrated on this car. Changing PWM requires recalibration.

Implementation and verification:

- [x] Add failing tests for motor direction, simultaneous retained PWM, stop on
  interruption/write error, inversion, invalid input/configuration, separate
  calibration, queued mixed scripts, and CLI entry points.
- [x] Correct stale stem_project package references inside vehicle_testing.
- [x] Add turn calibration config and share timed output sequencing in the controller.
- [x] Add degree-based parsing/dispatch and fixed-PWM turn logs.
- [x] Document dry-run, physical tests, and separate left/right angle calibration.
- [x] Run all vehicle_testing tests and both direct/module dry-run entry points.

Software results: 48 tests passed; direct-file and module entry points both ran a
mixed move/turn/pause script in dry-run mode with exit code 0.

Validation boundary: automated checks use in-memory channel output only. Actual
turn direction, mechanical stopping and angle accuracy require testing on the car.
