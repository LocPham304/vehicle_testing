"""Regression checks for fixed lift endpoints and seconds-only commands."""

import importlib
import unittest
from unittest.mock import Mock, patch

from vehicle_testing.cli.robot import HELP, parse_command
from vehicle_testing.tests.test_hand import mock_lift_calibration


class TimedHandTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hardware.servos")
        mock_lift_calibration(self, self.module)

    def test_commands_only_accept_seconds_and_remove_tay_goc(self):
        self.assertEqual(parse_command("nang"), ("hand_up", 2, 0))
        self.assertEqual(parse_command("ha 4"), ("hand_down", 4, 0))
        self.assertNotIn("tay_goc", HELP)
        for command in ("tay_goc 40", "nang 0.5", "ha -10", "nang nan", "ha 2 0.5"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_command(command)

    def test_timed_endpoints_start_lowered_move_gradually_and_keep_holding(self):
        hold = patch.object(self.module, "SERVO_HOLD_POSITION", True)
        hold.start()
        self.addCleanup(hold.stop)
        elapsed = 0
        writes = []
        output = Mock()
        def wait(seconds):
            nonlocal elapsed
            elapsed += seconds
        factory = Mock(return_value=output)
        output.set_angle.side_effect = lambda angle: writes.append((elapsed, angle))
        hand = self.module.HandController(factory, sleeper=wait)
        hand.hand_down()
        factory.assert_not_called()
        for method, start, end, seconds in ((hand.hand_up, -10, 80, 2),
                                          (hand.hand_down, 80, -10, 3)):
            with self.subTest(end=end):
                elapsed = 0
                writes.clear()
                method(seconds)
                self.assertEqual(writes[0], (0, start))
                self.assertEqual(writes[-1][1], end)
                self.assertAlmostEqual(writes[-1][0], seconds)
                self.assertAlmostEqual(elapsed, seconds + 0.1)
                angles = [angle for _, angle in writes]
                self.assertTrue(all(-10 <= angle <= 80 for angle in angles))
                changes = [b - a for a, b in zip(angles, angles[1:])]
                self.assertTrue(all(change * (end - start) >= 0 for change in changes))
                magnitudes = [abs(change) for change in changes]
                self.assertLess(max(magnitudes), 2)
                self.assertLess(magnitudes[0], max(magnitudes) / 10)
                self.assertLess(magnitudes[-1], max(magnitudes) / 10)
        output.release.assert_not_called()

    @patch("vehicle_testing.hardware.servos.SERVO_HOLD_POSITION", False)
    def test_optional_release_mode_releases_after_each_completed_endpoint(self):
        elapsed = [0.0]
        releases = []
        output = Mock()
        output.release.side_effect = lambda: releases.append(
            (elapsed[0], output.set_angle.call_args.args[0]))
        hand = self.module.HandController(lambda: output,
            sleeper=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
        hand.hand_up(4)
        self.assertEqual(len(releases), 1)
        self.assertAlmostEqual(releases[0][0], 4.1)
        self.assertEqual(releases[0][1], 80)
        hand.hand_down(4)
        self.assertEqual(len(releases), 2)
        self.assertAlmostEqual(releases[1][0], 8.2)
        self.assertEqual(releases[1][1], -10)

    def test_negative_angle_mapping_stays_within_servo_pulse_range(self):
        gpio = Mock(BCM=11, OUT=0)
        with patch.dict("sys.modules", {"RPi.GPIO": gpio}):
            output = self.module.GPIOServoOutput()
        pwm = gpio.PWM.return_value
        for angle, duty in ((-10, 7.5), (0, 6.9444444444), (80, 2.5)):
            output.set_angle(angle)
            self.assertAlmostEqual(pwm.ChangeDutyCycle.call_args.args[0], duty)
        pwm.ChangeDutyCycle.reset_mock()
        with patch.object(self.module, "SERVO_DOWN_PULSE_US", None):
            with self.assertRaises(ValueError):
                output.set_angle(80)
        pwm.ChangeDutyCycle.assert_not_called()

    def test_raising_preserves_the_previous_decreasing_pulse_direction(self):
        lower = self.module.hand_angle_to_pulse_us(-10)
        upper = self.module.hand_angle_to_pulse_us(80)
        self.assertGreater(lower, upper)


if __name__ == "__main__":
    unittest.main()
