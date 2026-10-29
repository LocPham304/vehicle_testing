"""Discover and operate only the kernel GPIO PWM provider for the lift."""

import importlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch


class GPIOPWMDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.discovery = importlib.import_module("vehicle_testing.hardware.pwm")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def chip(self, index, pin=18, compatible=b"pwm-gpio\0"):
        chip = self.root / f"pwmchip{index}"
        node = chip / "device" / "of_node"
        node.mkdir(parents=True)
        (node / "compatible").write_bytes(compatible)
        (node / "gpios").write_bytes(b"\0\0\0\1" + pin.to_bytes(4, "big") + b"\0" * 4)
        (chip / "npwm").write_text("1", encoding="ascii")
        return chip

    def test_matches_gpio_and_driver_instead_of_first_chip(self):
        self.chip(0, compatible=b"brcm,bcm2835-pwm\0")
        self.chip(1, pin=17)
        self.chip(4)
        self.assertEqual(self.discovery.find_gpio_pwm_chip(18, self.root), 4)

    def test_missing_provider_never_falls_back_to_claw_chip(self):
        self.chip(0, compatible=b"brcm,bcm2835-pwm\0")
        with self.assertRaisesRegex(RuntimeError, "pwm-gpio,gpio=18"):
            self.discovery.find_gpio_pwm_chip(18, self.root)

    def test_ambiguous_provider_is_rejected(self):
        self.chip(1)
        self.chip(2)
        with self.assertRaises(RuntimeError):
            self.discovery.find_gpio_pwm_chip(18, self.root)

    def test_malformed_gpio_property_is_rejected(self):
        node = self.chip(1) / "device" / "of_node"
        (node / "gpios").write_bytes(b"18")
        with self.assertRaises(RuntimeError):
            self.discovery.find_gpio_pwm_chip(18, self.root)

    def test_claw_rejects_gpio_chip_after_provider_renumbering(self):
        self.chip(0)
        self.chip(2, compatible=b"brcm,bcm2835-pwm\0")
        with self.assertRaisesRegex(RuntimeError, "CLAW_PWM_CHIP"):
            self.discovery.validate_claw_pwm_chip(0, self.root)
        self.discovery.validate_claw_pwm_chip(2, self.root)

    def test_checker_reports_missing_provider_without_creating_channels(self):
        checker = importlib.import_module("vehicle_testing.cli.check_pwm")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(checker.main([], sysfs_root=self.root), 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_read_only_checker_prints_provider_without_opening_output(self):
        self.chip(3)
        self.chip(1, compatible=b"brcm,bcm2835-pwm\0")
        checker = importlib.import_module("vehicle_testing.cli.check_pwm")
        result = io.StringIO()
        with patch("vehicle_testing.hardware.servos.KernelPWMLiftOutput") as output, redirect_stdout(result):
            self.assertEqual(checker.main([], sysfs_root=self.root), 0)
        output.assert_not_called()
        self.assertIn("pwmchip3", result.getvalue())
        self.assertIn("BCM 18", result.getvalue())
        self.assertIn("CHE DO THU", result.getvalue())
        self.assertNotIn("tam khoa", result.getvalue())


class KernelLiftOutputTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hardware.servos")
        calibration = patch.multiple(self.module, SERVO_CALIBRATED=True,
                                    SERVO_DOWN_PULSE_US=1420.0, SERVO_UP_PULSE_US=1080.0)
        calibration.start()
        self.addCleanup(calibration.stop)
        self.hardware = Mock()
        self.pwm = self.hardware.HardwarePWM.return_value
        self.discovery = patch.object(self.module, "find_gpio_pwm_chip", return_value=3)
        self.find = self.discovery.start()
        self.addCleanup(self.discovery.stop)

    def output(self):
        with patch.dict("sys.modules", {"rpi_hardware_pwm": self.hardware}):
            return self.module.KernelPWMLiftOutput()

    def test_uses_discovered_provider_and_keeps_pwm_running_between_updates(self):
        output = self.output()
        self.find.assert_called_once_with(18)
        self.hardware.HardwarePWM.assert_called_once_with(pwm_channel=0, hz=50, chip=3)
        self.pwm.stop.assert_called_once()
        output.set_angle(-10)
        self.assertAlmostEqual(self.pwm.start.call_args.args[0], 7.1)
        output.set_angle(-9.999)  # Same rounded pulse: no change/restart.
        self.pwm.change_duty_cycle.assert_not_called()
        output.set_angle(80)
        self.assertAlmostEqual(self.pwm.change_duty_cycle.call_args.args[0], 5.4)
        self.pwm.start.assert_called_once()
        output.release()
        output.set_angle(80)
        self.assertEqual(self.pwm.start.call_count, 2)

    def test_user_tested_450_us_lift_endpoint_is_accepted_but_lower_values_are_rejected(self):
        with patch.multiple(self.module, SERVO_DOWN_PULSE_US=450.0, SERVO_UP_PULSE_US=1400.0):
            output = self.output()
            output.set_angle(-10)
            self.pwm.start.assert_called_once_with(2.25)
            output.set_angle(80)
            self.assertAlmostEqual(self.pwm.change_duty_cycle.call_args.args[0], 7.0)
        self.pwm.change_duty_cycle.reset_mock()
        with patch.object(self.module, "SERVO_DOWN_PULSE_US", 449.0):
            with self.assertRaises(ValueError):
                output.set_angle(-10)
        self.pwm.change_duty_cycle.assert_not_called()

    def test_unmeasured_profile_opens_kernel_output_with_an_explicit_warning(self):
        with patch.object(self.module, "SERVO_CALIBRATED", False):
            with self.assertLogs(self.module.__name__, level="WARNING") as logs:
                output = self.output()
        self.assertIn("chua do", " ".join(logs.output))
        output.set_angle(-10)
        self.pwm.start.assert_called_once()

    def test_missing_pulses_refuse_even_before_discovery(self):
        with patch.object(self.module, "SERVO_DOWN_PULSE_US", None):
            with self.assertRaises(ValueError):
                self.output()
        self.find.assert_not_called()
        self.hardware.HardwarePWM.assert_not_called()

    def test_missing_provider_does_not_open_another_pwm(self):
        self.find.side_effect = RuntimeError("Missing pwm-gpio")
        with self.assertRaises(RuntimeError):
            self.output()
        self.hardware.HardwarePWM.assert_not_called()

    def test_invalid_angle_or_calibration_never_changes_duty(self):
        output = self.output()
        for angle in (-11, 81, float("nan")):
            with self.assertRaises(ValueError):
                output.set_angle(angle)
        with patch.object(self.module, "SERVO_DOWN_PULSE_US", None):
            with self.assertRaises(ValueError):
                output.set_angle(0)
        self.pwm.start.assert_not_called()
        self.pwm.change_duty_cycle.assert_not_called()

    def test_close_stops_only_own_provider_and_is_idempotent(self):
        output = self.output()
        self.pwm.stop.reset_mock()
        output.close()
        output.close()
        self.pwm.stop.assert_called_once()
        with self.assertRaises(RuntimeError):
            output.set_angle(0)

    def test_partial_initialization_and_stop_errors_are_reported(self):
        self.pwm.stop.side_effect = [OSError("stop failed"), None]
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            self.output()
        self.assertEqual(self.pwm.stop.call_count, 2)


if __name__ == "__main__":
    unittest.main()
