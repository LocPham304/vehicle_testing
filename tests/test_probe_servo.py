"""Check the standalone pin probe without physical GPIO or motor hardware."""

import importlib
import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch


class ServoProbeTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.probe_servo")
        self.gpio = Mock(BCM=11, OUT=0)
        self.pwm = self.gpio.PWM.return_value

    def run_probe(self, *args, sleeper=lambda _: None):
        with patch.dict(sys.modules, {"RPi.GPIO": self.gpio}), \
                redirect_stdout(io.StringIO()) as output:
            result = self.module.main(list(args), sleeper=sleeper)
        return result, output.getvalue()

    def test_probe_uses_only_selected_pin_and_small_motion_range(self):
        waits = []
        result, output = self.run_probe("--pin", "18", sleeper=waits.append)
        self.assertEqual(result, 0)
        self.gpio.setup.assert_called_once_with(18, 0)
        self.gpio.PWM.assert_called_once_with(18, 50)
        self.pwm.start.assert_called_once_with(0)
        duties = [call.args[0] for call in self.pwm.ChangeDutyCycle.call_args_list]
        for actual, expected in zip(duties, [4.722222222, 4.166666667, 4.722222222, 0]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(len(duties), 4)
        self.assertEqual(waits, [2, 2, 2])
        self.assertIn("BCM 18", output)
        self.pwm.stop.assert_called_once()
        self.gpio.cleanup.assert_called_once_with(18)

    def test_dry_run_never_imports_gpio(self):
        with patch.object(self.module.importlib, "import_module", side_effect=AssertionError("GPIO opened")):
            result, output = self.run_probe("--pin", "19", "--dry-run")
        self.assertEqual(result, 0)
        self.assertIn("40", output)
        self.gpio.setup.assert_not_called()

    def test_requires_explicit_candidate_pin(self):
        for args in ([], ["--pin", "4"], ["--pin", "0"]):
            with self.subTest(args=args), patch("sys.stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.run_probe(*args)
                self.assertEqual(error.exception.code, 2)
        self.gpio.setup.assert_not_called()

    def test_interrupt_stops_pwm_and_cleans_selected_pin(self):
        def interrupt(_):
            raise KeyboardInterrupt
        result, _ = self.run_probe("--pin", "12", sleeper=interrupt)
        self.assertEqual(result, 130)
        self.assertEqual(self.pwm.ChangeDutyCycle.call_args.args, (0,))
        self.pwm.stop.assert_called_once()
        self.gpio.cleanup.assert_called_once_with(12)

    def test_start_failure_still_stops_pwm_and_cleans_selected_pin(self):
        self.pwm.start.side_effect = OSError("start failed")
        result, output = self.run_probe("--pin", "13")
        self.assertEqual(result, 1)
        self.assertIn("start failed", output)
        self.pwm.stop.assert_called_once()
        self.gpio.cleanup.assert_called_once_with(13)


if __name__ == "__main__":
    unittest.main()
