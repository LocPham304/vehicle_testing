"""Tests use an in-memory output in place of the physical PCA9685."""

import importlib
import io
import subprocess
import sys
import unittest
from dataclasses import replace
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
ENTRY_POINT = ROOT / "vehicle_testing" / "main.py"


class RecordingOutput:
    def __init__(self):
        self.values = {}
        self.writes = []
        self.closed = False
        self.failure = None

    def set_duty(self, channel, duty):
        self.writes.append((channel, duty))
        if self.failure is not None and self.failure(channel, duty):
            raise OSError("I2C write failed")
        self.values[channel] = duty

    def close(self):
        self.closed = True


class CommandLineTests(unittest.TestCase):
    def run_cli(self, text, *flags):
        return subprocess.run(
            [sys.executable, str(ENTRY_POINT), "--dry-run", *flags],
            input=text, capture_output=True, text=True, timeout=10, cwd=ROOT,
        )

    def test_forward_and_backward_work_without_hardware_libraries(self):
        result = self.run_cli("tien 0.001 0.5\nlui 0.001 0.3\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TIEN", result.stdout)
        self.assertIn("LUI", result.stdout)
        self.assertIn("50%", result.stdout)
        self.assertIn("30%", result.stdout)

    def test_invalid_command_does_not_end_the_session(self):
        result = self.run_cli("tien 1 5\ntien nan 0.5\nabc\ntien 0.001 0.5\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TIEN", result.stdout)
        self.assertEqual(result.stdout.count("Lenh khong hop le:"), 3)

    def test_multiline_commands_use_50_percent_each_time_pwm_is_omitted(self):
        result = self.run_cli(
            "tien 0.001 0.3\ntien 0.001\nlui 0.002\ntien 0.003\nlui 0.004\nchay\n"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        movements = [
            line.split("INFO: ", 1)[1] for line in result.stdout.splitlines()
            if "INFO: TIEN trong" in line or "INFO: LUI trong" in line
        ]
        self.assertEqual(movements, [
            "TIEN trong 0.001 giay, PWM 30%",
            "TIEN trong 0.001 giay, PWM 50%",
            "LUI trong 0.002 giay, PWM 50%",
            "TIEN trong 0.003 giay, PWM 50%",
            "LUI trong 0.004 giay, PWM 50%",
        ])

    def test_drafting_commands_never_starts_motion_without_chay(self):
        for ending in ("", "thoat\n"):
            with self.subTest(ending=ending):
                result = self.run_cli("tien 0.001\nngung 0.001\nlui 0.001\n" + ending)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("INFO: TIEN trong", result.stdout)
                self.assertNotIn("INFO: LUI trong", result.stdout)
                self.assertNotIn("INFO: NGUNG trong", result.stdout)

    def test_script_runs_pause_between_forward_and_backward(self):
        result = self.run_cli("tien 0.001\nngung 0.002\nlui 0.003\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        steps = [
            line.split("INFO: ", 1)[1] for line in result.stdout.splitlines()
            if any(label in line for label in ("INFO: TIEN trong", "INFO: NGUNG trong", "INFO: LUI trong"))
        ]
        self.assertEqual(steps, [
            "TIEN trong 0.001 giay, PWM 50%",
            "NGUNG trong 0.002 giay",
            "LUI trong 0.003 giay, PWM 50%",
        ])

    def test_a_second_chay_does_not_replay_completed_commands(self):
        result = self.run_cli("tien 0.001\nchay\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("INFO: TIEN trong"), 1)

    def test_dung_discards_commands_waiting_to_run(self):
        result = self.run_cli("tien 0.001\ndung\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("INFO: TIEN trong", result.stdout)

    def test_empty_script_can_be_followed_by_a_new_script(self):
        result = self.run_cli("chay\nlui 0.001\nchay\ntien 0.001\nchay\nthoat\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("INFO: LUI trong"), 1)
        self.assertEqual(result.stdout.count("INFO: TIEN trong"), 1)

    def test_end_of_input_exits_cleanly(self):
        result = self.run_cli("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_module_entry_point_also_works(self):
        result = subprocess.run(
            [sys.executable, "-m", "vehicle_testing.main", "--dry-run"],
            input="dung\nthoat\n", capture_output=True, text=True,
            timeout=10, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class MotorControllerTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.controller")
        self.config = importlib.import_module("vehicle_testing.config")
        self.output = RecordingOutput()

    def controller(self, sleeper=lambda seconds: None, motors=None):
        return self.module.MotorController(
            self.output, motors=self.config.MOTORS if motors is None else motors,
            sleeper=sleeper,
        )

    def test_all_four_motors_remain_enabled_during_forward_motion(self):
        snapshots = []

        def observe(seconds):
            if seconds == 2:
                snapshots.append(dict(self.output.values))

        self.controller(observe).move("forward", seconds=2, speed=0.5)
        self.assertEqual(snapshots, [{
            0: 32767, 6: 32767, 15: 32767, 9: 32767,
            2: 65535, 1: 0, 4: 65535, 5: 0,
            14: 65535, 13: 0, 10: 65535, 11: 0,
        }])
        self.assertTrue(all(value == 0 for value in self.output.values.values()))

    def test_backward_reverses_direction_but_keeps_requested_pwm(self):
        snapshots = []

        def observe(seconds):
            if seconds == 2:
                snapshots.append(dict(self.output.values))

        self.controller(observe).move("backward", seconds=2, speed=0.25)
        self.assertEqual(snapshots, [{
            0: 16383, 6: 16383, 15: 16383, 9: 16383,
            2: 0, 1: 65535, 4: 0, 5: 65535,
            14: 0, 13: 65535, 10: 0, 11: 65535,
        }])

    def test_direct_moves_default_to_50_percent_after_an_explicit_speed(self):
        snapshots = []

        def observe(seconds):
            if seconds == 2:
                snapshots.append(tuple(self.output.values[ch] for ch in (0, 6, 15, 9)))

        controller = self.controller(observe)
        controller.move("forward", 2, 0.3)
        controller.move("backward", 2)
        controller.move("forward", 2)
        self.assertEqual(snapshots, [
            (19660, 19660, 19660, 19660),
            (32767, 32767, 32767, 32767),
            (32767, 32767, 32767, 32767),
        ])

    def test_direction_switch_disables_all_pwm_before_setting_new_direction(self):
        controller = self.controller()
        controller.move("forward", 1, 0.5)
        self.output.writes.clear()
        controller.move("backward", 1, 0.5)

        writes = self.output.writes
        self.assertEqual(writes[:4], [(0, 0), (6, 0), (15, 0), (9, 0)])
        first_enable = next(
            index for index, (channel, duty) in enumerate(writes)
            if channel in (0, 6, 15, 9) and duty > 0
        )
        self.assertEqual(writes[4:first_enable], [
            (2, 0), (1, 0), (4, 0), (5, 0),
            (14, 0), (13, 0), (10, 0), (11, 0),
            (2, 0), (1, 65535), (4, 0), (5, 65535),
            (14, 0), (13, 65535), (10, 0), (11, 65535),
        ])

    def test_one_inverted_motor_does_not_reverse_the_other_motors(self):
        motors = dict(self.config.MOTORS)
        motors["FR"] = replace(motors["FR"], inverted=True)
        snapshots = []

        def observe(seconds):
            if seconds == 2:
                snapshots.append(dict(self.output.values))

        self.controller(observe, motors).move("forward", 2, 0.5)
        self.assertEqual((snapshots[0][2], snapshots[0][1]), (0, 65535))
        self.assertEqual((snapshots[0][4], snapshots[0][5]), (65535, 0))

    def test_interruption_during_wait_stops_every_motor(self):
        def interrupted_wait(seconds):
            if seconds == 2:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.controller(interrupted_wait).move("forward", 2, 0.5)
        self.assertTrue(all(value == 0 for value in self.output.values.values()))

    def test_partial_start_failure_stops_motors_already_enabled(self):
        self.output.failure = lambda channel, duty: channel == 6 and duty > 0
        with self.assertRaisesRegex(OSError, "I2C write failed"):
            self.controller().move("forward", 2, 0.5)
        self.assertTrue(all(value == 0 for value in self.output.values.values()))

    def test_stop_attempts_other_channels_when_one_write_fails(self):
        self.output.failure = lambda channel, duty: channel == 0
        with self.assertRaises(OSError):
            self.controller().stop()
        self.assertEqual(set(self.output.values), {6, 15, 9, 2, 1, 4, 5, 14, 13, 10, 11})
        self.assertTrue(all(value == 0 for value in self.output.values.values()))

    def test_close_releases_output_even_if_stopping_fails(self):
        self.output.failure = lambda channel, duty: channel == 0
        with self.assertRaises(OSError):
            self.controller().close()
        self.assertTrue(self.output.closed)

    def test_invalid_motion_is_rejected_before_writing_hardware(self):
        cases = [
            ("sideways", 1, 0.5), ("forward", 0, 0.5),
            ("forward", -1, 0.5), ("forward", float("nan"), 0.5),
            ("forward", float("inf"), 0.5), ("forward", 1, 0),
            ("forward", 1, -0.1), ("forward", 1, 5),
            ("forward", 1, float("nan")), ("forward", 1, float("inf")),
        ]
        controller = self.controller()
        for direction, seconds, speed in cases:
            with self.subTest(direction=direction, seconds=seconds, speed=speed):
                with self.assertRaises(ValueError):
                    controller.move(direction, seconds, speed)
        self.assertEqual(self.output.writes, [])

    def test_conflicting_motor_channels_are_rejected(self):
        motors = dict(self.config.MOTORS)
        motors["FL"] = motors["FR"]
        with self.assertRaises(ValueError):
            self.controller(motors=motors)
        self.assertEqual(self.output.writes, [])

    def test_pause_stops_all_channels_before_waiting(self):
        self.output.values = {
            0: 32767, 6: 32767, 15: 32767, 9: 32767,
            2: 65535, 1: 0, 4: 65535, 5: 0,
            14: 65535, 13: 0, 10: 65535, 11: 0,
        }
        waits = []

        def observe(seconds):
            waits.append(seconds)
            self.assertTrue(all(value == 0 for value in self.output.values.values()))

        self.controller(observe).pause(0.5)
        self.assertEqual(waits, [0.5])
        self.assertTrue(all(duty == 0 for channel, duty in self.output.writes))

    def test_pause_accepts_long_duration_without_capping_it(self):
        waits = []
        self.controller(waits.append).pause(86400)
        self.assertEqual(waits, [86400])

    def test_pause_rejects_invalid_duration_before_any_channel_write(self):
        controller = self.controller()
        for seconds in (0, -1, float("nan"), float("inf")):
            with self.subTest(seconds=seconds):
                with self.assertRaises(ValueError):
                    controller.pause(seconds)
        self.assertEqual(self.output.writes, [])

    def test_pause_cannot_use_a_closed_controller(self):
        controller = self.controller()
        controller.close()
        self.output.writes.clear()
        with self.assertRaises(RuntimeError):
            controller.pause(0.5)
        self.assertEqual(self.output.writes, [])


class ScriptSessionTests(unittest.TestCase):
    def test_enter_only_saves_commands_until_chay_is_entered(self):
        module = importlib.import_module("vehicle_testing.main")
        output = RecordingOutput()
        active_states = []

        def observe(seconds):
            if seconds in (2, 3):
                active_states.append((seconds, output.values[2], output.values[1]))

        controller = module.MotorController(output, sleeper=observe)
        lines = iter(["tien 2", "lui 3 0.3", "chay", "thoat"])

        def read_line(prompt):
            line = next(lines)
            if line != "thoat":
                self.assertEqual(output.writes, [], "Motion started before chay was submitted")
            return line

        with patch("builtins.input", side_effect=read_line), redirect_stdout(io.StringIO()):
            module.run_session(controller)
        self.assertEqual(active_states, [(2.0, 65535, 0), (3.0, 0, 65535)])
        self.assertTrue(all(value == 0 for value in output.values.values()))

    def test_failed_first_command_does_not_start_remaining_commands(self):
        module = importlib.import_module("vehicle_testing.main")
        output = RecordingOutput()
        output.failure = lambda channel, duty: channel == 6 and duty > 0
        controller = module.MotorController(output, sleeper=lambda seconds: None)
        lines = ["tien 2", "lui 3", "chay"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                module.run_session(controller)
        self.assertNotIn((1, 65535), output.writes)
        self.assertTrue(all(value == 0 for value in output.values.values()))

    def test_script_keeps_motors_off_for_the_requested_pause_then_resumes(self):
        module = importlib.import_module("vehicle_testing.main")
        output = RecordingOutput()
        states = []

        def observe(seconds):
            if seconds in (2, 0.5, 1):
                states.append((seconds, output.values[0], output.values[2], output.values[1]))
            if seconds == 0.5:
                self.assertTrue(all(value == 0 for value in output.values.values()))

        controller = module.MotorController(output, sleeper=observe)
        lines = ["tien 2", "ngung 0.5", "lui 1", "chay", "thoat"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            module.run_session(controller)
        self.assertEqual(states, [
            (2.0, 32767, 65535, 0),
            (0.5, 0, 0, 0),
            (1.0, 32767, 0, 65535),
        ])

    def test_interrupted_pause_does_not_run_remaining_commands(self):
        module = importlib.import_module("vehicle_testing.main")
        output = RecordingOutput()

        def interrupted_wait(seconds):
            if seconds == 0.5:
                raise KeyboardInterrupt

        controller = module.MotorController(output, sleeper=interrupted_wait)
        lines = ["ngung 0.5", "lui 1", "chay"]
        with patch("builtins.input", side_effect=lines), redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                module.run_session(controller)
        self.assertTrue(all(value == 0 for value in output.values.values()))
        self.assertFalse(any(duty > 0 for channel, duty in output.writes))


class CommandParserTests(unittest.TestCase):
    def test_pause_accepts_fractional_and_long_durations_without_pwm(self):
        parse = importlib.import_module("vehicle_testing.main").parse_command
        self.assertEqual(parse(" NGUNG 0.5 "), ("pause", 0.5, 0.0))
        self.assertEqual(parse("ngung 86400"), ("pause", 86400.0, 0.0))

    def test_pause_rejects_missing_extra_or_invalid_duration(self):
        parse = importlib.import_module("vehicle_testing.main").parse_command
        for text in ("ngung", "ngung 0.5 0.3", "ngung abc", "ngung 0", "ngung -1", "ngung nan", "ngung inf"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse(text)

    def test_valid_commands_keep_seconds_separate_from_speed(self):
        parse = importlib.import_module("vehicle_testing.main").parse_command
        self.assertEqual(parse(" TIEN 5 0.5 "), ("forward", 5.0, 0.5))
        self.assertEqual(parse("lui 1.5 0.3"), ("backward", 1.5, 0.3))
        self.assertEqual(parse("dung"), ("stop", 0.0, 0.0))
        self.assertEqual(parse("thoat"), ("exit", 0.0, 0.0))
        self.assertEqual(parse(" CHAY "), ("run", 0.0, 0.0))

    def test_omitted_pwm_defaults_to_50_percent_for_both_directions(self):
        parse = importlib.import_module("vehicle_testing.main").parse_command
        self.assertEqual(parse("tien 2 0.3"), ("forward", 2.0, 0.3))
        self.assertEqual(parse(" TIEN 2 "), ("forward", 2.0, 0.5))
        self.assertEqual(parse("lui 2"), ("backward", 2.0, 0.5))

    def test_omitted_pwm_does_not_allow_invalid_duration(self):
        parse = importlib.import_module("vehicle_testing.main").parse_command
        for text in ("tien nan", "tien inf", "lui 0", "lui -2", "tien abc"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse(text)

    def test_malformed_commands_are_rejected(self):
        parse = importlib.import_module("vehicle_testing.main").parse_command
        for text in ("", "abc", "tien", "tien 2 0.5 extra", "lui abc 0.5", "dung 2", "thoat now", "chay 2"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse(text)


class HardwareOutputTests(unittest.TestCase):
    """Replace only the unavailable physical bus/chip, not the adapter."""

    def test_frequency_setup_failure_releases_both_chip_and_bus(self):
        class BrokenChip:
            closed = False

            @property
            def frequency(self):
                return 0

            @frequency.setter
            def frequency(self, value):
                raise OSError("frequency setup failed")

            def deinit(self):
                self.closed = True

        bus = SimpleNamespace(closed=False)
        bus.deinit = lambda: setattr(bus, "closed", True)
        chip = BrokenChip()
        modules = {
            "board": SimpleNamespace(SCL=1, SDA=2),
            "busio": SimpleNamespace(I2C=lambda scl, sda: bus),
            "adafruit_pca9685": SimpleNamespace(PCA9685=lambda bus, address: chip),
        }
        output_type = importlib.import_module("vehicle_testing.controller").PCA9685Output
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(OSError, "frequency setup failed"):
                output_type()
        self.assertTrue(chip.closed)
        self.assertTrue(bus.closed)

    def test_chip_cleanup_error_does_not_prevent_bus_cleanup(self):
        def fail_cleanup():
            raise OSError("chip cleanup failed")

        bus = SimpleNamespace(closed=False)
        bus.deinit = lambda: setattr(bus, "closed", True)
        chip = SimpleNamespace(deinit=fail_cleanup)
        modules = {
            "board": SimpleNamespace(SCL=1, SDA=2),
            "busio": SimpleNamespace(I2C=lambda scl, sda: bus),
            "adafruit_pca9685": SimpleNamespace(PCA9685=lambda bus, address: chip),
        }
        output_type = importlib.import_module("vehicle_testing.controller").PCA9685Output
        with patch.dict(sys.modules, modules):
            output = output_type()
            with self.assertRaisesRegex(OSError, "chip cleanup failed"):
                output.close()
        self.assertTrue(bus.closed)


if __name__ == "__main__":
    unittest.main()
