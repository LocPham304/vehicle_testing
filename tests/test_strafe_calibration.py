"""Per-wheel PWM trim is isolated to strafing, using in-memory output."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from vehicle_testing import config, controller
from vehicle_testing.tests.test_robot import RecordingOutput


class StrafeCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.output = RecordingOutput()

    def test_each_direction_uses_its_own_per_wheel_gains(self):
        snapshots = []
        def observe(seconds):
            if seconds == 1:
                snapshots.append(dict(self.output.values))
        motor = controller.MotorController(self.output, sleeper=observe)
        left = {"FR": 0.8, "FL": 1.0, "RL": 0.9, "RR": 0.7}
        right = {"FR": 1.0, "FL": 0.6, "RL": 0.75, "RR": 0.9}
        with patch.object(controller, "STRAFE_LEFT_GAINS", left), patch.object(
            controller, "STRAFE_RIGHT_GAINS", right
        ):
            motor.strafe("left", 1, 0.5)
            motor.strafe("right", 1, 0.5)
        for values, gains, forward in zip(snapshots, (left, right), (
            {"FR": True, "FL": False, "RL": True, "RR": False},
            {"FR": False, "FL": True, "RL": False, "RR": True},
        )):
            for name, pins in config.MOTORS.items():
                self.assertEqual(values[pins.pwm], int(0.5 * gains[name] * 65535))
                self.assertEqual(values[pins.in1], 65535 if forward[name] else 0)
                self.assertEqual(values[pins.in2], 0 if forward[name] else 65535)
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(all(v == 0 for v in self.output.values.values()))

    def test_bad_gain_maps_are_rejected_before_any_output(self):
        valid = {name: 1.0 for name in config.MOTORS}
        cases = [None, {}, {"FR": 1.0}, dict(valid, other=1.0)]
        cases += [dict(valid, FR=value) for value in (
            0, -0.1, 1.01, float("nan"), float("inf"), "0.9", True,
        )]
        motor = controller.MotorController(self.output, sleeper=lambda _: None)
        for direction, constant in (("left", "STRAFE_LEFT_GAINS"), ("right", "STRAFE_RIGHT_GAINS")):
            for gains in cases:
                with self.subTest(direction=direction, gains=gains), patch.object(controller, constant, gains):
                    with self.assertRaises(ValueError):
                        motor.strafe(direction, 1, 0.5)
        self.assertEqual(self.output.writes, [])

    def test_trim_does_not_change_forward_backward_or_turn_pwm(self):
        snapshots = []
        def observe(seconds):
            if any(self.output.values.get(p.pwm, 0) for p in config.MOTORS.values()):
                snapshots.append(tuple(self.output.values[p.pwm] for p in config.MOTORS.values()))
        motor = controller.MotorController(self.output, sleeper=observe)
        with patch.object(controller, "STRAFE_LEFT_GAINS", {"FR": 0.1}), patch.object(
            controller, "STRAFE_RIGHT_GAINS", None
        ):
            motor.move("forward", 1, 0.4)
            motor.move("backward", 1, 0.6)
            motor.turn_left(15)
            motor.turn_right(15)
        self.assertEqual(snapshots, [
            (int(0.4 * 65535),) * 4, (int(0.6 * 65535),) * 4,
            (int(config.TURN_SPEED * 65535),) * 4, (int(config.TURN_SPEED * 65535),) * 4,
        ])

    def test_calibration_keeps_inversion_and_direction_before_pwm(self):
        motors = dict(config.MOTORS)
        motors["FR"] = replace(motors["FR"], inverted=True)
        snapshots = []
        def observe(seconds):
            if seconds == 1:
                snapshots.append(dict(self.output.values))
        with patch.object(controller, "STRAFE_LEFT_GAINS", {"FR": 0.8, "FL": 1, "RL": 1, "RR": 1}):
            controller.MotorController(self.output, motors=motors, sleeper=observe).strafe("left", 1, 0.5)
        self.assertEqual((snapshots[0][2], snapshots[0][1]), (0, 65535))
        self.assertEqual(snapshots[0][0], int(0.4 * 65535))
        first_enable = next(i for i, (ch, duty) in enumerate(self.output.writes) if ch in (0, 6, 15, 9) and duty)
        self.assertEqual(self.output.writes[:4], [(0, 0), (6, 0), (15, 0), (9, 0)])
        self.assertEqual(len(self.output.writes[first_enable - 8:first_enable]), 8)
        self.assertTrue(all(ch not in (0, 6, 15, 9) for ch, duty in self.output.writes[first_enable - 8:first_enable]))

    def test_interruption_and_partial_enable_failure_still_stop(self):
        gains = {"FR": 0.8, "FL": 0.9, "RL": 1, "RR": 1}
        for failure in ("interrupt", "write"):
            with self.subTest(failure=failure):
                self.output = RecordingOutput()
                def wait(seconds):
                    if failure == "interrupt" and seconds == 1:
                        raise KeyboardInterrupt
                if failure == "write":
                    self.output.failure = lambda ch, value: ch == 6 and value > 0
                with patch.object(controller, "STRAFE_LEFT_GAINS", gains):
                    with self.assertRaises(KeyboardInterrupt if failure == "interrupt" else OSError):
                        controller.MotorController(self.output, sleeper=wait).strafe("left", 1, 0.5)
                self.assertTrue(all(value == 0 for value in self.output.values.values()))

    def test_log_reports_effective_pwm_for_each_wheel(self):
        with patch.object(controller, "STRAFE_LEFT_GAINS", {"FR": 0.8, "FL": 1, "RL": 0.9, "RR": 1}):
            with self.assertLogs("vehicle_testing.controller", level="INFO") as logs:
                controller.MotorController(self.output, sleeper=lambda _: None).strafe("left", 1, 0.5)
        self.assertTrue(any("FR=40.0%" in line and "FL=50.0%" in line and
                            "RL=45.0%" in line and "RR=50.0%" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
