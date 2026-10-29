# Bluetooth Classic SPP implementation

Scope: vehicle_testing only; add Windows laptop to Pi 4 Bluetooth control with
the same upload/run/stop/status workflow and existing parser/runner. Keep config,
GPIO mappings, FE/BE and other receivers unchanged. Implementation choice: SPP
with BlueZ ProfileManager on Pi and an outgoing Bluetooth COM port on Windows.
BLE GATT is not implemented. This fits the existing serial JSON client; browser
integration remains a separate step, as it does for the current USB console.

Files: connections/bluetooth/{receiver,bluez,client}.py plus package initializer,
root bluetooth_receiver.py and bluetooth_client.py launchers, requirements-
bluetooth.txt, docs/BLUETOOTH.md, README, tests/test_bluetooth.py and client tests.

Design:
- Register standard SPP UUID 00001101-0000-1000-8000-00805f9b34fb via BlueZ D-Bus
  Profile1; authentication and service authorization required. No boot edits,
  pairing-agent bypass, custom PIN or external Bluetooth module.
- BlueZ supplies the authorized RFCOMM socket FD. A single connection worker
  owns a fresh RobotSession; a second connection is rejected until cleanup.
  D-Bus callbacks never block on script execution.
- Reuse existing bounded UTF-8 JSON frames and request-ID deduplication. Upload
  only stores validated code. Default preview, --dry-run simulation, --run real
  hardware. Status explicitly distinguishes all three modes.
- Client uses shared USBClient protocol with configurable transport labels and
  the shared console. Add a Bluetooth COM selector and bt> prompt.
- EOF, socket/write failure, Bluetooth disconnection or missing valid heartbeat
  for 5 seconds cancels execution, closes the connection and clears pending code.
  Reconnection uses a new session and requires uploading again.
- Imports/help work without Linux D-Bus/GLib on Windows. Load Pi-only libraries
  lazily; install BlueZ/python3-dbus/python3-gi through apt, not pip on Windows.

Steps: write failing tests; implement stream ownership and BlueZ adapter; add
COM client and compatibility launchers; test FD lifecycle, concurrency, Unicode,
malformed/oversized frames, timeout/stop/reconnect, actual client/receiver stream
exchange with simulated runner; run existing transport/hardware unit regressions.

Sources checked: official BlueZ ProfileManager/Profile1 documentation and test-
profile example; Microsoft Windows SPP/RFCOMM support documentation. Document
pairing and outgoing COM selection. Software tests cannot verify the actual
Pi radio, Windows Bluetooth driver, pairing UI or motor behavior.

Verified on Windows: all 307 active tests passed with HTTP and Bluetooth socket
integration enabled (288 existing + 19 Bluetooth tests). Includes real socketpair
byte exchange, simulated runner and existing actual HTTP/MQTT loopback tests;
BlueZ D-Bus is represented by test doubles, not an actual Pi service. Both new
root commands support --help from another working directory without Linux-only
dependencies. config.py, existing sample and stem_firmware are unchanged.
