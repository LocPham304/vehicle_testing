"""Wheel compensation checks use recorded outputs, never the actual robot."""

import unittest
from unittest.mock import patch

from vehicle_testing import config, controller
from vehicle_testing.tests.test_robot import RecordingOutput


class WheelGainTests(unittest.TestCase):
    def test_config_contains_user_requested_trial_gains(self):
        self.assertEqual(getattr(config, "WHEEL_GAIN", None),
                         {"FR": 0.90, "FL": 1.0, "RL": 1.0, "RR": 1.0})

    def test_log_reports_effective_pwm_including_inactive_wheels(self):
        motor = controller.MotorController(RecordingOutput(), sleeper=lambda _: None)
        with self.assertLogs(controller.logger, level="INFO") as logs:
            motor.move_forward_left(2)
        self.assertTrue(any("PWM tung banh: FR=45.0%, FL=0.0%, RL=50.0%, RR=0.0%"
                            in line for line in logs.output))

    def test_each_movement_scales_pwm_without_changing_directions_or_inactive_wheels(self):
        cases = [
            ("move", ("forward", 2, 0.5), {"FR": True, "FL": True, "RL": True, "RR": True}),
            ("move", ("backward", 2, 0.5), {"FR": False, "FL": False, "RL": False, "RR": False}),
            ("strafe", ("left", 2, 0.5), {"FR": True, "FL": False, "RL": True, "RR": False}),
            ("strafe", ("right", 2, 0.5), {"FR": False, "FL": True, "RL": False, "RR": True}),
            ("move_forward_left", (2, 0.5), {"FR": True, "RL": True}),
            ("move_forward_right", (2, 0.5), {"FL": True, "RR": True}),
            ("move_backward_left", (2, 0.5), {"FL": False, "RR": False}),
            ("move_backward_right", (2, 0.5), {"FR": False, "RL": False}),
            ("turn_left", (90,), {"FR": True, "FL": False, "RL": False, "RR": True}),
            ("turn_right", (90,), {"FR": False, "FL": True, "RL": True, "RR": False}),
        ]
        gains = {"FR": 0.90, "FL": 1.0, "RL": 1.0, "RR": 1.0}
        for method, args, directions in cases:
            with self.subTest(method=method, args=args):
                output = RecordingOutput()
                snapshots = []

                def observe(_):
                    if any(output.values.get(p.pwm, 0) for p in config.MOTORS.values()):
                        snapshots.append(dict(output.values))

                with patch.object(controller, "WHEEL_GAIN", gains, create=True):
                    motor = controller.MotorController(output, sleeper=observe)
                    getattr(motor, method)(*args)
                self.assertEqual(len(snapshots), 1)
                for name, pins in config.MOTORS.items():
                    expected_pwm = (29490 if name == "FR" else 32767) if name in directions else 0
                    self.assertEqual(snapshots[0][pins.pwm], expected_pwm)
                    self.assertEqual(snapshots[0][pins.in1], 65535 if directions.get(name) is True else 0)
                    self.assertEqual(snapshots[0][pins.in2], 65535 if directions.get(name) is False else 0)
                self.assertTrue(all(value == 0 for value in output.values.values()))

    def test_config_can_trim_other_wheels_and_restore_neutral_gains(self):
        for gains, expected in [
            ({"FR": 1.0, "FL": 1.0, "RL": 1.0, "RR": 1.0}, (32767,) * 4),
            ({"FR": 1.0, "FL": 0.8, "RL": 0.6, "RR": 0.4}, (32767, 26214, 19660, 13107)),
        ]:
            with self.subTest(gains=gains), patch.object(controller, "WHEEL_GAIN", gains, create=True):
                output = RecordingOutput()
                snapshots = []

                def observe(seconds):
                    if seconds == 2:
                        snapshots.append(tuple(output.values[p.pwm] for p in config.MOTORS.values()))

                controller.MotorController(output, sleeper=observe).move("forward", 2, 0.5)
                self.assertEqual(snapshots, [expected])

    def test_invalid_gain_configuration_is_rejected_before_any_output(self):
        neutral = dict.fromkeys(config.MOTORS, 1.0)
        cases = [{}, {**neutral, "typo": 1.0}, {k: v for k, v in neutral.items() if k != "FR"}]
        cases += [{**neutral, "FR": value} for value in
                  (0, -0.1, 1.1, float("nan"), float("inf"), "0.9", None, True)]
        for gains in cases:
            with self.subTest(gains=gains), patch.object(controller, "WHEEL_GAIN", gains, create=True):
                output = RecordingOutput()
                with self.assertRaises(ValueError):
                    controller.MotorController(output, sleeper=lambda _: None)
                self.assertEqual(output.writes, [])

    def test_full_speed_does_not_exceed_pwm_range_and_interrupt_still_stops(self):
        output = RecordingOutput()

        def interrupt(seconds):
            if seconds == 2:
                self.assertEqual(output.values[config.MOTORS["FR"].pwm], 58981)
                self.assertEqual(output.values[config.MOTORS["RL"].pwm], 65535)
                raise KeyboardInterrupt

        gains = {"FR": 0.9, "FL": 1.0, "RL": 1.0, "RR": 1.0}
        with patch.object(controller, "WHEEL_GAIN", gains, create=True):
            motor = controller.MotorController(output, sleeper=interrupt)
            with self.assertRaises(KeyboardInterrupt):
                motor.strafe("left", 2, 1.0)
        self.assertTrue(all(value == 0 for value in output.values.values()))


if __name__ == "__main__":
    unittest.main()
