# Timed Mecanum strafing

Extend vehicle_testing with the sideways motion requested by the user, before
firmware integration. Reuse the existing timed-output sequence and script queue.

Interface: `MotorController.strafe(direction, seconds, speed=DEFAULT_SPEED)`;
direction is `left` or `right`. CLI commands: `ngang_trai <seconds> [PWM]` and
`ngang_phai <seconds> [PWM]`. Commands are queued until `chay` and can be mixed
with existing moves, turns and pauses. Omitted PWM uses DEFAULT_SPEED per command.
The input is seconds, not centimeters or degrees.

For the documented Mecanum X arrangement and confirmed physical forward:
left means FR/RL forward, FL/RR backward; right is the exact inverse. Validate all
four wheel names, positive finite duration, and PWM in (0, 1] before output.
Retain per-wheel inversion, PWM-off before directions, and stop in finally.

Steps:
- [x] Write tests and confirm failure before implementation.
- [x] Add controller method and CLI parse, dispatch, help and queue labels.
- [x] Update README with sideways commands and physical verification limits.
- [x] Run all tests and both CLI entry points in dry-run mode.
- [x] Review scoped changes for direction and stop behavior.

Results: 58 tests passed. Direct and module CLI entry points ran mixed scripts
with exit code 0. Independent review found no important defects. SHA256 check
confirmed config.py was unchanged. Physical sideways travel is still unverified.

Preserve the user's current config: TURN_SPEED=0.5, left/right factors=0.0179,
and all pin mappings. Turn tests must follow calibration settings rather than
assuming the original 0.0133 value. No motor hardware is accessed during checks.

## 2026-10-26: per-wheel sideways PWM calibration

The supplied video shows sideways travel with longitudinal drift and heading
change. The user confirmed traction on all wheels, freely turning rollers and
even floor contact. Actual wheel speed remains unmeasured.

Add independent STRAFE_LEFT_GAINS / STRAFE_RIGHT_GAINS maps with neutral all-1.0
defaults. Effective PWM = base PWM * wheel gain. Require exactly FR/FL/RL/RR,
numeric finite gains in (0,1], validated before movement output. Keep physical
directions, stop behavior, pin maps, TURN_SPEED and turn factors intact. Only
strafe passes per-wheel speeds to the common timed driver; move/turn stay uniform.
Log effective sideways PWM and document controlled field calibration, without
claiming these defaults fix the observed physical drift.

- [x] Add failing tests for independent maps, invalid config, isolation of other
  motions, inversion, startup/stop behavior and effective-PWM logs.
- [x] Implement gain config, sideways-only scaling and log/help updates.
- [x] Document neutral defaults, restart requirement and one-change-at-a-time trials.
- [x] Verify all 64 tests pass; independent review found no important defects.
- [x] Verify direct/module CLI and non-neutral gains in dry-run integration.

Both entry points passed with neutral gains. An in-memory trial with front-wheel
gains=0.95 logged FR/FL=47.5% and RL/RR=50.0% at base PWM=50%, without hardware.

Field calibration and physical correction are pending testing on the car.
