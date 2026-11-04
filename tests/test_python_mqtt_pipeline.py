"""Receive FE commands, convert to a file and run a child with simulated devices."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import types
import unittest
from unittest.mock import Mock, patch


class PythonPipelineTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('vehicle_testing.runtime.python_program')
        self.assertIsNotNone(spec, 'Python receive-convert-run pipeline is missing')
        from vehicle_testing.runtime import python_program
        from vehicle_testing.connections.mqtt.python_receiver import PythonMqttReceiver
        self.runtime = python_program
        self.receiver_class = PythonMqttReceiver

    def client(self):
        client = Mock()
        client.is_connected.return_value = True
        client.publish.return_value = types.SimpleNamespace(rc=0)
        return client

    def message(self, topic, payload, **kwargs):
        return types.SimpleNamespace(topic=topic, payload=payload.encode('utf-8'),
                                     retain=kwargs.get('retain', False), dup=kwargs.get('dup', False))

    def test_upload_saves_original_and_converted_then_child_runs_the_sdk(self):
        source = ('report_block("network-only") robot.sendCmd("move_forward:0.1")\n'
                  'robot.sendCmd("hand_up:30")\nrobot.sendCmd("led_strip:MQTT OK")')
        with tempfile.TemporaryDirectory() as directory:
            program = self.runtime.prepare_program(source, Path(directory))
            self.assertEqual(program.source_path.read_text(encoding='utf-8'), source)
            self.assertIn('robot.hand_up(30.0)', program.path.read_text(encoding='utf-8'))
            events = []
            self.runtime.execute_python_program(program, dry_run=True, stop_event=Event(), notify=events.append)
            self.assertIn('network-only', [e.get('block_id') for e in events])
            self.assertTrue(any('MO PHONG' in e.get('message', '') for e in events))

    def test_upload_does_not_run_and_execute_is_one_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            execute = Mock()
            receiver = self.receiver_class('test-device', program_dir=directory, executor=execute)
            self.addCleanup(receiver.close)
            client = self.client()
            receiver.on_message(client, None, self.message(receiver.topic_code, 'robot.sendCmd("hand_up:90")'))
            execute.assert_not_called()
            receiver.on_message(client, None, self.message(receiver.topic_execute, 'execute'))
            self.assertTrue(receiver.wait_for_execution(3))
            execute.assert_called_once()
            receiver.on_message(client, None, self.message(receiver.topic_execute, 'execute'))
            execute.assert_called_once()

    def test_retained_commands_and_invalid_replacement_never_execute_old_code(self):
        with tempfile.TemporaryDirectory() as directory:
            execute = Mock()
            receiver = self.receiver_class('test-device', program_dir=directory, executor=execute)
            self.addCleanup(receiver.close)
            client = self.client()
            receiver.on_message(client, None, self.message(receiver.topic_code, 'robot.sendCmd("move_forward:1")', retain=True))
            self.assertIsNone(receiver.current_program)
            receiver.on_message(client, None, self.message(receiver.topic_code, 'robot.sendCmd("move_forward:1")'))
            receiver.on_message(client, None, self.message(receiver.topic_execute, 'execute', retain=True))
            execute.assert_not_called()
            receiver.on_message(client, None, self.message(receiver.topic_code, 'import os'))
            self.assertIsNone(receiver.current_program)
            receiver.on_message(client, None, self.message(receiver.topic_execute, 'execute'))
            execute.assert_not_called()

    def test_stop_is_processed_while_worker_is_running_and_new_upload_is_rejected(self):
        started = Event()

        def execute(program, *, stop_event):
            started.set()
            if not stop_event.wait(3):
                raise AssertionError('STOP did not reach worker')

        with tempfile.TemporaryDirectory() as directory:
            receiver = self.receiver_class('test-device', program_dir=directory, executor=execute)
            self.addCleanup(receiver.close)
            client = self.client()
            for index in range(3):
                receiver.on_message(client, None, self.message(
                    receiver.topic_code, f'robot.sendCmd("move_forward:{index + 1}")'))
            files_before_run = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
            receiver.on_message(client, None, self.message(receiver.topic_execute, 'execute'))
            self.assertTrue(started.wait(2))
            receiver.on_message(client, None, self.message(receiver.topic_code, 'robot.sendCmd("move_forward:2")'))
            self.assertIsNone(receiver.current_program)
            self.assertEqual({path.name: path.read_bytes() for path in Path(directory).iterdir()},
                             files_before_run)
            receiver.on_message(client, None, self.message(receiver.topic_stop, 'stop'))
            self.assertTrue(receiver.wait_for_execution(2))

    def test_pre_cancelled_run_does_not_start_a_process(self):
        with tempfile.TemporaryDirectory() as directory:
            program = self.runtime.prepare_program('robot.sendCmd("move_forward:1")', Path(directory))
            stop = Event()
            stop.set()
            from vehicle_testing.runtime.runner import ExecutionCancelled
            with patch.object(self.runtime.subprocess, 'Popen') as launch:
                with self.assertRaises(ExecutionCancelled):
                    self.runtime.execute_python_program(program, dry_run=True, stop_event=stop)
                launch.assert_not_called()

    def test_receiver_runs_directly_from_its_directory_and_an_unrelated_directory(self):
        script = Path(__file__).resolve().parents[1] / 'connections/mqtt/python_receiver.py'
        with tempfile.TemporaryDirectory() as directory:
            for cwd, path in ((script.parent, script.name), (Path(directory), str(script))):
                with self.subTest(cwd=str(cwd)):
                    result = subprocess.run(
                        [sys.executable, '-I', '-B', '-X', 'utf8', path, '--help'],
                        cwd=cwd, capture_output=True, text=True, encoding='utf-8', timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('--broker', result.stdout)
                    self.assertIn('--dry-run', result.stdout)

    def test_child_timeout_is_reported_as_error_instead_of_done(self):
        with tempfile.TemporaryDirectory() as directory:
            program = self.runtime.prepare_program('robot.sendCmd("move_forward:1")', Path(directory))
            # A benign, stalled child fixture exercises the supervisor fallback.
            program.path.write_text('import time\ntime.sleep(10)\n', encoding='utf-8')
            with self.assertRaises(TimeoutError):
                self.runtime.execute_python_program(program, dry_run=True, stop_event=Event(), timeout=0.1)


    def test_cleanup_failure_latches_receiver_and_rejects_another_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            receiver = self.receiver_class('test-device', program_dir=directory)
            self.addCleanup(receiver.close)
            client = self.client()
            receiver._client = client
            program = self.runtime.prepare_program('robot.sendCmd("stop:")', Path(directory))
            program.path.write_text(
                'from robot_sdk import Robot\n'
                'class BrokenMotor:\n'
                '    def close(self):\n'
                '        raise OSError("I2C stop failed")\n'
                'robot = Robot()\nrobot._motor = BrokenMotor()\nrobot.stop()\n', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'SDK'):
                self.runtime.execute_python_program(program, dry_run=True, stop_event=Event(), notify=receiver._notify)
            self.assertTrue(receiver._faulted.is_set())
            receiver.on_message(client, None, self.message(receiver.topic_code, 'robot.sendCmd("move_forward:1")'))
            self.assertIsNone(receiver.current_program)

    def test_real_lift_requires_lowered_start_and_only_one_execution_per_receiver(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self.client()
            denied = self.receiver_class('test-device', program_dir=directory, dry_run=False, executor=Mock())
            self.addCleanup(denied.close)
            source = 'robot.sendCmd("hand_up:90")'
            denied.on_message(client, None, self.message(denied.topic_code, source))
            self.assertIsNone(denied.current_program)
            execute = Mock()
            allowed = self.receiver_class('test-device', program_dir=directory, dry_run=False,
                                          lift_start_lowered=True, executor=execute)
            self.addCleanup(allowed.close)
            allowed.on_message(client, None, self.message(allowed.topic_code, source))
            self.assertIsNotNone(allowed.current_program)
            allowed.on_message(client, None, self.message(allowed.topic_execute, 'execute'))
            self.assertTrue(allowed.wait_for_execution(3))
            execute.assert_called_once()
            allowed.on_message(client, None, self.message(allowed.topic_code, source))
            self.assertIsNone(allowed.current_program)


class SdkTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('vehicle_testing.robot_sdk')
        self.assertIsNotNone(spec, 'robot_sdk is missing')
        from vehicle_testing import robot_sdk
        self.sdk = robot_sdk
        self.sdk.configure(dry_run=True)

    def tearDown(self):
        if hasattr(self, 'sdk'):
            self.sdk.close_all()

    def test_hand_uses_keyword_angle_and_stop_cleans_acquired_devices(self):
        motor, hand = Mock(), Mock()
        with patch.object(self.sdk, '_open_motor', return_value=motor), \
                patch.object(self.sdk, '_open_hand', return_value=hand):
            robot = self.sdk.Robot()
            robot.move_forward(0.2)
            robot.hand_up(90)
            robot.stop()
        hand.hand_up.assert_called_once_with(angle=90)
        motor.move.assert_called_once_with('forward', 0.2, speed=0.25)
        hand.close.assert_called_once()
        motor.close.assert_called_once()

    def test_stop_file_cancels_before_opening_any_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = Path(directory) / 'stop'
            stop.touch()
            self.sdk.configure(dry_run=True, stop_file=stop)
            robot = self.sdk.Robot()
            with patch.object(self.sdk, '_open_motor') as opening:
                with self.assertRaises(self.sdk.RobotStopped):
                    robot.move_forward(1)
                opening.assert_not_called()
