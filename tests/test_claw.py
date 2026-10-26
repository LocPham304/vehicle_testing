"""Use observed BCM 18 lift / BCM 12 claw mapping, without physical GPIO."""

import importlib
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from vehicle_testing.main import parse_command, run_session
from vehicle_testing.controller import MotorController
from vehicle_testing.tests.test_hand import RecordingServo


class ClawTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")
        self.output = RecordingServo()
        self.waits = []
        self.factory = Mock(return_value=self.output)

    def claw(self, sleeper=None):
        return self.module.ClawController(self.factory, sleeper=sleeper or self.waits.append)

    def test_parser_accepts_absolute_and_relative_claw_degrees(self):
        self.assertEqual(parse_command("cang_goc 0"), ("claw_angle", 0, 0))
        self.assertEqual(parse_command(" MO_CANG 10 "), ("claw_open", 10, 0))
        self.assertEqual(parse_command("dong_cang 5.5"), ("claw_grip", 5.5, 0))
        for command in ("cang_goc 81", "cang_goc nan", "mo_cang 0", "dong_cang -1",
                        "mo_cang inf", "dong_cang 10 0.5", "cang_goc"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_command(command)

    def test_claw_opens_with_decreasing_angle_and_closes_with_increasing_angle(self):
        claw = self.claw()
        claw.set_angle(40)
        claw.open(3)
        claw.grip(2)
        self.assertEqual(self.output.angles, [40, 39, 38, 37, 38, 39])
        self.assertEqual(len([wait for wait in self.waits if wait == 0.02]), 5)

    def test_claw_requires_own_reference_without_opening_gpio(self):
        claw = self.claw()
        with self.assertRaisesRegex(ValueError, "cang_goc"):
            claw.open(10)
        self.factory.assert_not_called()

    def test_ramp_accepts_fractional_steps_and_stays_inside_limits(self):
        claw = self.claw()
        claw.set_angle(1.5)
        claw.open(100)
        self.assertEqual(self.output.angles, [1.5, 0.5, 0])
        claw.set_angle(79)
        self.output.angles.clear()
        claw.grip(100)
        claw.grip(10)
        self.assertEqual(self.output.angles, [80])

    def test_interrupt_in_ramp_forgets_reference_and_releases_pwm(self):
        def wait(seconds):
            if seconds == 0.02:
                raise KeyboardInterrupt
        claw = self.claw(wait)
        claw.set_angle(40)
        with self.assertRaises(KeyboardInterrupt):
            claw.open(10)
        self.assertEqual(self.output.angles, [40, 39])
        self.assertTrue(self.output.released)
        with self.assertRaisesRegex(ValueError, "cang_goc"):
            claw.grip(10)

    def test_lift_and_claw_keep_independent_references_in_mixed_queue(self):
        lift_output = RecordingServo()
        lift = self.module.HandController(lambda: lift_output, sleeper=lambda _: None)
        claw = self.claw()
        motor_output = Mock()
        states = {}
        motor_output.set_duty.side_effect = lambda ch, duty: states.update({ch: duty})
        motor = MotorController(motor_output, sleeper=lambda _: None)
        original_write = self.output.set_angle
        def write(angle):
            self.assertTrue(all(value == 0 for value in states.values()))
            original_write(angle)
        self.output.set_angle = write
        lines = ["tay_goc 40", "cang_goc 40", "nang 10", "mo_cang 3",
                 "ha 5", "dong_cang 2", "chay", "chay", "thoat"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            run_session(motor, lift, claw)
        self.assertEqual(lift_output.angles, [40, 30, 35])
        self.assertEqual(self.output.angles, [40, 39, 38, 37, 38, 39])

    def test_cancelled_claw_draft_never_opens_gpio(self):
        claw = self.claw()
        lines = ["cang_goc 40", "mo_cang 10", "dung", "chay", "thoat"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            run_session(MotorController(Mock(), sleeper=lambda _: None), None, claw)
        self.factory.assert_not_called()

    def test_main_hardware_uses_confirmed_pins_and_closes_both(self):
        main = importlib.import_module("vehicle_testing.main")
        gpio = Mock(BCM=11, OUT=0)
        motor_output = Mock()
        lines = ["tay_goc 40", "cang_goc 40", "chay", "thoat"]
        with patch.dict("sys.modules", {"RPi.GPIO": gpio}), \
                patch.object(main, "PCA9685Output", return_value=motor_output), \
                patch.object(self.module.time, "sleep"), \
                patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            # Replace sleep at the constructor boundary; the default is bound at import.
            real_lift = main.HandController
            real_claw = main.ClawController
            with patch.object(main, "HandController", side_effect=lambda factory: real_lift(factory, sleeper=lambda _: None)), \
                    patch.object(main, "ClawController", side_effect=lambda factory: real_claw(factory, sleeper=lambda _: None)):
                self.assertEqual(main.main([]), 0)
        self.assertEqual([call.args for call in gpio.PWM.call_args_list], [(18, 50), (12, 50)])
        self.assertEqual([call.args for call in gpio.cleanup.call_args_list], [(18,), (12,)])

    def test_claw_cleanup_runs_when_lift_cleanup_fails_or_is_interrupted(self):
        main = importlib.import_module("vehicle_testing.main")
        for failure, expected in ((OSError("GPIO failed"), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(failure=failure), \
                    patch.object(main, "MotorController"), \
                    patch.object(main, "HandController") as lift, \
                    patch.object(main, "ClawController") as claw, \
                    patch.object(main, "run_session"), redirect_stdout(io.StringIO()):
                lift.return_value.close.side_effect = failure
                self.assertEqual(main.main(["--dry-run"]), expected)
                claw.return_value.close.assert_called_once()

    def test_closing_lift_does_not_disable_claw_pwm_or_cleanup_its_pin(self):
        gpio = Mock(BCM=11, OUT=0)
        lift_pwm, claw_pwm = Mock(), Mock()
        gpio.PWM.side_effect = [lift_pwm, claw_pwm]
        with patch.dict("sys.modules", {"RPi.GPIO": gpio}):
            lift = self.module.GPIOServoOutput()
            claw = self.module.GPIOServoOutput(pin=12)
        claw.set_angle(40)
        claw_pwm.ChangeDutyCycle.reset_mock()
        lift.close()
        claw_pwm.stop.assert_not_called()
        claw_pwm.ChangeDutyCycle.assert_not_called()
        gpio.cleanup.assert_called_once_with(18)
        claw.set_angle(30)
        self.assertAlmostEqual(claw_pwm.ChangeDutyCycle.call_args.args[0], 4.166666667)
        claw.close()

    def test_failed_claw_ramp_aborts_later_wheel_move(self):
        claw = self.claw()
        claw.set_angle(40)
        self.output.set_angle = Mock(side_effect=OSError("write failed"))
        motor_output = Mock()
        lines = ["mo_cang 10", "tien 1", "chay"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                run_session(MotorController(motor_output, sleeper=lambda _: None), None, claw)
        self.assertTrue(self.output.released)
        self.assertFalse(any(call.args[1] > 0 for call in motor_output.set_duty.call_args_list))


if __name__ == "__main__":
    unittest.main()
