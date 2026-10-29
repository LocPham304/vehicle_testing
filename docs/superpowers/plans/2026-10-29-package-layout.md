# Package layout refactor

Goal: group implementation by responsibility while keeping the existing Pi and
laptop startup commands and the user's editable config.py intact.

Routine organization choices for this refactor:
- hardware/: motors.py, servos.py, pwm.py, ultrasonic.py and displays/.
- runtime/: parser.py, runner.py, session.py, console.py, paths.py.
- connections/: mqtt/, usb/, wifi/, with receiver/client/protocol modules.
- cli/: robot.py and check_pwm.py for local terminal control and diagnostics.
- Root CLI files become small compatibility launchers. controller.py remains a
  compatibility import for the three scripts outside this nested repository.
- Canonical implementations import canonical paths. Legacy launchers alias the
  module object, so existing monkeypatches and imported globals are not copies.
- Root config.py, requirements files and examples/scratch_sample.txt stay put.
- Historical design notes remain historical; current README/API guides describe
  the new locations. Tests of deleted probe_servo/probe_lift_pwm are retained
  under tests/legacy, outside active discovery, with an explicit README.

Implementation steps:
1. Record baseline and add layout compatibility tests (canonical imports, legacy
   module identity, direct/module CLI help, sample resolution from another cwd).
2. Move implementations, update internal imports and tests, resolve defaults via
   runtime.paths, and add the compatibility launchers without hardware changes.
3. Update README with the folder tree and a map of old names to implementations.
4. Run active unit tests and actual HTTP/MQTT loopback integration with simulated
   outputs; check all startup help commands, external wheel-script imports and
   Git diff. No robot hardware is opened, no calibration constants are changed.

Baseline before edits: 300 tests, 16 errors from the two already absent probe
modules, 1 local MQTT socket failure due to sandbox permissions, 3 opt-in HTTP
tests skipped. Keep this distinction visible when reporting refactor validation.

Verification after refactor: all 288 active tests passed with HTTP integration
enabled and local sockets allowed (including actual Mosquitto and HTTP loopback
with simulated outputs). The count is 300 baseline tests minus 16 archived probe
checks plus 4 layout/compatibility tests. Legacy imports share canonical module
objects; all 11 old CLI help commands work from another working directory.
Config, dependencies and sample contents are unchanged. No physical Pi test.
