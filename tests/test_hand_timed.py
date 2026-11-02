"""Regression checks for timed lift interpolation and absolute CLI angles."""

import importlib
import unittest
from unittest.mock import Mock, patch

from vehicle_testing.cli.robot import HELP, parse_command
from vehicle_testing.tests.test_hand import mock_lift_calibration


class TimedHandTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hardware.servos")
        mock_lift_calibration(self, self.module)

    def test_commands_accept_angles_and_keep_tay_goc_removed(self):
        self.assertEqual(parse_command("nang 60"), ("hand_up", 60, 2))
        self.assertEqual(parse_command("ha 20 4"), ("hand_down", 20, 4))
        self.assertNotIn("tay_goc", HELP)
        for command in ("tay_goc 40", "nang", "ha -10", "nang nan", "ha 20 0.1"):
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
        for method, start, end, seconds in ((hand.hand_up, 0, 90, 2),
                                          (hand.hand_down, 90, 0, 3)):
            with self.subTest(end=end):
                elapsed = 0
                writes.clear()
                method(seconds)
                self.assertEqual(writes[0], (0, start))
                self.assertEqual(writes[-1][1], end)
                self.assertAlmostEqual(writes[-1][0], seconds)
                self.assertAlmostEqual(elapsed, seconds + 0.1)
                angles = [angle for _, angle in writes]
                self.assertTrue(all(0 <= angle <= 90 for angle in angles))
                changes = [b - a for a, b in zip(angles, angles[1:])]
                self.assertTrue(all(change * (end - start) >= 0 for change in changes))
                magnitudes = [abs(change) for change in changes]
                self.assertLess(max(magnitudes), 2)
                self.assertLess(magnitudes[0], max(magnitudes) / 10)
                self.assertLess(magnitudes[-1], max(magnitudes) / 10)
        output.release.assert_not_called()

    def test_default_four_second_moves_release_after_each_completed_endpoint(self):
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
        self.assertEqual(releases[0][1], 90)
        hand.hand_down(4)
        self.assertEqual(len(releases), 2)
        self.assertAlmostEqual(releases[1][0], 8.2)
        self.assertEqual(releases[1][1], 0)

    def test_synthetic_angle_mapping_stays_within_servo_pulse_range(self):
        gpio = Mock(BCM=11, OUT=0)
        with patch.dict("sys.modules", {"RPi.GPIO": gpio}):
            output = self.module.GPIOServoOutput()
        pwm = gpio.PWM.return_value
        for angle, duty in ((0, 7.5), (9, 7.0), (90, 2.5)):
            output.set_angle(angle)
            self.assertAlmostEqual(pwm.ChangeDutyCycle.call_args.args[0], duty)
        pwm.ChangeDutyCycle.reset_mock()
        with patch.object(self.module, "SERVO_DOWN_PULSE_US", None):
            with self.assertRaises(ValueError):
                output.set_angle(90)
        pwm.ChangeDutyCycle.assert_not_called()

    def test_synthetic_reversed_calibration_preserves_its_pulse_direction(self):
        lower = self.module.hand_angle_to_pulse_us(0)
        upper = self.module.hand_angle_to_pulse_us(90)
        self.assertGreater(lower, upper)


if __name__ == "__main__":
    unittest.main()
