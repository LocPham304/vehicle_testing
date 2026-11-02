"""Absolute lift angles through the main CLI, without physical outputs."""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from vehicle_testing.cli.robot import parse_command, run_session
from vehicle_testing.hardware import servos


class AbsoluteLiftTests(unittest.TestCase):
    def test_cli_accepts_absolute_angle_and_optional_duration(self):
        for line, expected in (
            ("nang 60", ("hand_up", 60, 2)),
            ("ha 20 3", ("hand_down", 20, 3)),
            ("nang 0", ("hand_up", 0, 2)),
            ("ha 90", ("hand_down", 90, 2)),
            ("nang 12.5 0.2", ("hand_up", 12.5, 0.2)),
        ):
            with self.subTest(line=line):
                self.assertEqual(parse_command(line), expected)

    def test_invalid_lift_command_is_rejected_before_queueing(self):
        for line in ("nang", "ha", "nang -1", "ha 91", "nang nan", "ha inf",
                     "nang 20 nan", "ha 20 inf", "nang 20 0.1", "ha 20 61",
                     "nang 20 2 extra"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_command(line)

    def test_trial_pulses_are_relabelled_zero_to_ninety(self):
        self.assertEqual(servos.SERVO_START_ANGLE, 0)
        self.assertAlmostEqual(servos.hand_angle_to_pulse_us(0), 450)
        self.assertAlmostEqual(servos.hand_angle_to_pulse_us(90), 1400)
        self.assertAlmostEqual(servos.hand_angle_to_pulse_us(60), 1083.3333333333)
        self.assertFalse(servos.SERVO_HOLD_POSITION)

    def test_main_queue_stops_wheels_and_passes_target_and_duration(self):
        events = []
        motor, hand = Mock(), Mock()
        motor.stop.side_effect = lambda: events.append("stop")
        hand.hand_up.side_effect = lambda **kw: events.append(("up", kw))
        hand.hand_down.side_effect = lambda **kw: events.append(("down", kw))
        lines = ["nang 60", "ha 20 3", "chay", "chay", "thoat"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            run_session(motor, hand)
        self.assertEqual(events, ["stop", ("up", {"angle": 60, "seconds": 2}),
                                  "stop", ("down", {"angle": 20, "seconds": 3})])

    def test_controller_moves_to_intermediate_angles_and_releases(self):
        output, waits = Mock(), []
        hand = servos.HandController(lambda: output, sleeper=waits.append)
        hand.hand_up(angle=60, seconds=2)
        self.assertEqual(output.set_angle.call_args.args, (60,))
        output.set_angle.reset_mock()
        hand.hand_down(angle=20, seconds=3)
        angles = [c.args[0] for c in output.set_angle.call_args_list]
        self.assertEqual((angles[0], angles[-1]), (60, 20))
        self.assertTrue(all(20 <= angle <= 60 for angle in angles))
        self.assertTrue(all(a >= b for a, b in zip(angles, angles[1:])))
        self.assertAlmostEqual(sum(waits), 5.2)
        self.assertEqual(output.release.call_count, 2)

    def test_invalid_direct_target_never_opens_gpio(self):
        factory = Mock()
        hand = servos.HandController(factory, sleeper=lambda _: None)
        for angle in (-1, 91, float("nan"), float("inf")):
            with self.subTest(angle=angle), self.assertRaises(ValueError):
                hand.hand_up(angle=angle)
        factory.assert_not_called()

    def test_trajectory_matches_the_accepted_standalone(self):
        from vehicle_testing.tests import test_lift_angle as trial
        output, main_waits, trial_angles, trial_waits = Mock(), [], [], []
        hand = servos.HandController(lambda: output, sleeper=main_waits.append)
        experiment = trial.LiftExperiment(dry_run=False)
        with patch.object(experiment, "_open"), \
                patch.object(experiment, "_set_angle", side_effect=trial_angles.append), \
                patch.object(trial.time, "sleep", side_effect=trial_waits.append):
            with redirect_stdout(io.StringIO()):
                experiment.move(60, 2)
                experiment.move(20, 3)
        hand.hand_up(angle=60, seconds=2)
        hand.hand_down(angle=20, seconds=3)
        self.assertEqual([c.args[0] for c in output.set_angle.call_args_list], trial_angles)
        self.assertEqual(main_waits, trial_waits)


if __name__ == "__main__":
    unittest.main()
