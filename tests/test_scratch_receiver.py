"""MQTT receive/preview behavior with a local in-memory client boundary."""

import importlib
import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "vehicle_testing/examples/scratch_sample.txt"


class Client:
    def __init__(self):
        self.subscriptions = []
        self.published = []
        self.connected = True
        self.connection = None
        self.started = self.stopped = self.disconnected = False

    def subscribe(self, topics):
        self.subscriptions.append(topics)
        return 0, 1

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload, **kwargs):
        self.published.append((topic, payload, kwargs))
        return SimpleNamespace(rc=0)

    def connect_async(self, host, port, keepalive):
        self.connection = (host, port, keepalive)

    def loop_start(self):
        self.started = True

    def disconnect(self):
        self.disconnected = True

    def loop_stop(self):
        self.stopped = True


class EntryTests(unittest.TestCase):
    def test_offline_preview_direct_and_module_work_without_hardware(self):
        for arguments, cwd in ((["scratch_receiver.py", "--file", str(SAMPLE)], ROOT / "vehicle_testing"),
                               (["-m", "vehicle_testing.scratch_receiver", "--file", str(SAMPLE)], ROOT)):
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, "-B", *arguments], cwd=cwd,
                                        capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("7 block", result.stdout)
                self.assertIn("6 lenh", result.stdout)
                self.assertIn("2 giay", result.stdout)

    def test_receiver_import_does_not_load_mqtt_or_hardware(self):
        code = ("import sys; import vehicle_testing.scratch_receiver; "
                "assert not any(n in sys.modules for n in "
                "('RPi.GPIO','board','serial','paho','vehicle_testing.controller','vehicle_testing.hand'))")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_and_missing_network_device_id(self):
        result = subprocess.run([sys.executable, "-B", "vehicle_testing/scratch_receiver.py", "--help"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--broker", result.stdout)
        result = subprocess.run([sys.executable, "-B", "vehicle_testing/scratch_receiver.py", "--broker", "localhost"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.scratch_receiver")
        self.receiver = self.module.ScratchReceiver("robot-001")
        self.client = Client()

    def deliver(self, suffix, payload, retained=False):
        message = SimpleNamespace(topic=f"device/robot-001/{suffix}",
                                  payload=payload.encode("utf-8") if isinstance(payload, str) else payload,
                                  qos=1, retain=retained)
        self.receiver.on_message(self.client, None, message)

    def upload_sample(self):
        self.deliver("code", SAMPLE.read_text(encoding="utf-8"))

    def test_upload_parses_immediately_and_execute_previews_same_program(self):
        with self.assertLogs(self.module.logger, level="INFO") as logs:
            self.upload_sample()
            program = self.receiver.current_program
            self.deliver("execute", "execute")
        self.assertEqual(program.command_count, 6)
        self.assertIs(self.receiver.current_program, program)
        self.assertIn("PREVIEW EXECUTE", "\n".join(logs.output))
        self.assertIn("văn bản", "\n".join(logs.output))
        self.assertEqual(self.client.published, [])

    def test_execute_without_program_is_reported(self):
        with self.assertLogs(self.module.logger, level="WARNING") as logs:
            self.deliver("execute", "execute")
        self.assertIn("chua co", "\n".join(logs.output))
        self.assertIsNone(self.receiver.current_program)

    def test_invalid_replacement_upload_clears_previous_program(self):
        for invalid in (b'\xff', '', 'import os', 'robot.sendCmd("unknown:1")'):
            with self.subTest(invalid=invalid):
                self.upload_sample()
                with self.assertLogs(self.module.logger, level="WARNING") as logs:
                    self.deliver("code", invalid)
                    self.deliver("execute", "execute")
                self.assertIsNone(self.receiver.current_program)
                self.assertNotIn("PREVIEW EXECUTE", "\n".join(logs.output))

    def test_bad_or_retained_execute_does_not_preview_or_destroy_valid_program(self):
        self.upload_sample()
        program = self.receiver.current_program
        for payload, retained in (("run", False), (b'\xff', False), ("execute", True)):
            with self.subTest(payload=payload, retained=retained), self.assertLogs(self.module.logger, level="WARNING") as logs:
                self.deliver("execute", payload, retained)
                self.assertNotIn("PREVIEW EXECUTE", "\n".join(logs.output))
                self.assertIs(self.receiver.current_program, program)

    def test_topics_for_other_devices_are_ignored(self):
        self.upload_sample()
        program = self.receiver.current_program
        self.receiver.on_message(self.client, None, SimpleNamespace(topic="device/other/code", payload=b"bad"))
        self.assertIs(self.receiver.current_program, program)

    def test_heartbeat_never_claims_execution_or_completion(self):
        self.upload_sample()
        self.deliver("execute", "execute")
        self.receiver.publish_heartbeat(self.client)
        self.assertEqual(self.client.published, [("device/robot-001/status", "idle", {"qos": 1, "retain": False})])
        self.client.connected = False
        self.receiver.publish_heartbeat(self.client)
        self.assertEqual(len(self.client.published), 1)

    def test_connect_subscribes_to_device_topics_and_disconnect_invalidates_program(self):
        reason = SimpleNamespace(is_failure=False)
        self.receiver.on_connect(self.client, None, None, reason, None)
        self.assertEqual(self.client.subscriptions, [[("device/robot-001/code", 1), ("device/robot-001/execute", 1)]])
        self.upload_sample()
        self.receiver.on_disconnect(self.client, None, None, reason, None)
        self.assertIsNone(self.receiver.current_program)

    def test_device_id_cannot_redirect_subscription_to_wildcards(self):
        for device_id in ("", "x/y", "a+", "#", " x", "a\n"):
            with self.subTest(device_id=device_id), self.assertRaises(ValueError):
                self.module.ScratchReceiver(device_id)

    def test_network_main_publishes_idle_and_closes_on_ctrl_c(self):
        with patch.object(self.module, "create_client", return_value=self.client), \
                patch.object(self.module.time, "sleep", side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.main(["--broker", "test-broker", "--device-id", "robot-001"]), 130)
        self.assertEqual(self.client.connection, ("test-broker", 1883, 30))
        self.assertEqual(self.client.published, [("device/robot-001/status", "idle", {"qos": 1, "retain": False})])
        self.assertTrue(self.client.disconnected and self.client.stopped)

    def test_network_setup_failure_still_stops_client(self):
        with patch.object(self.module, "create_client", return_value=self.client), \
                patch.object(self.client, "connect_async", side_effect=OSError("cannot connect")), \
                self.assertLogs(self.module.logger, level="ERROR"), redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.main(["--broker", "test-broker", "--device-id", "robot-001"]), 1)
        self.assertTrue(self.client.disconnected and self.client.stopped)

    def test_disconnect_failure_does_not_skip_loop_stop(self):
        with patch.object(self.module, "create_client", return_value=self.client), \
                patch.object(self.module.time, "sleep", side_effect=KeyboardInterrupt), \
                patch.object(self.client, "disconnect", side_effect=OSError("disconnect failed")), \
                self.assertLogs(self.module.logger, level="ERROR"), redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.main(["--broker", "test-broker", "--device-id", "robot-001"]), 1)
        self.assertTrue(self.client.stopped)


if __name__ == "__main__":
    unittest.main()
