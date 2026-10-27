"""Hardware PWM adapter checks without opening GPIO or kernel PWM files."""

import importlib
import unittest
from unittest.mock import Mock, patch


class HardwareClawTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")
        self.hardware = Mock()
        self.pwm = self.hardware.HardwarePWM.return_value

    def output(self):
        with patch.dict("sys.modules", {"rpi_hardware_pwm": self.hardware}):
            return self.module.HardwarePWMClawOutput(pin=12)

    def test_endpoints_continuous_updates_and_duplicate_suppression(self):
        output = self.output()
        self.hardware.HardwarePWM.assert_called_once_with(pwm_channel=0, hz=50, chip=0)
        self.pwm.stop.assert_called_once()
        output.set_angle(0)
        self.pwm.start.assert_called_once_with(2.5)
        output.set_angle(0.001)
        self.pwm.change_duty_cycle.assert_not_called()
        output.set_angle(100)
        self.assertAlmostEqual(self.pwm.change_duty_cycle.call_args.args[0], 8.055)
        self.pwm.start.assert_called_once()  # Do not restart the PWM each step.
        output.release()
        output.set_angle(100)
        self.assertEqual(self.pwm.start.call_count, 2)

    def test_invalid_angles_do_not_write_and_close_is_idempotent(self):
        output = self.output()
        for angle in (-1, 101, float("nan"), float("inf")):
            with self.subTest(angle=angle), self.assertRaises(ValueError):
                output.set_angle(angle)
        self.pwm.start.assert_not_called()
        self.pwm.change_duty_cycle.assert_not_called()
        self.pwm.stop.reset_mock()
        output.close()
        output.close()
        self.pwm.stop.assert_called_once()
        with self.assertRaises(RuntimeError):
            output.set_angle(50)

    def test_missing_overlay_reports_setup_error_without_software_fallback(self):
        self.hardware.HardwarePWM.side_effect = OSError("PWM overlay missing")
        with self.assertRaisesRegex(RuntimeError, "dtoverlay"):
            self.output()

    def test_initial_stop_error_still_attempts_cleanup(self):
        self.pwm.stop.side_effect = [OSError("stop failed"), None]
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            self.output()
        self.assertEqual(self.pwm.stop.call_count, 2)

    def test_failed_write_is_not_cached(self):
        output = self.output()
        self.pwm.start.side_effect = [OSError("start failed"), None]
        with self.assertRaises(OSError):
            output.set_angle(100)
        output.set_angle(100)
        self.assertEqual(self.pwm.start.call_count, 2)

    def test_close_error_is_reported_and_prevents_reuse(self):
        output = self.output()
        self.pwm.stop.side_effect = OSError("stop failed")
        with self.assertRaises(OSError):
            output.close()
        with self.assertRaises(RuntimeError):
            output.set_angle(0)

    def test_wrong_pin_rejected_before_import(self):
        with patch.object(self.module.importlib, "import_module") as importer:
            with self.assertRaises(ValueError):
                self.module.HardwarePWMClawOutput(pin=18)
        importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
