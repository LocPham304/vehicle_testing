"""Hardware PWM adapter checks without opening GPIO or kernel PWM files."""

import importlib
import unittest
from unittest.mock import Mock, patch


class HardwareClawTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hardware.servos")
        self.hardware = Mock()
        self.pwm = self.hardware.HardwarePWM.return_value
        provider = patch.object(self.module, "validate_claw_pwm_chip")
        self.provider = provider.start()
        self.addCleanup(provider.stop)

    def output(self):
        with patch.dict("sys.modules", {"rpi_hardware_pwm": self.hardware}):
            return self.module.HardwarePWMClawOutput(pin=12)

    def test_endpoints_continuous_updates_and_duplicate_suppression(self):
        output = self.output()
        self.hardware.HardwarePWM.assert_called_once_with(pwm_channel=0, hz=50, chip=self.module.CLAW_PWM_CHIP)
        self.pwm.stop.assert_called_once()
        output.set_angle(0)
        self.pwm.start.assert_called_once_with(8.055)
        output.set_angle(0.001)
        self.pwm.change_duty_cycle.assert_not_called()
        output.set_angle(100)
        self.assertAlmostEqual(self.pwm.change_duty_cycle.call_args.args[0], 2.5)
        self.pwm.start.assert_called_once()  # Do not restart the PWM each step.
        output.release()
        output.set_angle(100)
        self.assertEqual(self.pwm.start.call_count, 2)

    def test_four_second_open_keeps_closed_start_pulse_and_gradual_electrical_updates(self):
        elapsed = 0.0
        writes = []
        stops = []
        def wait(seconds):
            nonlocal elapsed
            elapsed += seconds
        def record(duty):
            writes.append((elapsed, duty * 200))  # 50 Hz: duty percent -> microseconds.
        self.pwm.start.side_effect = record
        self.pwm.change_duty_cycle.side_effect = record
        self.pwm.stop.side_effect = lambda: stops.append(elapsed)
        claw = self.module.ClawController(self.output, sleeper=wait)
        claw.open(4)
        self.assertEqual(writes[0], (0.0, 1611))
        self.assertAlmostEqual(writes[-1][1], 500)
        self.assertGreater(writes[-1][0], 3.5)
        pulses = [pulse for _, pulse in writes]
        self.assertTrue(all(b <= a for a, b in zip(pulses, pulses[1:])))
        self.assertAlmostEqual(stops[-1], 4.1)
        self.pwm.start.assert_called_once()
        # A new close request reverses the same calibrated pulse path.
        writes.clear()
        claw.grip(4)
        self.assertAlmostEqual(writes[0][1], 500)
        self.assertAlmostEqual(writes[-1][1], 1611)
        pulses = [pulse for _, pulse in writes]
        self.assertTrue(all(b >= a for a, b in zip(pulses, pulses[1:])))

    def test_configured_claw_pulses_define_midpoint_instead_of_generic_servo_scale(self):
        with patch.object(self.module, "CLAW_CLOSE_PULSE_US", 1500.0, create=True), \
                patch.object(self.module, "CLAW_OPEN_PULSE_US", 900.0, create=True):
            output = self.output()
            output.set_angle(50)
        self.pwm.start.assert_called_once_with(6.0)  # 1200 us.

    def test_invalid_claw_pulses_rejected_before_pwm_is_opened(self):
        for close, opened in ((None, 500), (float("nan"), 500), (450, 500),
                              (1611, 2501), (500, 500), ("1611", 500)):
            with self.subTest(close=close, opened=opened), \
                    patch.object(self.module, "CLAW_CLOSE_PULSE_US", close, create=True), \
                    patch.object(self.module, "CLAW_OPEN_PULSE_US", opened, create=True):
                with self.assertRaises(ValueError):
                    self.output()
        self.hardware.HardwarePWM.assert_not_called()

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

    def test_gpio_provider_rejected_before_any_pwm_write(self):
        self.provider.side_effect = RuntimeError("Wrong PWM provider")
        with self.assertRaisesRegex(RuntimeError, "Wrong PWM provider"):
            self.output()
        self.hardware.HardwarePWM.assert_not_called()

    def test_wrong_channel_rejected_before_any_pwm_write(self):
        with patch.object(self.module, "CLAW_PWM_CHANNEL", 1):
            with self.assertRaises(ValueError):
                self.output()
        self.hardware.HardwarePWM.assert_not_called()


if __name__ == "__main__":
    unittest.main()
