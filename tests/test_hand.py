"""Lift command lifecycle, GPIO isolation and queue checks without hardware."""

import importlib
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from vehicle_testing.main import parse_command, run_session
from vehicle_testing.controller import MotorController


class RecordingServo:
    def __init__(self):
        self.angles = []
        self.closed = False
        self.released = False

    def set_angle(self, angle):
        self.angles.append(angle)

    def release(self):
        self.released = True

    def close(self):
        self.closed = True


class HandControllerTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")
        self.output = RecordingServo()
        self.factory = Mock(return_value=self.output)
        self.hand = self.module.HandController(self.factory, sleeper=lambda _: None)

    def test_invalid_seconds_never_open_gpio(self):
        for seconds in (0, 0.5, -1, float("nan"), float("inf")):
            for method in (self.hand.hand_up, self.hand.hand_down):
                with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                    method(seconds)
        self.factory.assert_not_called()

    def test_repeated_endpoint_does_not_move_again(self):
        self.hand.hand_up()
        angles = self.output.angles.copy()
        self.hand.hand_up(4)
        self.assertEqual(self.output.angles, angles)

    def test_interruption_releases_and_invalidates_position(self):
        hand = self.module.HandController(self.factory, sleeper=Mock(side_effect=KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            hand.hand_up()
        self.assertTrue(self.output.released)
        for method in (hand.hand_up, hand.hand_down):
            with self.assertRaisesRegex(RuntimeError, "khoi dong lai"):
                method()

    def test_write_error_releases_and_invalidates_position(self):
        self.output.set_angle = Mock(side_effect=OSError("write failed"))
        with self.assertRaises(OSError):
            self.hand.hand_up()
        self.assertTrue(self.output.released)
        with self.assertRaisesRegex(RuntimeError, "khoi dong lai"):
            self.hand.hand_down()

    def test_close_is_lazy_idempotent_and_rejects_later_commands(self):
        self.hand.close()
        self.hand.close()
        self.factory.assert_not_called()
        with self.assertRaises(RuntimeError):
            self.hand.hand_up()
        used = self.module.HandController(self.factory, sleeper=lambda _: None)
        used.hand_up()
        used.close()
        self.assertTrue(self.output.closed)


class GPIOOutputTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")
        self.gpio = Mock(BCM=11, OUT=0)
        self.pwm = self.gpio.PWM.return_value

    def open(self):
        with patch.dict(sys.modules, {"RPi": Mock(), "RPi.GPIO": self.gpio}):
            return self.module.GPIOServoOutput()

    def test_gpio_stays_on_bcm18_and_cleanup_is_pin_scoped(self):
        output = self.open()
        self.gpio.PWM.assert_called_once_with(18, 50)
        self.pwm.start.assert_called_once_with(0)
        output.set_angle(-10)
        self.assertAlmostEqual(self.pwm.ChangeDutyCycle.call_args.args[0], 7.5)
        output.set_angle(80)
        self.assertAlmostEqual(self.pwm.ChangeDutyCycle.call_args.args[0], 2.5)
        self.pwm.stop.assert_not_called()
        output.close()
        self.pwm.stop.assert_called_once()
        self.gpio.cleanup.assert_called_once_with(18)

    def test_invalid_angle_does_not_change_pwm(self):
        output = self.open()
        for angle in (-11, 81, float("nan")):
            with self.assertRaises(ValueError):
                output.set_angle(angle)
        self.pwm.ChangeDutyCycle.assert_not_called()
        output.close()

    def test_partial_initialization_cleans_up_own_pin(self):
        self.pwm.start.side_effect = OSError("start failed")
        with self.assertRaisesRegex(OSError, "start failed"):
            self.open()
        self.pwm.stop.assert_called_once()
        self.gpio.cleanup.assert_called_once_with(18)

    def test_close_still_cleans_pin_when_zero_duty_fails(self):
        output = self.open()
        self.pwm.ChangeDutyCycle.side_effect = OSError("write failed")
        with self.assertRaises(OSError):
            output.close()
        self.pwm.stop.assert_called_once()
        self.gpio.cleanup.assert_called_once_with(18)


class HandSessionTests(unittest.TestCase):
    def setUp(self):
        module = importlib.import_module("vehicle_testing.hand")
        self.motor = Mock()
        self.controller = MotorController(self.motor, sleeper=lambda _: None)
        self.output = RecordingServo()
        self.factory = Mock(return_value=self.output)
        self.hand = module.HandController(self.factory, sleeper=lambda _: None)

    def session(self, lines):
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            run_session(self.controller, self.hand)

    def test_mixed_script_stops_wheels_during_lift_moves(self):
        states = {}
        self.motor.set_duty.side_effect = lambda ch, duty: states.update({ch: duty})
        def record(angle):
            self.assertTrue(all(duty == 0 for duty in states.values()))
            self.output.angles.append(angle)
        self.output.set_angle = record
        self.session(["tien 1", "nang 2", "ha 3", "chay", "nang", "chay", "chay", "thoat"])
        self.assertEqual(self.output.angles[0], -10)
        self.assertEqual(self.output.angles[-1], 80)
        self.assertEqual(self.output.angles.count(80), 3)

    def test_cancelled_draft_and_eof_never_initialize_gpio(self):
        for lines in (["nang 4", "thoat"], ["nang 4", EOFError()],
                      ["nang 4", "dung", "chay", "thoat"]):
            self.session(lines)
        self.factory.assert_not_called()

    def test_servo_failure_aborts_later_wheel_move(self):
        self.output.set_angle = Mock(side_effect=OSError("write failed"))
        with self.assertRaises(OSError):
            self.session(["nang", "tien 1", "chay"])
        self.assertTrue(self.output.released)
        self.assertFalse(any(call.args[1] > 0 for call in self.motor.set_duty.call_args_list))

    def test_cli_dry_run_works_without_gpio_library(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "vehicle_testing/main.py"), "--dry-run"],
            input="nang 2\nha 2\nchay\nthoat\n", cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NANG", result.stdout)
        self.assertIn("HA", result.stdout)
        self.assertNotIn("tay_goc", result.stdout)

    def test_cleanup_attempts_hand_even_when_motor_cleanup_fails(self):
        module = importlib.import_module("vehicle_testing.main")
        for failure, expected in ((OSError("I2C close failed"), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(failure=failure), patch.object(module, "MotorController") as motors, \
                    patch.object(module, "HandController") as hands, \
                    patch.object(module, "run_session"), redirect_stdout(io.StringIO()):
                motors.return_value.close.side_effect = failure
                self.assertEqual(module.main(["--dry-run"]), expected)
                hands.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
