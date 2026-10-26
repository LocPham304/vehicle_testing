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
        self.assertEqual(parse_command(" MO_CANG 10 "), ("claw_open", 10, 2))
        self.assertEqual(parse_command("dong_cang 5.5"), ("claw_grip", 5.5, 2))
        self.assertEqual(parse_command("mo_cang 10 3"), ("claw_open", 10, 3))
        self.assertEqual(parse_command("dong_cang 10 0.5"), ("claw_grip", 10, 0.5))
        for command in ("cang_goc 81", "cang_goc nan", "mo_cang 0", "dong_cang -1",
                        "mo_cang inf", "dong_cang 10 0", "mo_cang 10 nan",
                        "mo_cang 10 -1", "mo_cang 10 inf", "mo_cang 10 abc",
                        "mo_cang 10 2 extra", "cang_goc 40 2", "cang_goc"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_command(command)

    def test_claw_opens_with_decreasing_angle_and_closes_with_increasing_angle(self):
        claw = self.claw()
        claw.set_angle(40)
        claw.open(3)
        claw.grip(2)
        self.assertEqual(self.output.angles, [40, 39, 38, 37, 38, 39])
        # Two relative moves take 2s each, plus three 0.5s settling periods.
        self.assertAlmostEqual(sum(self.waits), 5.5)

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
        ticks = 0
        def wait(seconds):
            nonlocal ticks
            if seconds != 0.5:
                ticks += 1
                if ticks == 2:
                    raise KeyboardInterrupt
        claw = self.claw(wait)
        claw.set_angle(40)
        self.output.released = False
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

    def test_queued_claw_moves_use_explicit_and_default_durations(self):
        claw = self.claw()
        lines = ["cang_goc 40", "mo_cang 10 3", "dong_cang 5", "chay", "thoat"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            run_session(MotorController(Mock(), sleeper=lambda _: None), None, claw)
        self.assertEqual(self.output.angles[-1], 35)
        self.assertAlmostEqual(sum(self.waits), 6.5)  # 3s + 2s + three settling waits.

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
        self.output.released = False
        self.output.set_angle = Mock(side_effect=OSError("write failed"))
        motor_output = Mock()
        lines = ["mo_cang 10", "tien 1", "chay"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                run_session(MotorController(motor_output, sleeper=lambda _: None), None, claw)
        self.assertTrue(self.output.released)
        self.assertFalse(any(call.args[1] > 0 for call in motor_output.set_duty.call_args_list))

    def test_claw_releases_pwm_after_settling_but_lift_keeps_holding(self):
        events = []
        output = Mock()
        output.set_angle.side_effect = lambda angle: events.append(("angle", angle))
        output.release.side_effect = lambda: events.append(("release",))
        claw = self.module.ClawController(lambda: output,
                                          sleeper=lambda seconds: events.append(("wait", seconds)))
        claw.set_angle(40)
        self.assertEqual(events, [("angle", 40), ("wait", 0.5), ("release",)])
        lift_output = Mock()
        lift = self.module.HandController(lambda: lift_output, sleeper=lambda _: None)
        lift.set_angle(40)
        lift_output.release.assert_not_called()

    def test_same_absolute_claw_angle_is_reissued_after_pwm_release(self):
        output = Mock()
        claw = self.module.ClawController(lambda: output, sleeper=lambda _: None)
        claw.set_angle(40)
        claw.set_angle(40)
        self.assertEqual([call.args for call in output.set_angle.call_args_list], [(40,), (40,)])
        self.assertEqual(output.release.call_count, 2)

    def test_hold_option_keeps_pwm_and_does_not_reissue_unchanged_angle(self):
        output = Mock()
        with patch.object(self.module, "CLAW_HOLD_POSITION", True):
            claw = self.module.ClawController(lambda: output, sleeper=lambda _: None)
        claw.set_angle(40)
        claw.set_angle(40)
        output.release.assert_not_called()
        output.set_angle.assert_called_once_with(40)

    def test_release_error_invalidates_reference_and_aborts_move(self):
        output = Mock()
        output.release.side_effect = OSError("release failed")
        claw = self.module.ClawController(lambda: output, sleeper=lambda _: None)
        with self.assertLogs(self.module.logger, level="ERROR"):
            with self.assertRaisesRegex(OSError, "release failed"):
                claw.set_angle(40)
        with self.assertRaisesRegex(ValueError, "cang_goc"):
            claw.open(10)

    def test_open_reaches_requested_angle_at_two_seconds_before_settle_and_release(self):
        elapsed = 0
        writes = []
        output = Mock()
        def wait(seconds):
            nonlocal elapsed
            elapsed += seconds
        output.set_angle.side_effect = lambda angle: writes.append((elapsed, angle))
        claw = self.module.ClawController(lambda: output, sleeper=wait)
        claw.set_angle(40)
        elapsed = 0
        writes.clear()
        claw.open(10)
        self.assertEqual([angle for _, angle in writes], [39, 38, 37, 36, 35, 34, 33, 32, 31, 30])
        self.assertAlmostEqual(writes[0][0], 0.2)
        self.assertAlmostEqual(writes[-1][0], 2)
        self.assertAlmostEqual(elapsed, 2.5)

    def test_custom_duration_handles_fractional_final_step(self):
        elapsed = 0
        writes = []
        output = Mock()
        def wait(seconds):
            nonlocal elapsed
            elapsed += seconds
        output.set_angle.side_effect = lambda angle: writes.append((elapsed, angle))
        claw = self.module.ClawController(lambda: output, sleeper=wait)
        claw.set_angle(40)
        elapsed = 0
        writes.clear()
        claw.open(2.5, seconds=3)
        for (actual_time, actual_angle), (expected_time, expected_angle) in zip(
                writes, [(1.2, 39), (2.4, 38), (3, 37.5)]):
            self.assertAlmostEqual(actual_time, expected_time)
            self.assertAlmostEqual(actual_angle, expected_angle)
        self.assertEqual(len(writes), 3)

    def test_invalid_duration_does_not_send_new_angle(self):
        claw = self.claw()
        claw.set_angle(40)
        self.output.angles.clear()
        for seconds in (0, -1, float("nan"), float("inf")):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                claw.open(10, seconds=seconds)
        self.assertEqual(self.output.angles, [])


if __name__ == "__main__":
    unittest.main()
