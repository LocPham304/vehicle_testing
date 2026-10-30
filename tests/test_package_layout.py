"""Moving implementations must preserve commands, imports and sample paths."""

import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = {
    "main": "cli.robot",
    "check_lift_pwm": "cli.check_pwm",
    "ultrasonic": "hardware.ultrasonic",
    "seven_segment": "hardware.displays.seven_segment",
    "test_displays": "hardware.displays.matrix",
    "scratch_runner": "runtime.runner",
    "scratch_receiver": "connections.mqtt.receiver",
    "usb_client": "connections.usb.client",
    "usb_receiver": "connections.usb.receiver",
    "wifi_client": "connections.wifi.client",
    "wifi_receiver": "connections.wifi.receiver",
    "wifi_udp_receiver": "connections.wifi.udp_receiver",
    "bluetooth_client": "connections.bluetooth.client",
    "bluetooth_receiver": "connections.bluetooth.receiver",
}


class PackageLayoutTests(unittest.TestCase):
    def test_old_imports_alias_the_same_implementation_not_copied_globals(self):
        for old, new in {**LAUNCHERS, "controller": "hardware.motors"}.items():
            with self.subTest(module=old):
                self.assertIs(importlib.import_module("vehicle_testing." + old),
                              importlib.import_module("vehicle_testing." + new))

    def test_all_old_script_help_commands_work_from_outside_project(self):
        with tempfile.TemporaryDirectory() as cwd:
            for name in LAUNCHERS:
                with self.subTest(command=name):
                    result = subprocess.run(
                        [sys.executable, "-B", str(PACKAGE_ROOT / (name + ".py")), "--help"],
                        cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("usage:", result.stdout)

    def test_module_startup_works_for_legacy_and_canonical_names(self):
        for name in ("wifi_receiver", "connections.wifi.receiver", "scratch_runner", "runtime.runner"):
            with self.subTest(module=name):
                result = subprocess.run(
                    [sys.executable, "-B", "-m", "vehicle_testing." + name, "--help"],
                    cwd=PACKAGE_ROOT.parent, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_runner_and_console_use_same_sample_regardless_of_module_location(self):
        from vehicle_testing.runtime import console, runner
        self.assertEqual(runner.DEFAULT_FILE, PACKAGE_ROOT / "examples" / "scratch_sample.txt")
        self.assertEqual(console.DEFAULT_FILE, runner.DEFAULT_FILE)
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run(
                [sys.executable, "-B", str(PACKAGE_ROOT / "scratch_runner.py"), "--dry-run"],
                cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TIEN", result.stdout)


if __name__ == "__main__":
    unittest.main()
