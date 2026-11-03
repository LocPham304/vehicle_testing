# WebSocket Device Identity Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation. The user approved implementing one-time assignment and persistent local identity; no further approval is needed.

**Goal:** Configure each Pi's registered robot UUID/name once, then start its WebSocket receiver with `python wifi_websocket_receiver.py --dry-run`.

**Architecture:** Store `uuid` and `name` in a per-Pi UTF-8 JSON file at the checkout root. An explicit `--setup` command validates and saves the assignment without opening a server or GPIO. Normal startup reads this file; existing explicit identity flags remain compatible.

**Tech Stack:** Python standard library, existing websockets server, unittest.

**Spec:** User-approved chat design: one physical Pi per robot; assign a registered robot once and load the identity on subsequent starts.

## Global Constraints

- No automatic assignment from incoming FE messages or from the first API record.
- No backend or FE code changes and no dependency on the authenticated devices API at startup.
- Preserve Upload/EXEC ordering, UUID filtering, one controller, preview/dry-run/hardware modes, and disconnect cleanup.
- Never open GPIO or run hardware during setup or verification.
- Local `device_identity.json` is ignored by Git; ship only an example.
- Keep discovery without a target UUID working; an explicitly different UUID must be ignored.
- Preserve unrelated files and existing wheel-gain configuration. No commits requested.

## Review Focus

- Missing or malformed identity must stop before starting a server.
- Config lookup must use the checkout root, independent of current working directory.
- Unicode names and invalid/empty identities must be handled explicitly.
- Multiple robots must respond only to matching targeted UUIDs.
- Explicit legacy UUID/name flags must not inherit another robot's saved name.

### Task 1: Persist and use per-Pi identity

**Files:**
- Create `runtime/identity.py` and `tests/test_device_identity.py`.
- Modify `connections/wifi/websocket_receiver.py`, `tests/test_wifi_websocket.py`, `.gitignore`.
- Create `device_identity.example.json`.

**Interfaces:** `DeviceIdentity(uuid, name)`, `load_identity(path)`, `save_identity(path, identity)` and shared identity validation. Receiver CLI adds `--setup` and `--identity-file`; `--device-id` becomes optional when a saved identity exists.

- [x] Write tests for persistence, invalid data, missing config, setup, startup without identity flags, legacy overrides and UUID filtering across five receivers.
- [x] Run the new tests and confirm the missing functionality fails.
- [x] Implement validated JSON persistence, one-time setup, local config loading and targeted identify filtering.
- [x] Run focused unit and WebSocket loopback checks, then the full existing suite; distinguish unrelated baseline failures.

### Task 2: Make the workflow testable on the user's Pi

**Files:** Modify `docs/WIFI_WEBSOCKET.md`, `docs/RUN_COMMANDS.md`, `README.md`.

- [x] Document one-time setup, subsequent dry-run/hardware startup, config location, per-Pi uniqueness, and unchanged FE payloads.
- [x] Verify setup and a real identify round trip with a temporary config; check only the intended files changed.
- [x] Report exact commands and verification limits. Do not configure or restart the user's physical Pi remotely.

## Verification and review

- New functionality failed before implementation: 13 expected failures in 15 checks (missing config APIs/CLI and wrong-target identify response).
- Final focused checks: 63/63 passed, including loopback, Unicode persistence, reassigning an existing file, legacy overrides and a five-robot routing simulation.
- Whole suite: 406 tests, 2 pre-existing wheel-gain failures, 5 skipped. Two supplementary identity tests were added afterward and passed in the final focused run.
- Real local smoke check: setup in one process, load config in another receiver process, identify, ignore a wrong UUID, upload and EXEC in dry-run, and observe block/done events. No GPIO or physical Pi was used.
- Local loopback used installed websockets 17.4; target dependency remains websockets 15.x and no new dependency/API was introduced.
- Fresh read-only review found no blockers; its suggested name-only override check was added and passed.
- Ruling: keep setup local and explicit rather than querying the devices API, because the API requires authentication and no hardware-to-registered-UUID mapping was supplied.
- Ruling: preserve untargeted identify for discovery; filter UUID when explicitly present, as well as preserving existing Upload/EXEC guards.
