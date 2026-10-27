"""Timed gradual claw requests, without physical GPIO."""

import importlib
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from vehicle_testing.main import HELP, parse_command, run_session
from vehicle_testing.controller import MotorController
from vehicle_testing.tests.test_hand import RecordingServo, mock_lift_calibration


class ClawTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hand")
        mock_lift_calibration(self, self.module)
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
        self.assertEqual(parse_command("mo_cang 2.5"), ("claw_open", 2.5, 0))
        self.assertEqual(parse_command("dong_cang 3"), ("claw_grip", 3, 0))
        self.assertNotIn("cang_goc", HELP)
        for command in ("cang_goc", "cang_goc 40", "mo_cang 10 2", "dong_cang 10 2",
                        "mo_cang 0", "mo_cang 0.5", "dong_cang -1", "mo_cang nan",
                        "dong_cang inf", "mo_cang abc"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_command(command)

    def test_starts_closed_without_gpio_and_initial_close_is_noop(self):
        claw = self.claw()
        self.factory.assert_not_called()
        claw.grip()
        self.factory.assert_not_called()
        claw.open()
        self.assertEqual(self.output.angles[0], 100)
        self.assertEqual(self.output.angles[-1], 0)
        self.assertGreater(len(self.output.angles), 2)

    def test_open_and_close_reach_target_at_requested_time_with_gentle_ends(self):
        elapsed = 0
        writes = []
        releases = []
        output = Mock()
        def wait(seconds):
            nonlocal elapsed
            elapsed += seconds
        output.set_angle.side_effect = lambda angle: writes.append((elapsed, angle))
        output.release.side_effect = lambda: releases.append(elapsed)
        claw = self.module.ClawController(lambda: output, sleeper=wait)
        for method, start, target, seconds in ((claw.open, 100, 0, 2), (claw.grip, 0, 100, 3)):
            with self.subTest(target=target):
                elapsed = 0
                writes.clear()
                releases.clear()
                method(seconds)
                self.assertEqual(writes[0], (0, start))
                self.assertEqual(writes[-1][1], target)
                self.assertAlmostEqual(writes[-1][0], seconds)
                self.assertAlmostEqual(releases[0], seconds + 0.1)
                angles = [angle for _, angle in writes]
                self.assertGreater(len(angles), 90)
                self.assertTrue(all(0 <= angle <= 100 for angle in angles))
                differences = [b - a for a, b in zip(angles, angles[1:])]
                self.assertTrue(all(delta * (target - start) >= 0 for delta in differences))
                magnitudes = [abs(delta) for delta in differences]
                self.assertLess(max(magnitudes), 2)
                self.assertLess(magnitudes[0], max(magnitudes) / 10)
                self.assertLess(magnitudes[-1], max(magnitudes) / 10)

    def test_repeated_open_does_not_reissue_endpoint_or_move_again(self):
        claw = self.claw()
        claw.open()
        angles = self.output.angles.copy()
        waits = self.waits.copy()
        claw.open()
        self.assertEqual(self.output.angles, angles)
        self.assertEqual(self.waits, waits)

    def test_invalid_duration_never_opens_gpio(self):
        claw = self.claw()
        for seconds in (0, 0.5, 1.999, -1, float("nan"), float("inf")):
            for method in (claw.open, claw.grip):
                with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                    method(seconds)
        self.factory.assert_not_called()

    def test_interruption_releases_and_blocks_later_moves_with_unknown_position(self):
        claw = self.claw(Mock(side_effect=[KeyboardInterrupt(), None]))
        with self.assertRaises(KeyboardInterrupt):
            claw.open()
        self.assertTrue(self.output.released)
        for method in (claw.open, claw.grip):
            with self.assertRaisesRegex(RuntimeError, "khoi dong lai"):
                method()
        self.assertEqual(self.output.angles, [100])

    def test_close_is_lazy_idempotent_and_rejects_later_moves(self):
        claw = self.claw()
        claw.close()
        claw.close()
        self.factory.assert_not_called()
        with self.assertRaises(RuntimeError):
            claw.open()
        self.factory.assert_not_called()
        used = self.claw()
        used.open()
        used.close()
        self.assertTrue(self.output.closed)

    def test_mixed_queue_keeps_independent_lift_endpoints_and_stops_wheels_for_claw(self):
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
        self.session(["nang 2", "mo_cang 2.5", "ha 3", "dong_cang",
                      "chay", "chay", "thoat"], self.claw(), lift, motor)
        self.assertEqual(lift_output.angles[0], -10)
        self.assertIn(80, lift_output.angles)
        self.assertEqual(lift_output.angles[-1], -10)
        self.assertEqual(self.output.angles[0], 100)
        self.assertIn(0, self.output.angles)
        self.assertEqual(self.output.angles[-1], 100)
        self.assertAlmostEqual(sum(self.waits), 4.7)

    def test_cancelled_draft_never_opens_gpio(self):
        self.session(["mo_cang", "dong_cang 3", "dung", "chay", "thoat"], self.claw())
        self.factory.assert_not_called()

    def test_failed_claw_move_aborts_later_wheel_move(self):
        self.output.set_angle = Mock(side_effect=OSError("write failed"))
        motor = Mock()
        with self.assertRaises(OSError):
            self.session(["mo_cang", "tien 1", "chay"], self.claw(), motor_output=motor)
        self.assertTrue(self.output.released)
        self.assertFalse(any(call.args[1] > 0 for call in motor.set_duty.call_args_list))

    def test_claw_allows_100_but_lift_rejects_it_and_cleanup_is_isolated(self):
        gpio = Mock(BCM=11, OUT=0)
        lift_pwm, claw_pwm = Mock(), Mock()
        gpio.PWM.side_effect = [lift_pwm, claw_pwm]
        with patch.dict("sys.modules", {"RPi.GPIO": gpio}):
            lift = self.module.GPIOServoOutput()
            claw = self.module.GPIOServoOutput(pin=12)
        claw.set_angle(100)
        self.assertAlmostEqual(claw_pwm.ChangeDutyCycle.call_args.args[0], 8.0555555556)
        for angle in (-1, 101, float("nan"), float("inf")):
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
        claw.open()
        output.release.assert_not_called()
        lift = self.module.HandController(lambda: output, sleeper=lambda _: None)
        lift.hand_up()
        output.release.assert_not_called()

    def test_release_error_is_reported(self):
        output = Mock()
        output.release.side_effect = OSError("release failed")
        claw = self.module.ClawController(lambda: output, sleeper=lambda _: None)
        with self.assertRaisesRegex(OSError, "release failed"):
            claw.open()
        with self.assertRaisesRegex(RuntimeError, "khoi dong lai"):
            claw.grip()

    def test_main_uses_separate_kernel_pwm_providers_and_closes_both(self):
        main = importlib.import_module("vehicle_testing.main")
        gpio = Mock(BCM=11, OUT=0)
        hardware = Mock()
        lift_pwm, claw_pwm = Mock(), Mock()
        hardware.HardwarePWM.side_effect = lambda **kwargs: lift_pwm if kwargs["chip"] == 3 else claw_pwm
        real_lift, real_claw = main.HandController, main.ClawController
        with patch.dict("sys.modules", {"RPi.GPIO": gpio, "rpi_hardware_pwm": hardware}), \
                patch.object(main, "PCA9685Output"), \
                patch.object(self.module, "find_gpio_pwm_chip", return_value=3), \
                patch.object(self.module, "validate_claw_pwm_chip"), \
                patch.object(main, "HandController", side_effect=lambda factory, **kwargs: real_lift(factory, sleeper=lambda _: None, **kwargs)), \
                patch.object(main, "ClawController", side_effect=lambda factory: real_claw(factory, sleeper=lambda _: None)), \
                patch("builtins.input", side_effect=["nang 2", "mo_cang", "chay", "thoat"]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main.main([]), 0)
        gpio.PWM.assert_not_called()
        gpio.cleanup.assert_not_called()
        self.assertEqual(hardware.HardwarePWM.call_count, 2)
        hardware.HardwarePWM.assert_any_call(pwm_channel=0, hz=50, chip=3)
        hardware.HardwarePWM.assert_any_call(pwm_channel=0, hz=50, chip=0)
        self.assertTrue(lift_pwm.start.called)
        self.assertTrue(claw_pwm.start.called)
        self.assertEqual(claw_pwm.change_duty_cycle.call_args.args, (2.5,))
        self.assertTrue(lift_pwm.stop.called)
        self.assertTrue(claw_pwm.stop.called)

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
