"""Bounded, manually triggered lift probes without real PWM access."""

import importlib
import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch


class LiftPulseProbeTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.probe_lift_pwm")
        self.output = Mock()
        self.factory = Mock(return_value=self.output)
        self.waits = []
        self.args = ["--start-us", "1500", "--min-us", "1500", "--max-us", "1600"]

    def run_probe(self, commands, extra=(), sleeper=None):
        log = io.StringIO()
        with redirect_stdout(log), redirect_stderr(log):
            status = self.module.main(self.args + list(extra), input_fn=Mock(side_effect=commands),
                                      sleeper=sleeper or self.waits.append,
                                      pwm_factory=self.factory)
        return status, log.getvalue()

    def test_opening_menu_or_invalid_commands_never_opens_pwm(self):
        status, log = self.run_probe(["", "1510", "nang 4", "thoat"])
        self.assertEqual(status, 0)
        self.factory.assert_not_called()
        self.assertIn("chua phat", log)

    def test_one_plus_is_one_small_burst_then_stop_without_a_baseline_pulse(self):
        status, log = self.run_probe(["+", "thoat"])
        self.assertEqual(status, 0)
        self.factory.assert_called_once_with()
        self.output.start.assert_called_once()
        self.assertAlmostEqual(self.output.start.call_args.args[0], 7.55)
        self.assertEqual(self.waits, [0.04])
        self.assertTrue(self.output.stop.called)
        self.assertIn("1510", log)

    def test_outside_window_is_rejected_without_starting_a_burst(self):
        status, _ = self.run_probe(["-", "+", "+", "+", "thoat"], ["--max-us", "1520"])
        self.assertEqual(status, 0)
        self.assertEqual(self.output.start.call_count, 2)
        self.assertAlmostEqual(self.output.start.call_args.args[0], 7.6)

    def test_interrupt_during_burst_stops_pwm_and_exits(self):
        status, _ = self.run_probe(["+"], sleeper=Mock(side_effect=KeyboardInterrupt()))
        self.assertEqual(status, 130)
        self.output.stop.assert_called()

    def test_start_failure_still_stops_pwm_and_does_not_continue(self):
        self.output.start.side_effect = OSError("write failed")
        status, log = self.run_probe(["+", "+", "thoat"])
        self.assertEqual(status, 1)
        self.output.start.assert_called_once()
        self.output.stop.assert_called()
        self.assertIn("write failed", log)

    def test_dry_run_never_creates_hardware_even_when_triggered(self):
        status, log = self.run_probe(["+", "thoat"], ["--dry-run"])
        self.assertEqual(status, 0)
        self.factory.assert_not_called()
        self.assertEqual(self.waits, [])
        self.assertIn("1510", log)

    def test_invalid_or_overly_long_requests_are_rejected_before_hardware(self):
        for args in (["--on-seconds", "0.11"], ["--step-us", "100"],
                     ["--start-us", "nan"], ["--max-us", "2501"],
                     ["--max-us", "2000"], ["--min-us", "1600"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.module.main(self.args + args, pwm_factory=self.factory)
        self.factory.assert_not_called()

    def test_factory_uses_discovered_lift_provider_only(self):
        hardware = Mock()
        with patch.object(self.module, "find_gpio_pwm_chip", return_value=0) as find, \
                patch.dict("sys.modules", {"rpi_hardware_pwm": hardware}):
            self.module.create_lift_pwm()
        find.assert_called_once_with(18)
        hardware.HardwarePWM.assert_called_once_with(pwm_channel=0, hz=50, chip=0)
        hardware.HardwarePWM.return_value.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
