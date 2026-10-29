# USB serial implementation

Scope: laptop Windows -> data cable -> Pi 4 USB-C CDC ACM gadget. Source is
in vehicle_testing as requested by the user; stem_firmware stays unchanged.
USB-C availability while battery-powered was confirmed by the user.
Board power isolation and the running Pi kernel must still be checked physically.

Design: newline-delimited UTF-8 JSON carrying id/action/code; upload and run
are separate. One bounded pending program and one worker; stop interrupts motor
and LED timed waits. Client pings every second; 5 seconds without valid traffic
invalidates pending data and cancels execution. Each request gets a response;
recent mutating request IDs are deduplicated. No exec/eval.

Files: script_session.py, usb_protocol.py, usb_receiver.py, usb_client.py,
tests/test_usb*.py, docs/USB.md, requirements-usb.txt. Reuse scratch_parser.py
and scratch_runner.py, without changing MQTT behavior or hardware calibration.

Steps:
- Write failing tests for upload-only, execution snapshots, busy/stop/error,
  duplicate IDs, fragmented/oversized/invalid frames, link loss and sender split.
- Reuse the already tested parser, motor and matrix logic.
- Implement USB framing/session/client and preview, simulation and hardware modes.
- Verify without hardware, including a simulated duplex serial connection.
- Document one-time dwc2/g_serial setup, COM selection and USB source deployment.

Limits: only the existing sequential literal Scratch command subset, seconds for
movement and degrees for turns. No service autostart, other transports, arbitrary
Python support, or new servo/sensor Scratch commands in this step.

Verification: 72 targeted USB/parser/runner/MQTT regression tests passed. Includes
a duplex simulated serial link with fragmented UTF-8, separate upload/run,
notifications, timeout reset, duplicate request IDs and startup cleanup failure.
Both direct entrypoints expose --help without hardware libraries. Git diff check
passed; stem_firmware tracked files remain unchanged. Physical CDC enumeration,
pyserial driver I/O on the real cable, power isolation and USB-triggered motion
remain for on-device verification.
