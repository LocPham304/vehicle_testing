"""Validate generated Python as data, preserving Scratch markers and ordering."""

import importlib
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "vehicle_testing/examples/scratch_sample.txt"


class ImportTests(unittest.TestCase):
    def test_parser_import_is_available_without_hardware_or_mqtt(self):
        code = ("import sys; from vehicle_testing.scratch_parser import parse_program; "
                "assert not any(n in sys.modules for n in "
                "('RPi.GPIO', 'board', 'serial', 'paho', 'vehicle_testing.controller'))")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.scratch_parser")

    def test_user_sample_preserves_seven_markers_and_six_commands(self):
        program = self.module.parse_program(SAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(len(program.events), 13)
        self.assertEqual(program.marker_count, 7)
        self.assertEqual(program.command_count, 6)
        self.assertEqual(program.events[0].block_id, ')xzR$@uEnJi(Jj%.p)n7')
        self.assertEqual(program.events[1].block_id, 'V0D(SIWG2DO%83`i0VG0')
        self.assertEqual(program.events[2].block_id, 'V0D(SIWG2DO%83`i0VG0')
        self.assertEqual(program.events[2].command, "move_forward")
        self.assertEqual(program.events[2].value, 2)
        self.assertEqual(program.events[2].unit, "seconds")
        self.assertEqual(program.events[4].unit, "degrees")
        self.assertEqual(program.events[6].value, 10)
        self.assertEqual(program.events[8].value, 10)
        self.assertNotEqual(program.events[6].block_id, program.events[8].block_id)
        self.assertEqual(program.events[-1].value, "văn bản")
        self.assertEqual(program.events[-1].line, 13)

    def test_source_comments_blank_lines_quotes_and_text_colons_are_preserved(self):
        source = '# test\n\nreport_block(\'id: $@`\')\nrobot.sendCmd(\'led_strip:văn: "bản"\\\\file\')\n'
        program = self.module.parse_program(source)
        self.assertEqual(program.events[0].line, 3)
        self.assertEqual(program.events[1].value, 'văn: "bản"\\file')
        self.assertEqual(program.events[1].block_id, 'id: $@`')

    def test_marker_only_program_and_command_without_marker_are_valid(self):
        self.assertEqual(self.module.parse_program('report_block("start")').command_count, 0)
        event = self.module.parse_program('robot.sendCmd("turn_right:90")').events[0]
        self.assertIsNone(event.block_id)
        self.assertEqual(event.value, 90)

    def test_multiple_commands_share_nearest_marker_without_losing_duplicates(self):
        program = self.module.parse_program('report_block("a")\nrobot.sendCmd("move_backward:10")\nrobot.sendCmd("move_backward:10")')
        self.assertEqual(program.command_count, 2)
        self.assertEqual([event.block_id for event in program.events], ["a", "a", "a"])

    def test_empty_text_and_fractional_seconds_are_supported(self):
        program = self.module.parse_program('robot.sendCmd("led_strip:")\nrobot.sendCmd("move_forward:0.5")')
        self.assertEqual(program.events[0].value, "")
        self.assertEqual(program.events[1].value, 0.5)

    def test_unsupported_syntax_is_rejected_without_running_it(self):
        sources = [
            'import os', 'value = 1', 'for i in range(2):\n report_block("a")',
            'while True:\n report_block("a")', 'print("hello")',
            'other.sendCmd("move_forward:1")', 'robot.other("move_forward:1")',
            'robot.sendCmd(__import__("os").getcwd())',
            'robot.sendCmd(f"move_forward:{1}")', 'report_block("a" + "b")',
            'report_block(id="a")', 'report_block(*["a"])',
            'report_block("a", "done")', 'report_block(123)', 'robot.sendCmd(1)',
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(self.module.ScratchParseError):
                self.module.parse_program(source)

    def test_bad_command_late_in_program_rejects_whole_program_with_line(self):
        for command in ('bad:10', 'move_forward', 'move_forward:0', 'move_forward:-1',
                        'move_backward:nan', 'turn_left:inf', 'turn_right:1e999', 'turn_right:abc'):
            with self.subTest(command=command):
                with self.assertRaises(self.module.ScratchParseError) as error:
                    self.module.parse_program('report_block("a")\nrobot.sendCmd("move_forward:1")\nrobot.sendCmd("' + command + '")')
                self.assertEqual(error.exception.line, 3)

    def test_empty_source_syntax_errors_and_oversized_source_are_reported(self):
        for source in ('', ' # comments only', 'robot.sendCmd("x)', ' ' * 65537):
            with self.subTest(source=source[:30]), self.assertRaises(self.module.ScratchParseError):
                self.module.parse_program(source)

    def test_readable_preview_uses_seconds_degrees_and_original_block_ids(self):
        program = self.module.parse_program(SAMPLE.read_text(encoding="utf-8"))
        text = self.module.format_program(program)
        self.assertIn("7 block", text)
        self.assertIn("6 lenh", text)
        self.assertIn("2 giay", text)
        self.assertIn("180 do", text)
        self.assertIn("văn bản", text)
        self.assertIn('V0D(SIWG2DO%83`i0VG0', text)


if __name__ == "__main__":
    unittest.main()
