# Scratch MQTT parse preview implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation. The approved scope is recorded below; no hardware execution or subagent work is required.

**Goal:** Receive generated Scratch Python via MQTT and print its validated markers and commands in order.

**Architecture:** A pure AST parser creates an immutable program. An MQTT adapter caches only validated programs and prints them on upload and execute. The same parser has an offline file entry point. Execution, hardware imports and block-progress publication are deferred to the runner stage.

**Tech stack:** Python 3.10+, standard-library AST/dataclasses/unittest, optional paho-mqtt 2.1.0.

**Spec:** This document, section Approved scope.

## Approved scope

- Work in `vehicle_testing`, preserving manual test programs and FE/BE sources.
- Parse `report_block("id")` and `robot.sendCmd("command:value")`; preserve standalone markers, order, original IDs, Unicode text, duplicate actions and source line numbers.
- Attach commands to their nearest previous marker; commands without a marker carry no block ID.
- Support `move_forward`, `move_backward` in seconds; `turn_left`, `turn_right` in degrees; `led_strip` as text. Reject unsupported syntax/commands and invalid numeric values with a line number.
- Receive `device/<UUID>/code` and `/execute`. Upload validates/caches; execute prints a preview only. Heartbeat remains `idle`; never report simulated actions as hardware execution.
- Invalid upload/UTF-8 invalidates the old cached program. Ignore retained execute, reject unexpected execute payloads, clear cached programs on disconnect.
- No exec/eval/subprocess, GPIO, motor, serial or firmware imports. No live robot/broker action in verification.

## Review focus

1. Two markers before a command are retained separately.
2. Text containing colons/quotes/backslashes/accents remains intact.
3. An invalid later command rejects the whole upload, not a partial program.
4. Invalid replacement uploads cannot leave an older program ready for execute.
5. Direct/module CLI help and offline parsing work without paho or hardware libraries.

## Tasks

- [x] Add sample fixture and failing parser tests; implement the pure parser and readable preview.
- [x] Add failing receiver tests; implement MQTT callbacks, idle heartbeat and offline/network CLI.
- [x] Add optional dependency and user instructions; verify sample, targeted tests, full suite and diffs.

## Verification record

- Watched parser and receiver import tests fail before adding their modules.
- An offline subprocess test exposed Windows cp1252 output failure for Vietnamese; fixed stdout UTF-8 in the CLI and reran the same test successfully.
- 24 targeted tests pass, including the exact sample (7 markers, 6 commands), invalid replacement uploads, idle-only heartbeat and network-client cleanup.
- Full vehicle suite: 229 tests, zero assertion failures, 16 pre-existing import errors: 8 in `test_probe_lift_pwm` and 8 in `test_probe_servo`, referencing absent probe modules.
- Verified direct/module help and offline CLI. Created a client using the existing environment's real paho-mqtt 2.1.0; callbacks configured, client remained disconnected. No live broker/Pi or hardware validation occurred.
- Diff and syntax checks pass. No Git commit/push was requested.

Ruling: This preview accepts at most 64 KiB UTF-8 and 1000 events; document this smaller limit than the backend's upload limit. It bounds the first-stage AST parser; larger programs need an explicit future limit review.
