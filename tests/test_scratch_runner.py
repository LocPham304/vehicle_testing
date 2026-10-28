"""Local scenario execution without opening real hardware."""

import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from vehicle_testing import scratch_runner as runner
from vehicle_testing.scratch_parser import parse_program
from vehicle_testing.test_displays import text_columns, text_frames


class RunnerTests(unittest.TestCase):
    def setUp(self):
        for context in (redirect_stdout(io.StringIO()), patch.object(runner, "logger"),
                        patch.object(runner.logging, "basicConfig")):
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def test_sample_runs_all_six_commands_and_seven_markers_in_order(self):
        program = parse_program(runner.DEFAULT_FILE.read_text(encoding="utf-8"))
        recorder = Mock()
        runner.run_program(program, recorder.motor, recorder.matrix, recorder.report)
        expected = []
        for event in program.events:
            if hasattr(event, "command"):
                if event.command == "move_forward":
                    expected.append(call.motor.move("forward", 2.0))
                elif event.command == "move_backward":
                    expected.append(call.motor.move("backward", 2.0))
                elif event.command == "turn_left":
                    expected.append(call.motor.turn_left(180.0))
                else:
                    expected.append(call.matrix.show_text(event.value))
            else:
                expected.append(call.report(event.block_id))
        expected.append(call.motor.stop())
        self.assertEqual(recorder.mock_calls, expected)

    def test_right_turn_and_command_without_marker(self):
        motor = Mock()
        runner.run_program(parse_program('robot.sendCmd("turn_right:15.5")'), motor, None)
        self.assertEqual(motor.mock_calls, [call.turn_right(15.5), call.stop()])

    def test_invalid_font_in_later_step_rejected_before_any_motor_command(self):
        motor, matrix = Mock(), Mock()
        program = parse_program('robot.sendCmd("move_forward:2")\nrobot.sendCmd("led_strip:🙂")')
        with self.assertRaisesRegex(ValueError, "font"):
            runner.run_program(program, motor, matrix)
        motor.assert_not_called()
        self.assertEqual(motor.mock_calls, [])
        self.assertEqual(matrix.mock_calls, [])

    def test_interrupt_or_error_stops_and_skips_following_commands(self):
        for error in (KeyboardInterrupt(), OSError("I2C")):
            with self.subTest(error=type(error)):
                motor, matrix = Mock(), Mock()
                motor.move.side_effect = error
                program = parse_program('robot.sendCmd("move_forward:2")\nrobot.sendCmd("led_strip:HELLO")')
                with self.assertRaises(type(error)):
                    runner.run_program(program, motor, matrix)
                motor.stop.assert_called_once_with()
                matrix.show_text.assert_not_called()

    def test_main_closes_both_devices_after_interrupt_and_close_failure(self):
        motor, matrix = Mock(), Mock()
        motor.move.side_effect = KeyboardInterrupt
        motor.close.side_effect = OSError("close motor")
        with patch.object(runner, "open_motor", return_value=motor), \
                patch.object(runner, "MatrixTextDisplay", return_value=matrix):
            self.assertEqual(runner.main([]), 1)
        motor.stop.assert_called()
        motor.close.assert_called_once_with()
        matrix.close.assert_called_once_with()

    def test_main_returns_130_on_interrupt_and_closes_devices(self):
        motor, matrix = Mock(), Mock()
        matrix.show_text.side_effect = KeyboardInterrupt
        with patch.object(runner, "open_motor", return_value=motor), \
                patch.object(runner, "MatrixTextDisplay", return_value=matrix):
            self.assertEqual(runner.main([]), 130)
        motor.close.assert_called_once_with()
        matrix.close.assert_called_once_with()

    def test_main_preflight_rejects_bad_text_without_opening_hardware(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.txt"
            source.write_text('robot.sendCmd("move_forward:2")\nrobot.sendCmd("led_strip:🙂")', encoding="utf-8")
            with patch.object(runner, "open_motor") as motor, \
                    patch.object(runner, "MatrixTextDisplay") as matrix:
                self.assertEqual(runner.main(["--file", str(source)]), 1)
            motor.assert_not_called()
            matrix.assert_not_called()

    def test_dry_run_never_opens_hardware_or_waits(self):
        with patch.object(runner, "open_motor") as motor, \
                patch.object(runner, "MatrixTextDisplay") as matrix, \
                patch.object(runner.time, "sleep", side_effect=AssertionError("must not wait")):
            self.assertEqual(runner.main(["--dry-run"]), 0)
        motor.assert_not_called()
        matrix.assert_not_called()

    def test_failed_matrix_initialization_closes_motor_before_any_motion(self):
        motor = Mock()
        with patch.object(runner, "open_motor", return_value=motor), \
                patch.object(runner, "MatrixTextDisplay", side_effect=OSError("GPIO")):
            self.assertEqual(runner.main([]), 1)
        motor.move.assert_not_called()
        motor.close.assert_called_once_with()

    def test_matrix_cleanup_error_still_closes_motor(self):
        motor, matrix = Mock(), Mock()
        matrix.close.side_effect = OSError("GPIO cleanup")
        with patch.object(runner, "open_motor", return_value=motor), \
                patch.object(runner, "MatrixTextDisplay", return_value=matrix):
            self.assertEqual(runner.main([]), 1)
        motor.close.assert_called_once_with()

    def test_matrix_only_scenario_does_not_open_motor(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "text.txt"
            source.write_text('robot.sendCmd("led_strip:HELLO")', encoding="utf-8")
            with patch.object(runner, "open_motor") as motor, \
                    patch.object(runner, "MatrixTextDisplay") as matrix:
                self.assertEqual(runner.main(["--file", str(source)]), 0)
            motor.assert_not_called()
            matrix.return_value.show_text.assert_called_once_with("HELLO")
            matrix.return_value.close.assert_called_once_with()

    def test_direct_and_module_cli_from_other_directory(self):
        root = Path(__file__).resolve().parents[2]
        for command, cwd in (([str(root / "vehicle_testing/scratch_runner.py")], root.parent),
                             (["-m", "vehicle_testing.scratch_runner"], root)):
            result = subprocess.run([sys.executable, "-B", *command, "--dry-run"], cwd=cwd,
                                    capture_output=True, encoding="utf-8", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("HOAN TAT", result.stdout)
            self.assertIn("VAN BAN", result.stdout)


class MatrixTests(unittest.TestCase):
    def test_text_scrolls_once_and_vietnamese_uses_existing_font(self):
        gpio, link, sleep = Mock(), Mock(), Mock()
        display = runner.MatrixTextDisplay(gpio=gpio, link_factory=Mock(return_value=link), sleeper=sleep)
        display.show_text("văn bản")
        frames = list(text_frames(text_columns("VAN BAN")[1]))
        self.assertEqual(link.write_frame.call_args_list, [call(frame) for frame in frames])
        self.assertEqual(sleep.call_args_list, [call(0.1)] * len(frames))
        display.close()
        link.send.assert_called_with([0x80])
        gpio.cleanup.assert_called_once_with([7, 5])

    def test_short_text_holds_one_second_and_empty_text_clears(self):
        link, sleep = Mock(), Mock()
        display = runner.MatrixTextDisplay(gpio=Mock(), link_factory=Mock(return_value=link), sleeper=sleep)
        display.show_text("OK")
        sleep.assert_called_once_with(1.0)
        display.show_text("")
        self.assertEqual(link.write_frame.call_args, call([0] * 16))

    def test_failed_initialization_releases_only_configured_pins(self):
        gpio = Mock()
        gpio.setup.side_effect = [None, OSError("pin")]
        with self.assertRaises(OSError):
            runner.MatrixTextDisplay(gpio=gpio)
        gpio.cleanup.assert_called_once_with([7])

    def test_close_failure_still_cleans_gpio(self):
        gpio, link = Mock(), Mock()
        display = runner.MatrixTextDisplay(gpio=gpio, link_factory=Mock(return_value=link))
        link.send.side_effect = OSError("write")
        with self.assertRaises(OSError):
            display.close()
        gpio.cleanup.assert_called_once_with([7, 5])


if __name__ == "__main__":
    unittest.main()
