# Lift kernel GPIO PWM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep BCM 18 wiring and the seconds-only lift commands while replacing RPi.GPIO edge generation with the supported kernel pwm-gpio driver.

**Architecture:** Discover a single pwm-gpio chip whose device-tree GPIO property selects BCM 18; never infer its chip number from enumeration order. Use the existing rpi-hardware-pwm sysfs API on that provider's channel 0. Keep independent hardware PWM0 on BCM 12 and preserve the calibration interlock after confirmed mechanical contact.

**Tech Stack:** Python, pathlib, Linux pwm-gpio/sysfs, rpi-hardware-pwm, unittest mocks and temporary filesystem fixtures.

**Spec:** User-approved direction and docs/lift-calibration.md. Runtime interface remains nang [seconds] -> 80 and ha [seconds] -> -10. The actual endpoint pulses are unknown and must not be invented.

## Global constraints

- No physical robot commands, boot edits, or source commits from this workspace.
- No fallback to RPi.GPIO or the claw PWM provider if the lift provider is absent.
- Real lift movement requires measured endpoint calibration; dry-run remains available.
- Keep the working claw's behavior and configuration.

## Tasks

- [x] Write failing tests for device-tree discovery, separate providers, lifecycle, and calibration checks before output creation.
- [x] Add gpio_pwm.py discovery and KernelPWMLiftOutput; route main.py lift commands to it.
- [x] Add a read-only check_lift_pwm.py diagnostic, including missing/ambiguous provider handling.
- [x] Document the additional overlay, reboot, diagnostic, and measured calibration fields without guessed pulse defaults.
- [x] Run focused tests, full suite, dry-run smoke checks, diff checks, and scoped independent review. Report physical calibration as outstanding.

## Execution evidence

- Discovery test observed RED (missing gpio_pwm module), then the 11 initial new tests passed.
- Focused kernel/claw adapters and integration: 37 tests passed.
- Full suite: 143 tests passed. compileall and git diff --check passed.
- Standalone CLI dry-run: nang 2, ha 2, mo_cang 2, dong_cang 2 completed without hardware imports.
- Ruling: also validate the configured claw provider before opening PWM — adding a driver can renumber chips and route the claw to BCM 18 otherwise. A missing/mismatched device-tree descriptor will now stop the claw rather than trying the configured chip blindly.
- Actual endpoint pulses remain unknown; calibration stays False/None. No real motion, boot edits, or source commits performed.
- Independent whole-change review: no actionable findings; reviewer independently passed all 143 tests. Physical timing, clearance, loaded movement and cross-servo operation remain unverified. Exact installed rpi-hardware-pwm 0.3.1 source was unavailable; upstream API and the already-working claw use the same constructor/start/stop/duty calls.
