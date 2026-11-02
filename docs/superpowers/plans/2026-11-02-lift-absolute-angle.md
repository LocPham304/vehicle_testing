# Absolute Lift Angle Integration Plan

**Goal:** Integrate the user-tested standalone lift into main: `nang <angle> [seconds]`
and `ha <angle> [seconds]`, absolute angles 0..90, releasing PWM after each move.

**Architecture:** Keep `main.py` as its compatibility launcher and the existing
draft/`chay` session. Add target angles to HandController and use Adafruit Servo
with a kernel pwm-gpio adapter on BCM 18, matching `tests/test_lift_angle.py`.

**Tech Stack:** Python, unittest, adafruit-circuitpython-motor, rpi-hardware-pwm.

**Spec:** User-approved standalone `tests/test_lift_angle.py` and the explicit
instruction in this conversation to integrate it without `--hold`.

## Constraints and review focus

- Angles 0..90 inclusive; pulses 450..1400 us; 50 Hz; 20 ms updates; 0.1 s settle.
- Default 2 seconds; optional duration 0.2..60 seconds, as in the standalone.
- Stop wheels before lift execution. Drafting, invalid commands and dry-run open no PWM.
- Preserve claw behavior, motor configuration, cleanup and interruption handling.
- Require the angle in terminal commands; the old seconds-only syntax is replaced.
- Preserve the internal endpoint methods' positional seconds API for existing callers.
- No physical hardware runs, commits or pushes during this integration.

## Tasks

- [x] Establish baseline: 343 tests; 2 existing wheel-gain failures, 5 skips.
- [x] Add failing tests for absolute parsing, limits, pulse mapping, dispatch and release.
- [x] Update config.py, cli/robot.py and hardware/servos.py; add the motor dependency.
- [x] Update existing lift tests for 0/90 and test the Adafruit/PWM adapter contract.
- [x] Update README and calibration notes for the main commands and start position.
- [x] Run focused checks, full unittest discovery, CLI dry-run and diff review.
- [x] Obtain code review and resolve findings within this scope.

## Baseline failures outside this change

`test_wheel_gain.WheelGainTests.test_config_contains_user_requested_trial_gains`
and `test_log_reports_effective_pwm_including_inactive_wheels`: tests expect
FR gain 0.90; the clean checkout has FR gain 1.00. Preserve that configuration.

## Verification

- 81 focused lift/claw/CLI tests pass, including trajectory comparison with the
  accepted standalone and Adafruit initialization-failure cleanup.
- Full suite: 353 tests; the same 2 pre-existing wheel-gain failures, 5 skips.
- Main launcher CLI dry-run passes from the vehicle_testing directory; invalid
  angles are rejected and valid drafts run only on `chay`.
- `git diff --check` passes. No actual GPIO waveform or physical main run measured.
- The external Adafruit API is represented by a PWM-contract test double here;
  the user has physically tested the standalone using the real library.
- Independent review found no actionable issues and separately passed 68 focused
  tests plus `git diff --check`.
