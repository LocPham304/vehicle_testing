"""Direct 0/90 degree claw commands, without physical GPIO."""

import importlib
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from vehicle_testing.main import HELP, parse_command, run_session
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

    def session(self, lines, claw, lift=None, motor_output=None):
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            run_session(MotorController(motor_output or Mock(), sleeper=lambda _: None), lift, claw)

    def test_commands_accept_only_optional_seconds(self):
        self.assertEqual(parse_command(" MO_CANG "), ("claw_open", 2, 0))
        self.assertEqual(parse_command("dong_cang"), ("claw_grip", 2, 0))
        self.assertEqual(parse_command("mo_cang 0.5"), ("claw_open", 0.5, 0))
        self.assertEqual(parse_command("dong_cang 3"), ("claw_grip", 3, 0))
        self.assertNotIn("cang_goc", HELP)
        for command in ("cang_goc", "cang_goc 40", "mo_cang 10 2", "dong_cang 10 2",
                        "mo_cang 0", "dong_cang -1", "mo_cang nan", "dong_cang inf", "mo_cang abc"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_command(command)

    def test_either_direction_works_first_without_reference(self):
        for first, angle in (("open", 0), ("grip", 90)):
            with self.subTest(first=first):
                output = Mock()
                waits = []
                claw = self.module.ClawController(lambda: output, sleeper=waits.append)
                getattr(claw, first)()
                output.set_angle.assert_called_once_with(angle)
                self.assertEqual(waits, [2])
                output.release.assert_called_once()

    def test_endpoints_and_release_after_requested_time(self):
        events = []
        output = Mock()
        output.set_angle.side_effect = lambda angle: events.append(("angle", angle))
        output.release.side_effect = lambda: events.append(("release",))
        claw = self.module.ClawController(lambda: output,
                                          sleeper=lambda seconds: events.append(("wait", seconds)))
        claw.open()
        claw.grip(0.75)
        self.assertEqual(events, [("angle", 0), ("wait", 2), ("release",),
                                  ("angle", 90), ("wait", 0.75), ("release",)])

    def test_repeated_open_sends_again_after_release(self):
        claw = self.claw()
        claw.open()
        claw.open()
        self.assertEqual(self.output.angles, [0, 0])

    def test_invalid_duration_never_opens_gpio(self):
        claw = self.claw()
        for seconds in (0, -1, float("nan"), float("inf")):
            for method in (claw.open, claw.grip):
                with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                    method(seconds)
        self.factory.assert_not_called()

    def test_interruption_releases_and_next_move_needs_no_reference(self):
        claw = self.claw(Mock(side_effect=[KeyboardInterrupt(), None]))
        with self.assertRaises(KeyboardInterrupt):
            claw.open()
        self.assertTrue(self.output.released)
        claw.grip()
        self.assertEqual(self.output.angles, [0, 90])

    def test_close_is_lazy_idempotent_and_rejects_later_moves(self):
        claw = self.claw()
        claw.close()
        claw.close()
        self.factory.assert_not_called()
        with self.assertRaises(RuntimeError):
            claw.open()
        self.factory.assert_not_called()
        used = self.claw()
        used.grip()
        used.close()
        self.assertTrue(self.output.closed)

    def test_mixed_queue_preserves_lift_reference_and_stops_wheels_for_claw(self):
        lift_output = RecordingServo()
        lift = self.module.HandController(lambda: lift_output, sleeper=lambda _: None)
        states = {}
        motor = Mock()
        motor.set_duty.side_effect = lambda ch, duty: states.update({ch: duty})
        original_write = self.output.set_angle
        def write(angle):
            self.assertTrue(all(value == 0 for value in states.values()))
            original_write(angle)
        self.output.set_angle = write
        self.session(["tay_goc 40", "nang 10", "mo_cang 0.5", "ha 5", "dong_cang",
                      "chay", "chay", "thoat"], self.claw(), lift, motor)
        self.assertEqual(lift_output.angles, [40, 30, 35])
        self.assertEqual(self.output.angles, [0, 90])
        self.assertEqual(self.waits, [0.5, 2])

    def test_cancelled_draft_never_opens_gpio(self):
        self.session(["mo_cang", "dong_cang 1", "dung", "chay", "thoat"], self.claw())
        self.factory.assert_not_called()

    def test_failed_claw_move_aborts_later_wheel_move(self):
        self.output.set_angle = Mock(side_effect=OSError("write failed"))
        motor = Mock()
        with self.assertRaises(OSError):
            self.session(["mo_cang", "tien 1", "chay"], self.claw(), motor_output=motor)
        self.assertTrue(self.output.released)
        self.assertFalse(any(call.args[1] > 0 for call in motor.set_duty.call_args_list))

    def test_claw_allows_90_but_lift_rejects_it_and_cleanup_is_isolated(self):
        gpio = Mock(BCM=11, OUT=0)
        lift_pwm, claw_pwm = Mock(), Mock()
        gpio.PWM.side_effect = [lift_pwm, claw_pwm]
        with patch.dict("sys.modules", {"RPi.GPIO": gpio}):
            lift = self.module.GPIOServoOutput()
            claw = self.module.GPIOServoOutput(pin=12)
        claw.set_angle(90)
        self.assertAlmostEqual(claw_pwm.ChangeDutyCycle.call_args.args[0], 7.5)
        for angle in (-1, 91, float("nan"), float("inf")):
            with self.subTest(angle=angle), self.assertRaises(ValueError):
                claw.set_angle(angle)
        with self.assertRaises(ValueError):
            lift.set_angle(90)
        claw_pwm.ChangeDutyCycle.reset_mock()
        lift.close()
        claw_pwm.stop.assert_not_called()
        claw_pwm.ChangeDutyCycle.assert_not_called()
        gpio.cleanup.assert_called_once_with(18)
        claw.close()

    def test_optional_hold_keeps_claw_pwm_and_lift_always_holds(self):
        output = Mock()
        with patch.object(self.module, "CLAW_HOLD_POSITION", True):
            claw = self.module.ClawController(lambda: output, sleeper=lambda _: None)
        claw.grip()
        output.release.assert_not_called()
        lift = self.module.HandController(lambda: output, sleeper=lambda _: None)
        lift.set_angle(40)
        output.release.assert_not_called()

    def test_release_error_is_reported(self):
        output = Mock()
        output.release.side_effect = OSError("release failed")
        claw = self.module.ClawController(lambda: output, sleeper=lambda _: None)
        with self.assertRaisesRegex(OSError, "release failed"):
            claw.open()

    def test_main_uses_confirmed_pins_and_closes_both(self):
        main = importlib.import_module("vehicle_testing.main")
        gpio = Mock(BCM=11, OUT=0)
        real_lift, real_claw = main.HandController, main.ClawController
        with patch.dict("sys.modules", {"RPi.GPIO": gpio}), \
                patch.object(main, "PCA9685Output"), \
                patch.object(main, "HandController", side_effect=lambda factory: real_lift(factory, sleeper=lambda _: None)), \
                patch.object(main, "ClawController", side_effect=lambda factory: real_claw(factory, sleeper=lambda _: None)), \
                patch("builtins.input", side_effect=["tay_goc 40", "dong_cang", "chay", "thoat"]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main.main([]), 0)
        self.assertEqual([call.args for call in gpio.PWM.call_args_list], [(18, 50), (12, 50)])
        self.assertEqual([call.args for call in gpio.cleanup.call_args_list], [(18,), (12,)])

    def test_cleanup_attempts_claw_when_lift_cleanup_fails(self):
        main = importlib.import_module("vehicle_testing.main")
        for failure, expected in ((OSError("GPIO failed"), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(failure=failure), patch.object(main, "MotorController"), \
                    patch.object(main, "HandController") as lift, \
                    patch.object(main, "ClawController") as claw, \
                    patch.object(main, "run_session"), redirect_stdout(io.StringIO()):
                lift.return_value.close.side_effect = failure
                self.assertEqual(main.main(["--dry-run"]), expected)
                claw.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
