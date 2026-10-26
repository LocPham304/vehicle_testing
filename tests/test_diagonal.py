"""Forward-left at 3*pi/4 drives FR/RL only; all outputs are in memory."""

import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from unittest.mock import patch

from vehicle_testing import config, controller
from vehicle_testing.main import parse_command, run_session
from vehicle_testing.tests import test_robot


RecordingOutput = test_robot.RecordingOutput


class ForwardLeftTests(unittest.TestCase):
    def test_only_fr_rl_run_forward_for_requested_duration_and_stop(self):
        for speed in (None, 0.3):
            with self.subTest(speed=speed):
                output = RecordingOutput()
                snapshots = []
                def observe(seconds):
                    if seconds == 2:
                        snapshots.append(dict(output.values))
                motor = controller.MotorController(output, sleeper=observe)
                if speed is None:
                    motor.move_forward_left(2)
                else:
                    motor.move_forward_left(2, speed)
                self.assertEqual(len(snapshots), 1)
                pwm = config.DEFAULT_SPEED if speed is None else speed
                for name, pins in config.MOTORS.items():
                    active = name in ("FR", "RL")
                    self.assertEqual(snapshots[0][pins.pwm], int(pwm * 65535) if active else 0)
                    self.assertEqual(snapshots[0][pins.in1], 65535 if active else 0)
                    self.assertEqual(snapshots[0][pins.in2], 0)
                self.assertTrue(all(value == 0 for value in output.values.values()))

    def test_inversion_changes_active_wheel_only_and_inactive_wheels_stay_off(self):
        output = RecordingOutput()
        motors = {name: replace(pins, inverted=True) for name, pins in config.MOTORS.items()}
        snapshots = []
        def observe(seconds):
            if seconds == 2:
                snapshots.append(dict(output.values))
        controller.MotorController(output, motors=motors, sleeper=observe).move_forward_left(2)
        for name, pins in motors.items():
            active = name in ("FR", "RL")
            self.assertEqual(snapshots[0][pins.in1], 0)
            self.assertEqual(snapshots[0][pins.in2], 65535 if active else 0)
            if not active:
                channels = (pins.pwm, pins.in1, pins.in2)
                self.assertFalse(any(ch in channels and duty for ch, duty in output.writes))

    def test_previous_move_is_cleared_and_directions_precede_pwm(self):
        output = RecordingOutput()
        motor = controller.MotorController(output, sleeper=lambda _: None)
        motor.move("forward", 1)
        output.writes.clear()
        motor.move_forward_left(2)
        self.assertEqual(output.writes[:4], [(0, 0), (6, 0), (15, 0), (9, 0)])
        first_enable = next(i for i, (ch, duty) in enumerate(output.writes) if ch in (0, 15) and duty)
        self.assertEqual(output.writes[first_enable - 8:first_enable], [
            (2, 65535), (1, 0), (4, 0), (5, 0),
            (14, 65535), (13, 0), (10, 0), (11, 0),
        ])
        self.assertFalse(any(ch in (6, 4, 5, 9, 10, 11) and duty for ch, duty in output.writes))

    def test_invalid_inputs_missing_wheels_and_closed_controller_do_not_write(self):
        output = RecordingOutput()
        motor = controller.MotorController(output, sleeper=lambda _: None)
        for seconds, speed in [(v, 0.5) for v in (0, -1, float("nan"), float("inf"))] + [
            (2, v) for v in (0, -1, 5, float("nan"), float("inf"))
        ]:
            with self.subTest(seconds=seconds, speed=speed), self.assertRaises(ValueError):
                motor.move_forward_left(seconds, speed)
        for names in (("FR", "FL", "RL"), ("FR", "FL", "RL", "other")):
            motors = dict(zip(names, config.MOTORS.values()))
            with self.assertRaises(ValueError):
                controller.MotorController(output, motors=motors).move_forward_left(2)
        self.assertEqual(output.writes, [])
        motor.close()
        output.writes.clear()
        with self.assertRaises(RuntimeError):
            motor.move_forward_left(2)
        self.assertEqual(output.writes, [])

    def test_interrupt_or_partial_enable_failure_stops_every_wheel(self):
        for failure in ("interrupt", "write"):
            with self.subTest(failure=failure):
                output = RecordingOutput()
                def observe(seconds):
                    if failure == "interrupt" and seconds == 2:
                        raise KeyboardInterrupt
                if failure == "write":
                    output.failure = lambda ch, duty: ch == config.MOTORS["RL"].pwm and duty > 0
                motor = controller.MotorController(output, sleeper=observe)
                with self.assertRaises(KeyboardInterrupt if failure == "interrupt" else OSError):
                    motor.move_forward_left(2)
                self.assertTrue(all(value == 0 for value in output.values.values()))


class ForwardLeftCommandTests(unittest.TestCase):
    def test_parser_uses_seconds_and_optional_pwm_and_rejects_bad_input(self):
        self.assertEqual(parse_command(" CHEO_TREN_TRAI 2 "), ("forward_left", 2.0, config.DEFAULT_SPEED))
        self.assertEqual(parse_command("cheo_tren_trai 1.5 0.3"), ("forward_left", 1.5, 0.3))
        for text in ("cheo_tren_trai", "cheo_tren_trai abc", "cheo_tren_trai 0",
                     "cheo_tren_trai -1", "cheo_tren_trai nan", "cheo_tren_trai inf",
                     "cheo_tren_trai 1 0", "cheo_tren_trai 1 5", "cheo_tren_trai 1 nan",
                     "cheo_tren_trai 1 inf", "cheo_tren_trai 1 0.3 extra"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_command(text)

    def test_mixed_script_waits_for_chay_runs_once_and_interrupt_cancels_rest(self):
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt):
                output = RecordingOutput()
                states = []
                def observe(seconds):
                    if seconds in (1, 2, 3, 4):
                        states.append((seconds, tuple(output.values[p.pwm] for p in config.MOTORS.values())))
                    if interrupt and seconds == 2:
                        raise KeyboardInterrupt
                motor = controller.MotorController(output, sleeper=observe)
                lines = iter(["tien 1", "cheo_tren_trai 2 0.3", "ngang_phai 3", "ngung 4",
                              "chay", "chay", "thoat"])
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
                half, third = int(config.DEFAULT_SPEED * 65535), int(0.3 * 65535)
                expected = [(1, (half,) * 4), (2, (third, 0, third, 0)),
                            (3, (half,) * 4), (4, (0,) * 4)]
                self.assertEqual(states, expected[:2] if interrupt else expected)
                self.assertTrue(all(value == 0 for value in output.values.values()))

    def test_cli_runs_diagonal_and_discards_unconfirmed_commands(self):
        run_cli = test_robot.CommandLineTests().run_cli
        result = run_cli("cheo_tren_trai 0.001 0.3\ncheo_tren_trai 0.002\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INFO: CHEO TREN TRAI trong 0.001 giay, PWM 30%", result.stdout)
        self.assertIn("INFO: CHEO TREN TRAI trong 0.002 giay, PWM 50%", result.stdout)
        for ending in ("", "thoat\n", "dung\nchay\nthoat\n"):
            result = run_cli("cheo_tren_trai 2\n" + ending)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("INFO: CHEO TREN TRAI trong", result.stdout)


if __name__ == "__main__":
    unittest.main()
