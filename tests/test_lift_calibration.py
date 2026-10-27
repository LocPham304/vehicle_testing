"""Reject unmeasured lift pulse endpoints before any GPIO output is opened."""

import importlib
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from vehicle_testing.main import run_session
from vehicle_testing.controller import MotorController


class LiftCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")

    def test_uncalibrated_lift_starts_without_gpio_but_refuses_both_moves(self):
        factory = Mock()
        with patch.object(self.module, "SERVO_CALIBRATED", False, create=True):
            hand = self.module.HandController(factory, sleeper=lambda _: None)
            for move in (hand.hand_up, hand.hand_down):
                with self.assertRaisesRegex(ValueError, "hieu chinh"):
                    move(4)
        factory.assert_not_called()

    def test_explicit_measured_pulses_define_the_logical_angle_mapping(self):
        with patch.multiple(self.module, SERVO_CALIBRATED=True, SERVO_DOWN_PULSE_US=1420.0,
                            SERVO_UP_PULSE_US=1080.0, create=True):
            self.assertAlmostEqual(self.module.hand_angle_to_pulse_us(-10), 1420)
            self.assertAlmostEqual(self.module.hand_angle_to_pulse_us(80), 1080)
            self.assertAlmostEqual(self.module.hand_angle_to_pulse_us(35), 1250)

    def test_bad_calibration_never_opens_gpio(self):
        for down, up in ((None, None), (1420, None), (1420, 1420),
                         (499, 1080), (1420, 2501), (float("nan"), 1080)):
            with self.subTest(down=down, up=up), patch.multiple(
                    self.module, SERVO_CALIBRATED=True, SERVO_DOWN_PULSE_US=down,
                    SERVO_UP_PULSE_US=up, create=True):
                factory = Mock()
                hand = self.module.HandController(factory, sleeper=lambda _: None)
                with self.assertRaises(ValueError):
                    hand.hand_up(4)
                factory.assert_not_called()

    def test_dry_run_can_preview_angles_without_calibrating_physical_outputs(self):
        output = Mock()
        with patch.object(self.module, "SERVO_CALIBRATED", False, create=True):
            hand = self.module.HandController(lambda: output, sleeper=lambda _: None,
                                               calibration_required=False)
            hand.hand_up(4)
        self.assertEqual(output.set_angle.call_args.args, (80,))

    def test_claw_commands_remain_available_with_uncalibrated_lift(self):
        factory = Mock()
        claw = Mock()
        with patch.object(self.module, "SERVO_CALIBRATED", False):
            hand = self.module.HandController(factory, sleeper=lambda _: None)
            with patch("builtins.input", side_effect=["mo_cang 4", "chay", "thoat"]), \
                    redirect_stdout(io.StringIO()):
                run_session(MotorController(Mock(), sleeper=lambda _: None), hand, claw)
        claw.open.assert_called_once_with(seconds=4)
        factory.assert_not_called()

    def test_mapping_does_not_extrapolate_past_calibrated_angle_endpoints(self):
        with patch.multiple(self.module, SERVO_CALIBRATED=True, SERVO_DOWN_PULSE_US=1420.0,
                            SERVO_UP_PULSE_US=1080.0, SERVO_UP_ANGLE=70):
            with self.assertRaises(ValueError):
                self.module.hand_angle_to_pulse_us(80)


if __name__ == "__main__":
    unittest.main()
