"""MQTT callbacks stay responsive while one scenario owns the hardware."""

from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from vehicle_testing import scratch_receiver as receiver_module
from vehicle_testing import scratch_runner as runner
from vehicle_testing.controller import MotorController
from vehicle_testing.config import MOTORS
from vehicle_testing.scratch_parser import parse_program
from vehicle_testing.tests.test_scratch_receiver import Client


class MQTTExecutionTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch.object(receiver_module, "logger")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)
        config_patch = patch.object(receiver_module.logging, "basicConfig")
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.started, self.release = Event(), Event()
        self.calls = []

        def execute(program, *, stop_event):
            self.calls.append((program, stop_event))
            self.started.set()
            if not self.release.wait(5):
                raise AssertionError("test failed to release worker")

        self.receiver = receiver_module.ScratchReceiver("robot-001", executor=execute)
        self.client = Client()
        self.addCleanup(self.receiver.close)
        self.addCleanup(self.release.set)

    def deliver(self, suffix, payload, *, retained=False, duplicate=False):
        self.receiver.on_message(self.client, None, SimpleNamespace(
            topic=f"device/robot-001/{suffix}", payload=payload.encode("utf-8"),
            retain=retained, dup=duplicate, qos=1))

    def start(self):
        self.deliver("code", 'report_block("a")\nrobot.sendCmd("move_forward:2")')
        self.deliver("execute", "execute")
        self.assertTrue(self.started.wait(2), "execute did not start")

    def statuses(self):
        return [payload for topic, payload, _ in self.client.published if topic.endswith("/status")]

    def test_upload_only_caches_then_execute_runs_received_program_in_worker(self):
        self.deliver("code", 'report_block("uploaded")\nrobot.sendCmd("turn_right:15")')
        program = self.receiver.current_program
        self.assertEqual(self.calls, [])
        self.deliver("execute", "execute")
        self.assertTrue(self.started.wait(2))
        self.assertTrue(self.receiver.busy)
        self.assertIs(self.calls[0][0], program)
        self.assertEqual(self.calls[0][0].events[1].command, "turn_right")
        self.release.set()
        self.assertTrue(self.receiver.wait_for_execution(2))
        self.assertFalse(self.receiver.busy)
        self.assertEqual(self.statuses(), ["executing", "done"])

    def test_busy_execute_rejected_while_upload_keeps_current_run_snapshot(self):
        self.start()
        original = self.calls[0][0]
        self.deliver("code", 'robot.sendCmd("led_strip:NEW")')
        replacement = self.receiver.current_program
        self.deliver("execute", "execute")
        self.assertEqual(len(self.calls), 1)
        self.assertIsNot(original, replacement)
        self.assertEqual(original.events[1].command, "move_forward")
        self.release.set()
        self.assertTrue(self.receiver.wait_for_execution(2))
        self.deliver("execute", "execute")
        self.assertTrue(self.receiver.wait_for_execution(2))
        self.assertIs(self.calls[1][0], replacement)

    def test_bad_replacement_or_unknown_font_clears_cache(self):
        for source in ('import os', 'robot.sendCmd("led_strip:🙂")'):
            self.deliver("code", 'robot.sendCmd("move_forward:2")')
            self.deliver("code", source)
            self.deliver("execute", "execute")
            self.assertIsNone(self.receiver.current_program)
            self.assertEqual(self.calls, [])

    def test_retained_and_duplicate_execute_do_not_start_hardware(self):
        self.deliver("code", 'robot.sendCmd("move_forward:2")')
        self.deliver("execute", "execute", retained=True)
        self.deliver("execute", "execute", duplicate=True)
        self.assertEqual(self.calls, [])

    def test_heartbeat_is_executing_until_worker_finishes(self):
        self.start()
        self.receiver.publish_heartbeat(self.client)
        self.assertEqual(self.statuses(), ["executing", "executing"])
        self.release.set()
        self.assertTrue(self.receiver.wait_for_execution(2))
        self.receiver.publish_heartbeat(self.client)
        self.assertEqual(self.statuses()[-2:], ["done", "idle"])

    def test_stop_cancels_active_run_and_reports_stopped(self):
        self.start()
        self.deliver("stop", "stop")
        self.assertTrue(self.calls[0][1].is_set())
        self.release.set()
        self.assertTrue(self.receiver.wait_for_execution(2))
        self.assertEqual(self.statuses()[-1], "stopped")

    def test_bad_retained_or_duplicate_stop_is_ignored(self):
        self.start()
        self.deliver("stop", "stop", retained=True)
        self.deliver("stop", "stop", duplicate=True)
        self.deliver("stop", "bad")
        self.assertFalse(self.calls[0][1].is_set())

    def test_disconnect_cancels_and_invalidates_program(self):
        self.start()
        self.receiver.on_disconnect(self.client, None, None, SimpleNamespace(is_failure=True), None)
        self.assertTrue(self.calls[0][1].is_set())
        self.assertIsNone(self.receiver.current_program)

    def test_close_cancels_and_waits_for_cleanup_then_refuses_new_work(self):
        cleaned = Event()

        def execute(program, *, stop_event):
            self.started.set()
            stop_event.wait(5)
            cleaned.set()

        self.receiver.executor = execute
        self.start()
        self.receiver.close()
        self.assertTrue(cleaned.is_set())
        self.assertFalse(self.receiver.busy)
        self.deliver("code", 'robot.sendCmd("move_forward:2")')
        self.deliver("execute", "execute")
        self.assertIsNone(self.receiver.current_program)

    def test_worker_error_reports_error_and_receiver_accepts_next_run(self):
        self.receiver.executor = Mock(side_effect=OSError("I2C"))
        self.deliver("code", 'robot.sendCmd("move_forward:2")')
        self.deliver("execute", "execute")
        self.assertTrue(self.receiver.wait_for_execution(2))
        self.assertEqual(self.statuses(), ["executing", "error"])
        self.receiver.executor = Mock()
        self.deliver("execute", "execute")
        self.assertTrue(self.receiver.wait_for_execution(2))
        self.assertEqual(self.statuses()[-2:], ["executing", "done"])

    def test_execution_mode_subscribes_to_stop_topic_too(self):
        self.receiver.on_connect(self.client, None, None, SimpleNamespace(is_failure=False), None)
        self.assertEqual(self.client.subscriptions[0], [
            ("device/robot-001/code", 1), ("device/robot-001/execute", 1), ("device/robot-001/stop", 1)])

    def test_main_run_flag_wires_executor_and_stops_worker_before_mqtt(self):
        receiver = Mock()
        order = Mock()
        order.attach_mock(receiver.close, "worker_close")
        order.attach_mock(Mock(wraps=self.client.disconnect), "disconnect")
        with patch.object(receiver_module, "ScratchReceiver", return_value=receiver) as factory, \
                patch.object(receiver_module, "create_client", return_value=self.client), \
                patch.object(self.client, "disconnect", order.disconnect), \
                patch.object(receiver_module.time, "sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(receiver_module.main(["--broker", "test", "--device-id", "robot-001", "--run"]), 130)
        self.assertIs(factory.call_args.kwargs["executor"].func, runner.execute_program)
        self.assertFalse(factory.call_args.kwargs["executor"].keywords["dry_run"])
        self.assertEqual([c[0] for c in order.mock_calls], ["worker_close", "disconnect"])

    def test_main_worker_close_error_still_disconnects_mqtt(self):
        receiver = Mock()
        receiver.close.side_effect = OSError("worker cleanup")
        with patch.object(receiver_module, "ScratchReceiver", return_value=receiver), \
                patch.object(receiver_module, "create_client", return_value=self.client), \
                patch.object(receiver_module.time, "sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(receiver_module.main(["--broker", "test", "--device-id", "robot-001", "--run"]), 1)
        self.assertTrue(self.client.disconnected and self.client.stopped)


class CancellableRunnerTests(unittest.TestCase):
    def test_cancellation_interrupts_long_move_stops_outputs_and_skips_next_step(self):
        output, matrix = Mock(), Mock()
        moving, cancel = Event(), Event()
        duties, errors = {}, []

        def write(channel, duty):
            duties[channel] = duty
            if duty and channel in {pins.pwm for pins in MOTORS.values()}:
                moving.set()

        output.set_duty.side_effect = write

        def run():
            try:
                runner.execute_program(parse_program(
                    'robot.sendCmd("move_forward:600")\nrobot.sendCmd("led_strip:HELLO")'), stop_event=cancel)
            except runner.ExecutionCancelled as error:
                errors.append(error)

        with patch.object(runner, "open_motor", side_effect=lambda **kw: MotorController(output, sleeper=kw["sleeper"])), \
                patch.object(runner, "MatrixTextDisplay", return_value=matrix):
            worker = Thread(target=run)
            worker.start()
            try:
                self.assertTrue(moving.wait(2))
            finally:
                cancel.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertTrue(duties and all(value == 0 for value in duties.values()))
        output.close.assert_called_once_with()
        matrix.show_text.assert_not_called()
        matrix.close.assert_called_once_with()

    def test_cancel_before_start_opens_no_hardware(self):
        cancel = Event()
        cancel.set()
        with patch.object(runner, "open_motor") as motor, patch.object(runner, "MatrixTextDisplay") as matrix:
            with self.assertRaises(runner.ExecutionCancelled):
                runner.execute_program(parse_program('robot.sendCmd("move_forward:2")'), stop_event=cancel)
        motor.assert_not_called()
        matrix.assert_not_called()

    def test_cancellation_interrupts_matrix_frame_wait_and_cleans_up(self):
        cancel = Event()
        gpio, link = Mock(), Mock()
        link.write_frame.side_effect = lambda frame: cancel.set()
        display = runner.MatrixTextDisplay(gpio=gpio, link_factory=Mock(return_value=link),
                                           sleeper=runner.cancellable_sleep(cancel))
        with patch.object(runner, "MatrixTextDisplay", return_value=display):
            with self.assertRaises(runner.ExecutionCancelled):
                runner.execute_program(parse_program('robot.sendCmd("led_strip:HELLO")'), stop_event=cancel)
        link.send.assert_called_with([0x80])
        gpio.cleanup.assert_called_once_with([7, 5])


if __name__ == "__main__":
    unittest.main()
