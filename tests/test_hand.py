"""Exercise arm commands without opening Raspberry Pi GPIO."""

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


class HandParserTests(unittest.TestCase):
    def test_accepts_relative_degrees_and_absolute_zero(self):
        self.assertEqual(parse_command(" NANG 10.5 "), ("hand_up", 10.5, 0))
        self.assertEqual(parse_command("ha 20"), ("hand_down", 20, 0))
        self.assertEqual(parse_command("tay_goc 0"), ("hand_angle", 0, 0))
        self.assertEqual(parse_command("tay_goc 80"), ("hand_angle", 80, 0))

    def test_rejects_invalid_angles_and_extra_pwm(self):
        for command in ("nang", "ha 1 0.5", "nang 0", "ha -1", "nang nan",
                        "ha inf", "tay_goc -1", "tay_goc 81", "tay_goc nan",
                        "tay_goc inf", "tay_goc abc", "tay_goc 10 0.5"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_command(command)


class HandControllerTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")
        self.output = RecordingServo()
        self.factory = Mock(return_value=self.output)
        self.hand = self.module.HandController(self.factory, sleeper=lambda _: None)

    def test_startup_and_close_without_commands_never_open_gpio(self):
        self.hand.close()
        self.factory.assert_not_called()

    def test_relative_commands_require_reference_before_opening_gpio(self):
        for method in (self.hand.hand_up, self.hand.hand_down):
            with self.assertRaisesRegex(ValueError, "tay_goc"):
                method(10)
        self.factory.assert_not_called()

    def test_relative_signs_limits_and_no_drift_at_limit(self):
        self.hand.set_angle(40)
        self.hand.hand_up(10)
        self.hand.hand_down(20)
        self.hand.hand_up(999)
        self.hand.hand_up(10)
        self.hand.hand_down(999)
        self.hand.hand_down(10)
        self.hand.hand_up(10)
        self.assertEqual(self.output.angles, [40, 30, 50, 0, 80, 70])

    def test_invalid_requests_never_open_gpio(self):
        for angle in (-1, 81, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.hand.set_angle(angle)
        for amount in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.hand.hand_up(amount)
            with self.assertRaises(ValueError):
                self.hand.hand_down(amount)
        self.factory.assert_not_called()

    def test_interrupted_move_releases_pwm_and_forgets_reference(self):
        self.hand.set_angle(40)
        def interrupt(_):
            raise KeyboardInterrupt
        hand = self.module.HandController(self.factory, sleeper=interrupt)
        with self.assertRaises(KeyboardInterrupt):
            hand.set_angle(50)
        self.assertTrue(self.output.released)
        with self.assertRaisesRegex(ValueError, "tay_goc"):
            hand.hand_up(10)

    def test_write_error_does_not_keep_previous_reference(self):
        self.hand.set_angle(40)
        self.output.set_angle = Mock(side_effect=OSError("GPIO failed"))
        with self.assertRaises(OSError):
            self.hand.hand_down(10)
        self.assertTrue(self.output.released)
        with self.assertRaisesRegex(ValueError, "tay_goc"):
            self.hand.hand_down(10)

    def test_close_releases_output_and_rejects_later_commands(self):
        self.hand.set_angle(40)
        self.hand.close()
        self.hand.close()
        self.assertTrue(self.output.closed)
        with self.assertRaises(RuntimeError):
            self.hand.set_angle(20)
        self.assertEqual(self.output.angles, [40])


class GPIOOutputTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")
        self.gpio = Mock(BCM=11, OUT=0)
        self.pwm = self.gpio.PWM.return_value

    def open(self):
        with patch.dict(sys.modules, {"RPi": Mock(), "RPi.GPIO": self.gpio}):
            return self.module.GPIOServoOutput()

    def test_pin_frequency_and_duty_keep_180_degree_electrical_scale(self):
        output = self.open()
        self.gpio.setmode.assert_called_once_with(11)
        self.gpio.setup.assert_called_once_with(18, 0)
        self.gpio.PWM.assert_called_once_with(18, 50)
        self.pwm.start.assert_called_once_with(0)
        output.set_angle(0)
        self.assertAlmostEqual(self.pwm.ChangeDutyCycle.call_args.args[0], 2.5)
        output.set_angle(80)
        self.assertAlmostEqual(self.pwm.ChangeDutyCycle.call_args.args[0], 6.944444444)
        self.pwm.stop.assert_not_called()  # Keep holding after a completed move.
        output.close()
        self.assertEqual(self.pwm.ChangeDutyCycle.call_args.args, (0,))
        self.pwm.stop.assert_called_once()
        self.gpio.cleanup.assert_called_once_with(18)

    def test_invalid_angle_does_not_change_pwm(self):
        output = self.open()
        for angle in (-1, 81, float("nan")):
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
        hand_module = importlib.import_module("vehicle_testing.hand")
        self.motor_output = Mock()
        self.controller = MotorController(self.motor_output, sleeper=lambda _: None)
        self.output = RecordingServo()
        self.factory = Mock(return_value=self.output)
        self.hand = hand_module.HandController(self.factory, sleeper=lambda _: None)

    def session(self, lines):
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            run_session(self.controller, self.hand)

    def test_mixed_script_runs_in_order_with_wheels_off_during_servo_moves(self):
        states = {}
        self.motor_output.set_duty.side_effect = lambda ch, duty: states.update({ch: duty})
        def record(angle):
            self.assertTrue(all(duty == 0 for duty in states.values()))
            self.output.angles.append(angle)
        self.output.set_angle = record
        self.session(["tien 1", "tay_goc 40", "nang 10", "ha 20", "chay",
                      "nang 5", "chay", "chay", "thoat"])
        self.assertEqual(self.output.angles, [40, 30, 50, 45])

    def test_draft_cancel_and_eof_never_initialize_gpio(self):
        for lines in (["tay_goc 40", "thoat"], ["tay_goc 40", EOFError()],
                      ["tay_goc 40", "dung", "chay", "thoat"]):
            self.session(lines)
        self.factory.assert_not_called()

    def test_missing_reference_aborts_before_later_wheel_command(self):
        with self.assertRaisesRegex(ValueError, "tay_goc"):
            self.session(["nang 10", "tien 1", "chay"])
        self.factory.assert_not_called()
        self.assertFalse(any(call.args[1] > 0 for call in self.motor_output.set_duty.call_args_list))

    def test_main_closes_servo_even_when_motor_cleanup_fails(self):
        module = importlib.import_module("vehicle_testing.main")
        with patch.object(module, "MotorController") as motors, \
                patch.object(module, "HandController") as hands, \
                patch.object(module, "run_session"), redirect_stdout(io.StringIO()):
            motors.return_value.close.side_effect = OSError("I2C close failed")
            self.assertEqual(module.main(["--dry-run"]), 1)
            hands.return_value.close.assert_called_once()

    def test_cli_dry_run_works_without_gpio_library(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "vehicle_testing/main.py"), "--dry-run"],
            input="tay_goc 40\nnang 10\nha 10\nchay\nthoat\n", cwd=root,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SERVO goc yeu cau 30", result.stdout)
        self.assertIn("SERVO goc yeu cau 40", result.stdout)

    def test_interrupt_during_motor_cleanup_still_closes_servo(self):
        module = importlib.import_module("vehicle_testing.main")
        with patch.object(module, "MotorController") as motors, \
                patch.object(module, "HandController") as hands, \
                patch.object(module, "run_session"), redirect_stdout(io.StringIO()):
            motors.return_value.close.side_effect = KeyboardInterrupt
            try:
                result = module.main(["--dry-run"])
            except KeyboardInterrupt:
                self.fail("Motor cleanup interruption bypassed servo cleanup")
            self.assertEqual(result, 130)
            hands.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
