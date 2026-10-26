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
