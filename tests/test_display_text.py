"""Text rendering and terminal updates, without opening physical GPIO."""

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from vehicle_testing.hardware.displays import matrix as module


class TextRenderingTests(unittest.TestCase):
    def test_vietnamese_and_combining_accents_become_uppercase_ascii(self):
        for text in ("Xin chào đèn ế ự!", "Xin cha\u0300o đe\u0300n e\u0302\u0301 u\u031b\u0323!"):
            normalized, columns = module.text_columns(text)
            self.assertEqual(normalized, "XIN CHAO DEN E U!")
            self.assertTrue(columns)
            self.assertTrue(all(0 <= column < 128 for column in columns))

    def test_all_letters_digits_and_advertised_punctuation_are_supported(self):
        normalized, columns = module.text_columns("abcdefghijklmnopqrstuvwxyz0123456789 .,!?':;+-/=()_")
        self.assertEqual(normalized, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,!?':;+-/=()_")
        self.assertTrue(columns)

    def test_unsupported_character_is_reported_instead_of_silently_removed(self):
        with self.assertRaisesRegex(ValueError, "🙂"):
            module.text_columns("HELLO 🙂")

    def test_short_text_is_one_centered_frame(self):
        _, columns = module.text_columns("H")
        frames = list(module.text_frames(columns))
        self.assertEqual(frames, [[0] * 5 + [0x7F, 8, 8, 8, 0x7F] + [0] * 6])

    def test_blank_text_clears_all_sixteen_columns(self):
        normalized, columns = module.text_columns("   ")
        self.assertEqual(normalized, "")
        self.assertEqual(list(module.text_frames(columns)), [[0] * 16])

    def test_hello_scrolls_left_and_retains_previous_frame_sequence(self):
        normalized, columns = module.text_columns("hello")
        self.assertEqual(normalized, "HELLO")
        self.assertEqual(len(columns), 29)
        frames = list(module.text_frames(columns))
        self.assertEqual(len(frames), 46)
        self.assertEqual(frames[0], [0] * 16)
        self.assertEqual(frames[-1], [0] * 16)
        self.assertTrue(all(len(frame) == 16 for frame in frames))
        self.assertTrue(all(b[:-1] == a[1:] for a, b in zip(frames, frames[1:])))
        self.assertEqual(list(module.hello_frames()), frames)


class RecordingDisplay:
    def __init__(self, *args, **kwargs):
        self.frames = []
        self.commands = []
        self.missing_ack = 0

    def write_frame(self, frame):
        self.frames.append(list(frame))

    def show(self, frame, brightness):
        self.write_frame(frame)

    def send(self, values):
        self.commands.append(list(values))


class InteractiveTests(unittest.TestCase):
    def test_input_poll_distinguishes_no_input_blank_line_and_eof(self):
        stream = io.StringIO("\n")
        with patch.object(module.sys, "stdin", stream), \
                patch.object(module.select, "select", return_value=([stream], [], [])):
            self.assertEqual(module.read_line(0.1), "")
            with self.assertRaises(EOFError):
                module.read_line(0.1)
        with patch.object(module.select, "select", return_value=([], [], [])):
            self.assertIsNone(module.read_line(0.1))

    def test_new_line_replaces_scrolling_text_and_empty_line_clears(self):
        display = RecordingDisplay()
        reads = iter(["Xin chào", None, "OK", "", "thoat"])
        output = io.StringIO()
        with patch.object(module, "read_line", side_effect=lambda timeout: next(reads)), redirect_stdout(output):
            module.run_matrix(display, [], interactive=True)
        ok = [0, 0, 0x3E, 0x41, 0x41, 0x41, 0x3E, 0,
              0x7F, 0x08, 0x14, 0x22, 0x41, 0, 0, 0]
        self.assertIn(ok, display.frames)
        self.assertEqual(display.frames[-1], [0] * 16)
        self.assertIn("XIN CHAO", output.getvalue())

    def test_bad_input_keeps_previous_static_text_and_session_accepts_next_line(self):
        display = RecordingDisplay()
        with patch.object(module, "read_line", side_effect=["OK", "🙂", "thoat"]), redirect_stdout(io.StringIO()) as output:
            module.run_matrix(display, [], interactive=True)
        self.assertEqual(len(display.frames), 2)
        self.assertNotEqual(display.frames[-1], [0] * 16)
        self.assertIn("🙂", output.getvalue())

    def test_eof_leaves_input_loop_cleanly(self):
        with patch.object(module, "read_line", side_effect=EOFError), redirect_stdout(io.StringIO()):
            module.run_matrix(RecordingDisplay(), [], interactive=True)

    def test_long_text_repeats_until_interrupted(self):
        display = RecordingDisplay()
        _, columns = module.text_columns("HELLO")
        with patch.object(module.time, "sleep", side_effect=[None] * 46 + [KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                module.run_matrix(display, columns)
        self.assertEqual(len(display.frames), 47)
        self.assertEqual(display.frames[0], display.frames[46])


class CLITests(unittest.TestCase):
    def test_bad_text_or_matrix_mode_on_7seg_is_rejected_before_gpio(self):
        for arguments in (["--target", "7seg", "--text", "HI"],
                          ["--text", "🙂"]):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    module.main(arguments)
                self.assertEqual(error.exception.code, 2)

    def test_seven_segment_interactive_and_distance_delegate_to_number_session(self):
        for flag in ("--interactive", "--distance"):
            with self.subTest(flag=flag), patch.object(module, "seven_segment_main", return_value=0) as session:
                self.assertEqual(module.main(["--target", "7seg", flag]), 0)
                self.assertEqual("--auto" in session.call_args.args[0], flag == "--distance")

    def test_interactive_exit_disables_matrix_and_only_releases_its_gpio(self):
        class GPIO:
            BCM, OUT, HIGH = 11, 0, 1

            def __init__(self):
                self.pins = {12, 18}

            def setmode(self, mode):
                pass

            def setup(self, pin, mode, **kwargs):
                self.pins.add(pin)

            def cleanup(self, pins):
                self.pins.difference_update(pins)

        gpio = GPIO()
        display = RecordingDisplay()
        with patch.dict(sys.modules, {"RPi": SimpleNamespace(GPIO=gpio), "RPi.GPIO": gpio}), \
                patch.object(module, "DisplayLink", return_value=display), \
                patch.object(module, "read_line", side_effect=["Xin chào", "thoat"]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(["--target", "matrix", "--interactive"]), 0)
        self.assertEqual(gpio.pins, {12, 18})
        self.assertEqual(display.commands[-1], [0x80])


if __name__ == "__main__":
    unittest.main()
