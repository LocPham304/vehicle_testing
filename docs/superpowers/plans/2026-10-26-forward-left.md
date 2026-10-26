# Forward-left diagonal movement implementation plan

> **For agentic workers:** Implement the steps in this session using a failing-test-first cycle, then review the complete change.

**Goal:** Add timed forward-left travel at 3*pi/4 without commanding chassis rotation.

**Architecture:** `MotorController.move_forward_left(seconds, speed=DEFAULT_SPEED)`
uses FR/RL forward and FL/RR disabled. Extend the existing timed driver with
`None` as a disabled-wheel direction, keeping its stop/start/finally sequence.
The CLI queues `cheo_tren_trai <seconds> [PWM]` until `chay`.

**Tech Stack:** Python, unittest, existing PCA9685 output abstraction.

**Spec:** User request on 2026-10-26 and the 3*pi/4 wheel-power column at
https://seamonsters-2605.github.io/archive/mecanum/ . The supplied table specifies
FR=1, FL=0, RL=1, RR=0; speed scales the two active wheels directly.

## Global constraints

- Angle is relative to the chassis: x right, y forward; 135 degrees from +x.
- Duration is positive finite seconds; PWM is finite in (0, 1].
- Omitted PWM uses DEFAULT_SPEED for each command.
- Disabled wheels keep PWM, IN1 and IN2 at zero, irrespective of inversion.
- Preserve config.py, its current delays/calibration, existing motions and firmware.
- Do not add wheel gains or a general joystick/angle mixer.
- Verification uses simulation and in-memory output only.

## Review focus

- Inactive-wheel inversion must never enable FL/RR.
- Direction writes must precede PWM; a preceding move must not leave stale output.
- Partial startup failure or Ctrl+C must request a stop on every wheel.
- Invalid parameters, incomplete wheel maps and closed controllers must not drive.
- Queue cancellation, mixed scripts and repeated `chay` must retain existing behavior.

## Task 1: Controller, CLI and documentation

**Files:** controller.py, main.py, tests/test_diagonal.py, README.md.

- [x] Run the existing suite as a baseline.
- [x] Add tests for wheel outputs, inversion, startup order, invalid input,
  interrupted/failed motion, command parsing, mixed queues and cancellation.
- [x] Run the new tests and confirm the missing feature fails.
- [x] Implement `move_forward_left` and optional disabled-wheel directions.
- [x] Add CLI parsing, help, queue labels and dispatch for `cheo_tren_trai`.
- [x] Document wheel powers, units, commands and physical-verification limits.
- [x] Run the complete suite and dry-run both CLI entry points.
- [x] Review the diff, verify config.py unchanged and record the results below.

## Results

Baseline: 58 tests ran, with four failures in pause/turn/strafe tests before
feature implementation. The current configured direction-change delay is 0.5 s;
three test observers confused that delay with their 0.5 s pause, while the fourth
expected a hardcoded 0.003 s delay. Keep config.py unchanged; use a distinct 0.7 s
pause in the affected scripts and assert the configured delay in the turn test.
All four affected tests passed after these test-only changes.

RED: the new controller and parser tests failed because move_forward_left and
cheo_tren_trai did not exist. GREEN: all eight new tests passed after implementation.
The complete suite passed: 66 tests in 21.336 s.
Direct and module CLI entry points passed a mixed script in dry-run/verbose mode;
only FR/RL were enabled in the diagonal segment and a second chay did not replay it.
git diff --check passed and config.py matches HEAD exactly.

Independent read-only review found no actionable issues and independently ran the
eight diagonal tests successfully. Physical angle, heading, coast/brake behavior
and successful stopping still require vehicle/driver evidence. README makes this
boundary explicit. Physical motion is unverified.
