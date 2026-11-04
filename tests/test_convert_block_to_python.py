"""Review the standalone converter using a fake SDK, never robot hardware."""

from pathlib import Path
from dataclasses import FrozenInstanceError
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
from vehicle_testing.helpers import ConvertBlockToPython as converter


class ConverterRegressionTests(unittest.TestCase):
    def execute_with_fake_sdk(self, source):
        calls = []

        class Robot:
            def __getattr__(self, name):
                return lambda *args: calls.append((name, *args))

        sdk = types.ModuleType("robot_sdk")
        sdk.Robot = Robot
        namespace = {}
        code = converter.convert_block_to_python(source, keep_block_ids=True)
        with patch.dict(sys.modules, {"robot_sdk": sdk}):
            exec(compile(code, "converted.py", "exec"), namespace)
        return calls, namespace

    def test_sample_preserves_all_markers_commands_duplicates_and_unicode(self):
        source = (ROOT / "vehicle_testing/examples/scratch_sample.txt").read_text(encoding="utf-8")
        calls, _ = self.execute_with_fake_sdk(source)
        self.assertEqual(sum(call[0] == "report_block" for call in calls), 7)
        self.assertEqual([call for call in calls if call[0] != "report_block"], [
            ("move_forward", 2.0), ("turn_left", 180.0), ("move_backward", 2.0),
            ("move_backward", 2.0), ("led_strip", "fffffffffff"),
            ("led_strip", "văn bản"), ("stop",),
        ])

    def test_hand_up_and_resource_groups(self):
        calls, namespace = self.execute_with_fake_sdk(
            'robot.sendCmd("hand_up:90")\nrobot.sendCmd("move_forward:2")\n'
            'robot.sendCmd("led_strip:HELLO")\nrobot.sendCmd("stop:")')
        self.assertEqual(calls[0], ("hand_up", 90.0))
        self.assertEqual(set(namespace["REQUIRED_RESOURCES"]), {"hand", "motor", "matrix"})
        commands = converter.parse_commands('robot.sendCmd("move_forward:2")')
        self.assertEqual(commands[0].resource, "motor")

    def test_all_simulator_robot_blocks_convert_with_the_fe_command_names(self):
        # Match BlockInitializer generators: the two text blocks share led_strip;
        # face commands retain the robot_ prefix and have no argument/colon.
        payloads = [
            'move_forward:0.5', 'move_backward:0.5', 'turn_left:90', 'turn_right:90',
            'hand_up:90', 'hand_down:0', 'led_strip:Hello World', 'led_strip:văn bản',
            'robot_led_matrix_smile', 'robot_led_matrix_cry',
            'robot_led_matrix_normal', 'robot_led_matrix_excited',
        ]
        source = '\n'.join(
            f'report_block("block-{index}") robot.sendCmd({payload!r})'
            for index, payload in enumerate(payloads)
        )
        calls, namespace = self.execute_with_fake_sdk(source)
        actions = [call for call in calls if call[0] != 'report_block']
        self.assertEqual(actions, [
            ('move_forward', 0.5), ('move_backward', 0.5),
            ('turn_left', 90.0), ('turn_right', 90.0),
            ('hand_up', 90.0), ('hand_down', 0.0),
            ('led_strip', 'Hello World'), ('led_strip', 'văn bản'),
            ('robot_led_matrix_smile',), ('robot_led_matrix_cry',),
            ('robot_led_matrix_normal',), ('robot_led_matrix_excited',), ('stop',),
        ])
        self.assertEqual([call for call in calls if call[0] == 'report_block'],
                         [('report_block', f'block-{index}') for index in range(12)])
        self.assertEqual(namespace['REQUIRED_RESOURCES'], ('motor', 'hand', 'matrix'))

    def test_hand_down_accepts_absolute_targets_and_rejects_invalid_angles(self):
        for value in ('0', '45.5', '90'):
            with self.subTest(value=value):
                events = converter.parse_commands(f'robot.sendCmd("hand_down:{value}")')
                self.assertEqual(events[0].arg, float(value))
                self.assertEqual(events[0].resource, 'hand')
        for payload in ('hand_down', 'hand_down:', 'hand_down:-1', 'hand_down:91',
                        'hand_down:nan', 'hand_down:inf', 'hand_down:abc'):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                    converter.BlockConvertError, 'Dòng 2'):
                converter.parse_commands(f'report_block("down")\nrobot.sendCmd({payload!r})')

    def test_face_commands_take_no_argument_and_require_only_matrix(self):
        for face in ('smile', 'cry', 'normal', 'excited'):
            name = f'robot_led_matrix_{face}'
            for suffix in ('', ':'):
                with self.subTest(name=name, suffix=suffix):
                    calls, namespace = self.execute_with_fake_sdk(
                        f'robot.sendCmd({(name + suffix)!r})')
                    self.assertEqual(calls, [(name,), ('stop',)])
                    self.assertEqual(namespace['REQUIRED_RESOURCES'], ('matrix',))
            with self.assertRaisesRegex(converter.BlockConvertError, 'không có tham số'):
                converter.parse_commands(f'robot.sendCmd("{name}:1")')

    def test_adjacent_calls_comments_and_original_line_for_errors(self):
        calls, _ = self.execute_with_fake_sdk(
            'report_block("id") robot.sendCmd("move_forward:2") # comment\n'
            'robot.sendCmd("hand_up:45")')
        self.assertEqual(calls[:3], [("report_block", "id"), ("move_forward", 2.0), ("hand_up", 45.0)])
        with self.assertRaisesRegex(converter.BlockConvertError, "Dòng 2"):
            converter.parse_commands('report_block("a") robot.sendCmd("move_forward:1")\n'
                                     'robot.sendCmd("hand_up:180")')

    def test_leading_spaces_and_tabs_are_accepted_and_line_numbers_stay_original(self):
        source = ('  report_block("start")\r\n'
                  '\trobot.sendCmd("move_forward:2")\r\n'
                  ' robot.sendCmd("hand_up:45")')
        calls, _ = self.execute_with_fake_sdk(source)
        self.assertEqual(calls, [
            ("report_block", "start"), ("move_forward", 2.0), ("hand_up", 45.0), ("stop",),
        ])
        events = converter.parse_commands(source, keep_block_ids=True)
        self.assertEqual([event.line for event in events], [1, 2, 3])
        with self.assertRaisesRegex(converter.BlockConvertError, "Dòng 3"):
            converter.parse_commands(source.replace("hand_up:45", "hand_up:180"))

    def test_unicode_line_separators_inside_strings_do_not_shift_insertions(self):
        for separator in ("\u2028", "\u2029", "\x0c", "\x85", "\x0b"):
            with self.subTest(separator=repr(separator)):
                text = "a" + separator + "b"
                source = ('robot.sendCmd("led_strip:' + text + '")\n'
                          'report_block("next") robot.sendCmd("move_forward:2")')
                calls, _ = self.execute_with_fake_sdk(source)
                self.assertEqual(calls, [
                    ("led_strip", text), ("report_block", "next"),
                    ("move_forward", 2.0), ("stop",),
                ])

    def test_multiline_literal_contents_are_not_dedented(self):
        source = ('robot.sendCmd("""led_strip:first\n    second\n\tthird""")\n'
                  'robot.sendCmd("stop:")')
        calls, _ = self.execute_with_fake_sdk(source)
        self.assertEqual(calls, [
            ("led_strip", "first\n    second\n\tthird"), ("stop",), ("stop",),
        ])

    def test_empty_led_text_and_python_numeric_underscores_keep_existing_behavior(self):
        calls, _ = self.execute_with_fake_sdk(
            'robot.sendCmd("led_strip:")\nrobot.sendCmd("move_forward:1_0")')
        self.assertEqual(calls, [("led_strip", ""), ("move_forward", 10.0), ("stop",)])

    def test_text_is_not_modified_and_does_not_add_statements(self):
        source = 'robot.sendCmd(\'led_strip:văn: "bản" robot.sendCmd("stop:")\')'
        calls, _ = self.execute_with_fake_sdk(source)
        self.assertEqual(calls, [("led_strip", 'văn: "bản" robot.sendCmd("stop:")'), ("stop",)])

    def test_angle_limits_positive_seconds_and_no_execution_during_conversion(self):
        for value in ("0", "45.5", "90"):
            converter.convert_block_to_python(f'robot.sendCmd("hand_up:{value}")')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "must_not_exist"
            for source in (
                'robot.sendCmd("hand_up:91")', 'robot.sendCmd("hand_up:nan")',
                'robot.sendCmd("move_forward:0")', 'robot.sendCmd("move_backward:inf")',
                'robot.sendCmd("move_forward")', 'robot.sendCmd("unknown:1")',
                f'open({str(path)!r}, "w")', 'for i in range(2):\n report_block("x")',
            ):
                with self.subTest(source=source), self.assertRaises(converter.BlockConvertError):
                    converter.convert_block_to_python(source)
            self.assertFalse(path.exists())

    def test_block_ids_can_be_omitted_but_standalone_markers_are_kept_when_requested(self):
        source = 'report_block("start")\nreport_block("end")'
        self.assertNotIn("robot.report_block", converter.convert_block_to_python(source))
        calls, _ = self.execute_with_fake_sdk(source)
        self.assertEqual(calls, [("report_block", "start"), ("report_block", "end"), ("stop",)])

    def test_custom_command_needs_only_one_spec_registration(self):
        spec = converter.CommandSpec(converter._number(0, 90), 'hand', 'độ, góc tuyệt đối')
        self.assertNotIn('custom_hand', converter.COMMANDS)
        with patch.dict(converter.COMMANDS, {"custom_hand": spec}):
            calls, namespace = self.execute_with_fake_sdk('robot.sendCmd("custom_hand:20")')
            self.assertEqual(converter.COMMAND_RESOURCES['custom_hand'], 'hand')
        self.assertEqual(calls, [("custom_hand", 20.0), ("stop",)])
        self.assertEqual(namespace["REQUIRED_RESOURCES"], ("hand",))

    def test_spec_contains_validation_resource_and_unit_and_is_frozen(self):
        spec = converter.COMMANDS['move_forward']
        self.assertIsInstance(spec, converter.CommandSpec)
        self.assertEqual(spec.resource, 'motor')
        self.assertEqual(spec.unit, 'giây')
        self.assertEqual(spec.validate('0.5', 'move_forward', 1), 0.5)
        with self.assertRaises(FrozenInstanceError):
            spec.resource = 'hand'
        with self.assertRaises(TypeError):
            converter.COMMAND_RESOURCES['move_forward'] = 'hand'

    def test_no_argument_spec_supports_optional_separator(self):
        spec = converter.CommandSpec(converter._none, 'matrix')
        with patch.dict(converter.COMMANDS, {'smile': spec}):
            for source in ('robot.sendCmd("smile")', 'robot.sendCmd("smile:")'):
                calls, namespace = self.execute_with_fake_sdk(source)
                self.assertEqual(calls, [('smile',), ('stop',)])
                self.assertEqual(namespace['REQUIRED_RESOURCES'], ('matrix',))
            with self.assertRaises(converter.BlockConvertError):
                converter.convert_block_to_python('robot.sendCmd("smile:1")')


class HelperApiTests(unittest.TestCase):
    def test_class_and_function_generate_the_same_sdk_program(self):
        source = 'report_block("lift") robot.sendCmd("hand_up:90")'
        generated = converter.ConvertBlockToPython().convert(source)
        self.assertEqual(generated, converter.convert_block_to_python(source, keep_block_ids=True))
        self.assertIn('from robot_sdk import Robot', generated)
        self.assertIn("robot.hand_up(90.0)", generated)
        self.assertNotIn("vehicle_testing.hardware", generated)
        self.assertNotIn("robot.report_block", converter.ConvertBlockToPython().convert(source, keep_block_ids=False))

    def test_convert_file_preserves_unicode_and_does_not_overwrite_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.txt'
            output = Path(directory) / 'nested/program.py'
            source.write_text('robot.sendCmd("led_strip:văn bản")', encoding='utf-8-sig')
            helper = converter.ConvertBlockToPython()
            self.assertEqual(helper.convert_file(source, output), output)
            original = output.read_text(encoding='utf-8')
            self.assertIn('văn bản', original)
            source.write_text('robot.sendCmd("bad:1")', encoding='utf-8')
            with self.assertRaises(ValueError):
                helper.convert_file(source, output)
            self.assertEqual(output.read_text(encoding='utf-8'), original)

    def test_same_input_output_is_rejected_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.txt'
            source = 'robot.sendCmd("hand_up:90")'
            path.write_text(source, encoding='utf-8')
            with self.assertRaises(ValueError):
                converter.ConvertBlockToPython().convert_file(path, path)
            self.assertEqual(path.read_text(encoding='utf-8'), source)

    def test_cli_converts_and_can_drop_block_ids_without_running_generated_code(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.txt'
            source.write_text('report_block("lift") robot.sendCmd("hand_up:90")', encoding='utf-8')
            for flags in ([], ['--drop-block-ids']):
                output = Path(directory) / ('drop.py' if flags else 'keep.py')
                result = subprocess.run(
                    [sys.executable, '-B', '-X', 'utf8', '-m',
                     'vehicle_testing.helpers.ConvertBlockToPython', '--input', str(source),
                     '--output', str(output), *flags],
                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                generated = output.read_text(encoding='utf-8')
                self.assertEqual('robot.report_block' in generated, not flags)
                self.assertIn('robot.hand_up(90.0)', generated)

    def test_helper_can_be_used_without_root_convert_or_robot_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / 'ConvertBlockToPython.py'
            helper.write_text(Path(converter.__file__).read_text(encoding='utf-8'), encoding='utf-8')
            source = Path(directory) / 'source.txt'
            source.write_text('robot.sendCmd("hand_up:90")', encoding='utf-8')
            output = Path(directory) / 'output.py'
            result = subprocess.run(
                [sys.executable, '-I', '-B', '-X', 'utf8', str(helper),
                 '--input', str(source), '--output', str(output)],
                cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('robot.hand_up(90.0)', output.read_text(encoding='utf-8'))


if __name__ == "__main__":
    unittest.main()
