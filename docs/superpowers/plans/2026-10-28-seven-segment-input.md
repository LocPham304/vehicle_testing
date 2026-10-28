# Seven-segment manual and distance input plan

**Goal:** Support manual numbers and live ultrasonic distance through one reusable display API.

**Approved design:** The user selected both input sources and requested implementation after the design discussion. Display 123 as 0123; `auto` selects ultrasonic readings; a new number selects manual mode; sensor errors display ---- and retry; `thoat`, EOF or Ctrl+C closes resources. Scratch integration and motor behavior are outside this change.

**Architecture:** Extract the existing clock/data transport into `display_link.py` and retain its import in `test_displays.py`. Add `seven_segment.py` with `SevenSegmentDisplay`, manual/auto terminal control and a direct/module CLI. Use the existing `UltrasonicSensor` only when auto is requested. Reuse this API for future Scratch calls.

**Tech stack:** Python 3.10+, RPi.GPIO on Raspberry Pi, unittest with simulated hardware.

**Constraints:** BCM CLK16/DIO6 and sensor TRIG8/ECHO11 by default. Preserve matrix modes. No motor, servo, MQTT or Scratch runtime imports. Round nonnegative finite values to whole units (half up), range 0..9999. Clear only owned pins. Prevent sensor/display pin overlap before opening the sensor.

## Steps

- [x] Add failing behavior tests for formatting, resource ownership, mode switching and sensor recovery.
- [x] Extract transport; implement display API, lazy sensor session and both CLI entry styles.
- [x] Add compatibility entry from `test_displays.py`, document commands and API.
- [x] Run targeted tests, full suite and diff checks; report existing unrelated failures separately.

**Verification:** 44 display/text/ultrasonic tests pass. Full vehicle suite runs 205 tests with zero assertion failures and 16 existing import errors (8 each for the absent `probe_lift_pwm.py` and `probe_servo.py`). Both direct/module help paths pass. Physical LED and sensor behavior remain to be checked on the Pi. No hardware was opened by local verification.

## Review focus

- Sensor is unopened in manual mode and is closed when manual mode resumes.
- Missing/invalid readings never masquerade as zero distance; later valid readings recover.
- Invalid manual input preserves the current mode and display.
- Sensor failure/interrupt cannot prevent LED shutdown and GPIO cleanup.
- Existing matrix and static seven-segment commands remain available.
