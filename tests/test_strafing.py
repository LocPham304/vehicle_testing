"""Timed sideways motion uses physical wheel directions, without hardware."""

import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from unittest.mock import patch

from vehicle_testing import config, controller
from vehicle_testing.tests import test_robot


class StrafingTests(unittest.TestCase):
    def setUp(self):
        self.output = test_robot.RecordingOutput()

    def test_strafe_directions_enable_all_wheels_for_requested_duration(self):
        # Actual PCA channels: FR=(2,1), FL=(4,5), RL=(14,13), RR=(10,11).
        for direction, expected in (
            ("left", [(2, 1, True), (4, 5, False), (14, 13, True), (10, 11, False)]),
            ("right", [(2, 1, False), (4, 5, True), (14, 13, False), (10, 11, True)]),
        ):
            with self.subTest(direction=direction):
                snapshots = []
                def observe(seconds):
                    if seconds == 2:
                        snapshots.append(dict(self.output.values))
                motor = controller.MotorController(self.output, sleeper=observe)
                motor.strafe(direction, seconds=2, speed=0.25)
                self.assertEqual(len(snapshots), 1)
                values = snapshots[0]
                self.assertEqual([values[ch] for ch in (0, 6, 15, 9)], [16383] * 4)
                for in1, in2, forward in expected:
                    self.assertEqual((values[in1], values[in2]), (65535, 0) if forward else (0, 65535))
                self.assertTrue(all(v == 0 for v in self.output.values.values()))

    def test_default_speed_is_reset_after_explicit_speed(self):
        snapshots = []
        def observe(seconds):
            if seconds == 1:
                snapshots.append(tuple(self.output.values[ch] for ch in (0, 6, 15, 9)))
        motor = controller.MotorController(self.output, sleeper=observe)
        motor.strafe("left", 1, 0.3)
        motor.strafe("right", 1)
        self.assertEqual(snapshots, [(19660,) * 4, (int(config.DEFAULT_SPEED * 65535),) * 4])

    def test_inversion_changes_only_the_selected_wheel(self):
        motors = dict(config.MOTORS)
        motors["RL"] = replace(motors["RL"], inverted=True)
        snapshots = []
        def observe(seconds):
            if seconds == 1:
                snapshots.append(dict(self.output.values))
        controller.MotorController(self.output, motors=motors, sleeper=observe).strafe("left", 1)
        self.assertEqual((snapshots[0][14], snapshots[0][13]), (0, 65535))
        self.assertEqual((snapshots[0][2], snapshots[0][1]), (65535, 0))

    def test_pwm_is_off_and_all_directions_are_set_before_enabling(self):
        controller.MotorController(self.output, sleeper=lambda _: None).strafe("right", 1)
        writes = self.output.writes
        self.assertEqual(writes[:4], [(0, 0), (6, 0), (15, 0), (9, 0)])
        first_enable = next(i for i, (ch, value) in enumerate(writes) if ch in (0, 6, 15, 9) and value)
        self.assertEqual(writes[first_enable - 8:first_enable], [
            (2, 0), (1, 65535), (4, 65535), (5, 0),
            (14, 0), (13, 65535), (10, 65535), (11, 0),
        ])

    def test_interruption_or_write_failure_stops_all_outputs(self):
        for failure in ("interrupt", "write"):
            with self.subTest(failure=failure):
                self.output = test_robot.RecordingOutput()
                def wait(seconds):
                    if failure == "interrupt" and seconds == 1:
                        raise KeyboardInterrupt
                if failure == "write":
                    self.output.failure = lambda ch, duty: ch == 6 and duty > 0
                with self.assertRaises(KeyboardInterrupt if failure == "interrupt" else OSError):
                    controller.MotorController(self.output, sleeper=wait).strafe("left", 1)
                self.assertTrue(all(v == 0 for v in self.output.values.values()))

    def test_invalid_values_and_closed_controller_do_not_write_outputs(self):
        motor = controller.MotorController(self.output, sleeper=lambda _: None)
        cases = [("forward", 1, 0.5)]
        cases += [("left", value, 0.5) for value in (0, -1, float("nan"), float("inf"))]
        cases += [("right", 1, value) for value in (0, -1, 5, float("nan"), float("inf"))]
        for direction, seconds, speed in cases:
            with self.subTest(direction=direction, seconds=seconds, speed=speed), self.assertRaises(ValueError):
                motor.strafe(direction, seconds, speed)
        self.assertEqual(self.output.writes, [])
        motor.close()
        self.output.writes.clear()
        with self.assertRaises(RuntimeError):
            motor.strafe("left", 1)
        self.assertEqual(self.output.writes, [])

    def test_requires_four_recognized_wheel_positions(self):
        for names in (("FR", "FL", "RL"), ("FR", "FL", "RL", "other")):
            motor = controller.MotorController(self.output, motors=dict(zip(names, config.MOTORS.values())))
            with self.assertRaises(ValueError):
                motor.strafe("right", 1)
        self.assertEqual(self.output.writes, [])


class StrafingCommandTests(unittest.TestCase):
    def test_parser_uses_seconds_and_optional_pwm(self):
        from vehicle_testing.main import parse_command
        self.assertEqual(parse_command(" NGANG_TRAI 2 "), ("strafe_left", 2.0, config.DEFAULT_SPEED))
        self.assertEqual(parse_command("ngang_phai 1.5 0.3"), ("strafe_right", 1.5, 0.3))
        for text in ("ngang_trai", "ngang_phai abc", "ngang_trai 0", "ngang_phai -1",
                     "ngang_trai nan", "ngang_phai inf", "ngang_trai 1 0", "ngang_phai 1 5",
                     "ngang_trai 1 nan", "ngang_phai 1 inf", "ngang_trai 1 0.3 extra"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_command(text)

    def test_mixed_script_executes_once_in_order_and_interrupt_cancels_rest(self):
        from vehicle_testing.main import run_session
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt):
                output = test_robot.RecordingOutput()
                states = []
                def observe(seconds):
                    if seconds == config.DIRECTION_CHANGE_DELAY_SECONDS:
                        return
                    states.append((seconds, tuple(output.values[ch] for ch in (2, 4, 14, 10))))
                    if interrupt and seconds == 2:
                        raise KeyboardInterrupt
                motor = controller.MotorController(output, sleeper=observe)
                lines = iter(["tien 1", "ngang_trai 2", "ngung 0.5", "ngang_phai 3 0.3",
                              "trai 15", "lui 4", "chay", "chay", "thoat"])
                def read_line(prompt):
                    line = next(lines)
                    if line not in ("chay", "thoat"):
                        self.assertEqual(output.writes, [])
                    return line
                with patch("builtins.input", side_effect=read_line), redirect_stdout(io.StringIO()):
                    if interrupt:
                        with self.assertRaises(KeyboardInterrupt):
                            run_session(motor)
                    else:
                        run_session(motor)
                expected_states = [(65535, 65535, 65535, 65535), (65535, 0, 65535, 0),
                                   (0, 0, 0, 0), (0, 65535, 0, 65535),
                                   (65535, 0, 0, 65535), (0, 0, 0, 0)]
                self.assertEqual([s[1] for s in states], expected_states[:2] if interrupt else expected_states)
                self.assertTrue(all(v == 0 for v in output.values.values()))

    def test_cli_runs_both_directions_and_discards_unconfirmed_commands(self):
        run_cli = test_robot.CommandLineTests().run_cli
        result = run_cli("ngang_trai 0.001\nngang_phai 0.002 0.3\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INFO: NGANG TRAI trong 0.001 giay, PWM 50%", result.stdout)
        self.assertIn("INFO: NGANG PHAI trong 0.002 giay, PWM 30%", result.stdout)
        for ending in ("", "thoat\n", "dung\nchay\nthoat\n"):
            result = run_cli("ngang_trai 2\nngang_phai 2\n" + ending)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("INFO: NGANG", result.stdout)


if __name__ == "__main__":
    unittest.main()
