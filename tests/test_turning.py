"""Mecanum turning tests run without opening the physical I2C bus."""

import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from unittest.mock import patch

from vehicle_testing import config, controller
from vehicle_testing.tests import test_robot

RecordingOutput = test_robot.RecordingOutput


class TurningTests(unittest.TestCase):
    def setUp(self):
        self.output = RecordingOutput()

    def test_left_and_right_use_opposite_sides_and_stop_all_wheels(self):
        for direction, expected in (
            ("left", {"FR": True, "FL": False, "RL": False, "RR": True}),
            ("right", {"FR": False, "FL": True, "RL": True, "RR": False}),
        ):
            with self.subTest(direction=direction):
                snapshots = []
                def observe(seconds):
                    if any(self.output.values.get(p.pwm, 0) for p in config.MOTORS.values()):
                        snapshots.append((seconds, dict(self.output.values)))
                motor = controller.MotorController(self.output, sleeper=observe)
                getattr(motor, "turn_" + direction)(90)
                self.assertEqual(len(snapshots), 1)
                seconds, values = snapshots[0]
                factor = config.TURN_LEFT_SECONDS_PER_DEGREE if direction == "left" else config.TURN_RIGHT_SECONDS_PER_DEGREE
                self.assertAlmostEqual(seconds, 90 * factor)
                for name, pins in config.MOTORS.items():
                    self.assertEqual(values[pins.pwm], int(config.TURN_SPEED * 65535))
                    self.assertEqual(values[pins.in1], 65535 if expected[name] else 0)
                    self.assertEqual(values[pins.in2], 0 if expected[name] else 65535)
                self.assertTrue(all(v == 0 for v in self.output.values.values()))

    def test_left_and_right_calibration_are_independent(self):
        waits = []
        motor = controller.MotorController(self.output, sleeper=waits.append)
        with patch.object(controller, "TURN_LEFT_SECONDS_PER_DEGREE", 0.02), patch.object(
            controller, "TURN_RIGHT_SECONDS_PER_DEGREE", 0.03
        ):
            motor.turn_left(15.5)
            motor.turn_right(15.5)
        self.assertEqual(len(waits), 6)
        delay = config.DIRECTION_CHANGE_DELAY_SECONDS
        for actual, expected in zip(waits, [delay, delay, 0.31, delay, delay, 0.465]):
            self.assertAlmostEqual(actual, expected)

    def test_turn_respects_individual_motor_inversion(self):
        motors = dict(config.MOTORS)
        motors["FR"] = replace(motors["FR"], inverted=True)
        snapshots = []
        def observe(seconds):
            if self.output.values.get(0, 0):
                snapshots.append(dict(self.output.values))
        controller.MotorController(self.output, motors=motors, sleeper=observe).turn_left(20)
        self.assertEqual((snapshots[0][2], snapshots[0][1]), (0, 65535))
        self.assertEqual((snapshots[0][10], snapshots[0][11]), (65535, 0))

    def test_turn_sets_all_directions_before_enabling_pwm(self):
        controller.MotorController(self.output, sleeper=lambda _: None).turn_right(15)
        writes = self.output.writes
        self.assertEqual(writes[:4], [(0, 0), (6, 0), (15, 0), (9, 0)])
        first_enable = next(i for i, (ch, duty) in enumerate(writes) if ch in (0, 6, 15, 9) and duty)
        self.assertEqual(writes[first_enable - 8:first_enable], [
            (2, 0), (1, 65535), (4, 65535), (5, 0),
            (14, 65535), (13, 0), (10, 0), (11, 65535),
        ])

    def test_interrupt_or_partial_start_failure_requests_stop(self):
        for failure in ("interrupt", "write"):
            with self.subTest(failure=failure):
                self.output = RecordingOutput()
                def wait(seconds):
                    if failure == "interrupt" and self.output.values.get(0, 0):
                        raise KeyboardInterrupt
                if failure == "write":
                    self.output.failure = lambda ch, duty: ch == 6 and duty > 0
                with self.assertRaises(KeyboardInterrupt if failure == "interrupt" else OSError):
                    controller.MotorController(self.output, sleeper=wait).turn_left(90)
                self.assertTrue(all(v == 0 for v in self.output.values.values()))

    def test_invalid_turn_or_closed_controller_never_writes_outputs(self):
        motor = controller.MotorController(self.output, sleeper=lambda _: None)
        for direction, angle in (("sideways", 10), ("left", 0), ("right", -1),
                                 ("left", float("nan")), ("right", float("inf"))):
            with self.subTest(direction=direction, angle=angle):
                with self.assertRaises(ValueError):
                    motor.turn(direction, angle)
        self.assertEqual(self.output.writes, [])
        motor.close()
        self.output.writes.clear()
        with self.assertRaises(RuntimeError):
            motor.turn_left(15)
        self.assertEqual(self.output.writes, [])

    def test_invalid_calibration_or_speed_is_rejected_before_outputs(self):
        motor = controller.MotorController(self.output, sleeper=lambda _: None)
        for constant in ("TURN_SPEED", "TURN_LEFT_SECONDS_PER_DEGREE", "TURN_RIGHT_SECONDS_PER_DEGREE"):
            for value in (0, -1, float("nan"), float("inf")):
                with self.subTest(constant=constant, value=value), patch.object(controller, constant, value):
                    with self.assertRaises(ValueError):
                        motor.turn_right(15) if "RIGHT" in constant else motor.turn_left(15)
        with patch.object(controller, "TURN_SPEED", 5):
            with self.assertRaises(ValueError):
                motor.turn_left(15)
        self.assertEqual(self.output.writes, [])

    def test_turn_rejects_incomplete_or_unknown_wheel_names(self):
        for names in (("FR", "FL", "RL"), ("FR", "FL", "RL", "other")):
            motors = dict(zip(names, config.MOTORS.values()))
            motor = controller.MotorController(self.output, motors=motors, sleeper=lambda _: None)
            with self.assertRaises(ValueError):
                motor.turn_left(15)
        self.assertEqual(self.output.writes, [])


class TurningCommandTests(unittest.TestCase):
    def test_parser_accepts_degrees_but_no_per_command_turn_pwm(self):
        from vehicle_testing.main import parse_command
        self.assertEqual(parse_command(" TRAI 15.5 "), ("left", 15.5, config.TURN_SPEED))
        self.assertEqual(parse_command("phai 90"), ("right", 90.0, config.TURN_SPEED))
        for text in ("trai", "phai abc", "trai 0", "phai -1", "trai nan", "phai inf", "trai 90 0.5"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_command(text)

    def test_mixed_script_queues_turns_and_runs_in_order_once(self):
        from vehicle_testing.main import run_session
        states = []
        output = RecordingOutput()
        def observe(seconds):
            if seconds != config.DIRECTION_CHANGE_DELAY_SECONDS:
                states.append((seconds, tuple(output.values[p.in1] for p in config.MOTORS.values())))
        motor = controller.MotorController(output, sleeper=observe)
        lines = ["tien 1", "trai 90", "ngung 0.7", "phai 15", "lui 2", "chay", "chay", "thoat"]
        def read_line(prompt):
            line = lines.pop(0)
            if line not in ("chay", "thoat"):
                self.assertEqual(output.writes, [])
            return line
        with patch("builtins.input", side_effect=read_line), redirect_stdout(io.StringIO()):
            run_session(motor)
        self.assertEqual(len(states), 5)
        self.assertEqual([s[1] for s in states], [
            (65535, 65535, 65535, 65535), (65535, 0, 0, 65535),
            (0, 0, 0, 0), (0, 65535, 65535, 0), (0, 0, 0, 0),
        ])
        expected_times = [1, 90 * config.TURN_LEFT_SECONDS_PER_DEGREE,
                          0.7, 15 * config.TURN_RIGHT_SECONDS_PER_DEGREE, 2]
        for actual, expected in zip([s[0] for s in states], expected_times):
            self.assertAlmostEqual(actual, expected)
        self.assertTrue(all(v == 0 for v in output.values.values()))

    def test_cli_turns_and_discards_unconfirmed_turns(self):
        run_cli = test_robot.CommandLineTests().run_cli
        result = run_cli("trai 1\nphai 1\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("QUAY TRAI", result.stdout)
        self.assertIn("QUAY PHAI", result.stdout)
        result = run_cli("trai 90\ndung\nchay\nphai 90\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("INFO: QUAY", result.stdout)


if __name__ == "__main__":
    unittest.main()
