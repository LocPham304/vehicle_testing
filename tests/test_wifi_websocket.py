"""WebSocket capture/UPLOAD tests; never open GPIO or real network sockets."""

from contextlib import redirect_stdout
from io import StringIO
import json
from unittest import TestCase
from unittest.mock import Mock, patch
from threading import Event

from vehicle_testing.connections.wifi import websocket_receiver as ws


CODE = 'report_block("block-1")\nrobot.sendCmd("move_forward:5")\n'


class WebSocketReceiverTests(TestCase):
    def setUp(self):
        self.receiver = ws.WebSocketReceiver("robot-003")
        self.socket = Mock()
        self.receiver.on_open(self.socket)

    def upload(self, **updates):
        payload = {"type": "UPLOAD", "uuid": "robot-003", "code": CODE}
        payload.update(updates)
        return self.receiver.on_message(self.socket, json.dumps(payload))

    def test_upload_parses_real_fe_shape_without_running_or_sending_messages(self):
        self.assertTrue(self.upload()["ok"])
        self.assertEqual(self.receiver.current_program.command_count, 1)
        self.assertEqual(self.receiver.current_program.events[-1].value, 5)
        self.socket.send.assert_not_called()

    def test_utf8_text_is_preserved(self):
        code = 'robot.sendCmd("led_strip:văn bản")\n'
        self.assertTrue(self.upload(code=code)["ok"])
        self.assertEqual(self.receiver.current_program.events[0].value, "văn bản")

    def test_wrong_uuid_does_not_replace_the_pending_preview(self):
        self.upload()
        previous = self.receiver.current_program
        self.assertIsNone(self.upload(uuid="robot-003-extra", code="invalid"))
        self.assertIs(self.receiver.current_program, previous)

    def test_bad_replacement_clears_old_preview(self):
        for code in ("import os", "robot.sendCmd('unknown:1')", None, ""):
            with self.subTest(code=code):
                self.upload()
                self.assertFalse(self.upload(code=code)["ok"])
                self.assertIsNone(self.receiver.current_program)

    def test_unknown_event_is_logged_and_never_treated_as_a_run(self):
        self.upload()
        for kind in ("RUN", "EXECUTE", "exec", "STATUS"):
            with self.subTest(kind=kind), self.assertLogs(ws.logger, level="INFO") as logs:
                result = self.receiver.on_message(self.socket, json.dumps({"type": kind, "uuid": "robot-003"}))
            self.assertFalse(result["ok"])
            self.assertIn(kind, "\n".join(logs.output))
        self.socket.send.assert_not_called()

    def execute(self, receiver=None, **updates):
        payload = {"type": "EXEC", "uuid": "robot-003", "code": ""}
        payload.update(updates)
        return (receiver or self.receiver).on_message(self.socket, json.dumps(payload))

    def test_exec_before_upload_or_duplicate_is_rejected(self):
        self.assertFalse(self.execute()["ok"])
        self.upload()
        self.assertEqual(self.execute()["status"], "preview")
        self.assertFalse(self.execute()["ok"])
        self.socket.send.assert_not_called()

    def test_exec_uses_uploaded_snapshot_and_disconnect_cancels_worker(self):
        started, stopped = Event(), Event()
        received = []

        def execute(program, *, stop_event, reporter):
            received.append(program)
            reporter("ws-block")
            started.set()
            stop_event.wait(2)
            stopped.set()

        receiver = ws.WebSocketReceiver("robot-003", executor=execute)
        self.addCleanup(receiver.close)
        receiver.on_open(self.socket)
        upload = json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE})
        self.assertTrue(receiver.on_message(self.socket, upload)["ok"])
        self.assertFalse(started.is_set())
        self.assertEqual(self.execute(receiver)["status"], "accepted")
        self.assertTrue(started.wait(1))
        self.assertFalse(self.execute(receiver)["ok"])
        self.assertFalse(receiver.on_message(self.socket, upload)["ok"])
        receiver.on_close(self.socket, 1006, "lost")
        self.assertTrue(stopped.wait(1))
        receiver.session.wait(1)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].events[-1].value, 5)
        receiver.on_open(self.socket)
        self.assertFalse(self.execute(receiver)["ok"])

    def test_wrong_uuid_or_nonempty_exec_code_cannot_run_uploaded_program(self):
        self.upload()
        self.assertIsNone(self.execute(uuid="robot-004"))
        self.assertFalse(self.execute(code=CODE)["ok"])
        self.assertEqual(self.execute()["status"], "preview")

    def test_completed_worker_requires_new_upload_before_next_exec(self):
        executor = Mock()
        receiver = ws.WebSocketReceiver("robot-003", executor=executor)
        self.addCleanup(receiver.close)
        receiver.on_open(self.socket)
        upload = json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE})
        for _ in range(2):
            self.assertTrue(receiver.on_message(self.socket, upload)["ok"])
            self.assertTrue(self.execute(receiver)["ok"])
            receiver.session.wait(1)
            self.assertFalse(self.execute(receiver)["ok"])
        self.assertEqual(executor.call_count, 2)

    def test_bad_frames_do_not_crash_the_listener(self):
        for payload in ("", "not-json", "null", "[]", "42", b"binary", '{"type":1}',
                        '{"uuid":"robot-003","type":[]}'):
            with self.subTest(payload=payload):
                result = self.receiver.on_message(self.socket, payload)
                self.assertTrue(result is None or not result["ok"])
        self.assertTrue(self.upload()["ok"])

    def test_large_message_is_rejected_and_log_is_bounded(self):
        message = "x" * (ws.MAX_MESSAGE_BYTES + 1)
        with self.assertLogs(ws.logger, level="INFO") as logs:
            self.assertFalse(self.receiver.on_message(self.socket, message)["ok"])
        self.assertLess(len("\n".join(logs.output)), 6000)

    def test_disconnect_error_and_reconnect_clear_old_preview(self):
        self.upload()
        self.receiver.on_close(self.socket, 1000, "closed")
        self.assertIsNone(self.receiver.current_program)
        self.assertFalse(self.upload()["ok"])
        self.receiver.on_open(self.socket)
        self.assertTrue(self.upload()["ok"])
        self.receiver.on_error(self.socket, OSError("connection lost"))
        self.assertIsNone(self.receiver.current_program)

    def test_invalid_device_ids_are_rejected(self):
        for device_id in ("", "robot/003", None, "x" * 65):
            with self.subTest(device_id=device_id), self.assertRaises(ValueError):
                ws.WebSocketReceiver(device_id)


class WebSocketCliTests(TestCase):
    def test_default_endpoint_callbacks_and_cleanup(self):
        library = Mock()
        with patch.object(ws, "load_websocket", return_value=library), redirect_stdout(StringIO()):
            result = ws.main(["--device-id", "robot-003", "--once"])
        self.assertEqual(result, 0)
        call = library.WebSocketApp.call_args
        self.assertEqual(call.args, ("ws://192.168.1.93:5000/stem",))
        self.assertTrue(all(callable(call.kwargs[name]) for name in ("on_open", "on_message", "on_error", "on_close")))
        library.WebSocketApp.return_value.run_forever.assert_called_once()
        library.WebSocketApp.return_value.close.assert_called_once()

    def test_invalid_endpoint_rejected_before_import_or_connection(self):
        for url in ("http://example.com/stem", "ws://", "ws://host:invalid/stem", "ws://host/stem#fragment"):
            with self.subTest(url=url), patch.object(ws, "load_websocket") as loader, \
                    patch("sys.stderr", new=StringIO()), self.assertRaises(SystemExit):
                ws.main(["--device-id", "robot-003", "--url", url, "--once"])
            loader.assert_not_called()

    def test_interrupt_closes_socket_and_returns_130(self):
        library = Mock()
        library.WebSocketApp.return_value.run_forever.side_effect = KeyboardInterrupt
        with patch.object(ws, "load_websocket", return_value=library), redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003", "--once"]), 130)
        library.WebSocketApp.return_value.close.assert_called_once()

    def test_interrupt_swallowed_by_websocket_19_does_not_reconnect(self):
        library = Mock()

        def swallow_interrupt(**kwargs):
            callbacks = library.WebSocketApp.call_args.kwargs
            callbacks["on_error"](library.WebSocketApp.return_value, KeyboardInterrupt())
            callbacks["on_close"](library.WebSocketApp.return_value, None, None)
            return False  # websocket-client 1.9 can return instead of propagating Ctrl+C.

        library.WebSocketApp.return_value.run_forever.side_effect = swallow_interrupt
        with patch.object(ws, "load_websocket", return_value=library), \
                patch.object(ws, "Event") as retry, redirect_stdout(StringIO()):
            retry.return_value.wait.side_effect = AssertionError("Ctrl+C must exit before reconnect")
            self.assertEqual(ws.main(["--device-id", "robot-003"]), 130)
        retry.return_value.wait.assert_not_called()
        self.assertEqual(library.WebSocketApp.call_count, 1)
        library.WebSocketApp.return_value.close.assert_called_once()

    def test_missing_dependency_reports_install_command(self):
        with patch.object(ws, "load_websocket", side_effect=RuntimeError("requirements-wifi.txt")), \
                redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003", "--once"]), 1)

    def test_dry_run_executes_fe_script_through_the_shared_runner(self):
        library = Mock()

        def serve(**kwargs):
            callbacks = library.WebSocketApp.call_args.kwargs
            connection = library.WebSocketApp.return_value
            callbacks["on_open"](connection)
            callbacks["on_message"](connection, json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE}))
            self.assertEqual(callbacks["on_message"](connection, '{"type":"EXEC","uuid":"robot-003","code":""}')["status"], "accepted")
            callbacks["on_message"].__self__.session.wait(1)

        library.WebSocketApp.return_value.run_forever.side_effect = serve
        with patch.object(ws, "load_websocket", return_value=library), \
                self.assertLogs("vehicle_testing.runtime.runner", level="INFO") as logs, redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003", "--dry-run", "--once"]), 0)
        self.assertIn("move_forward:5", "\n".join(logs.output))

    def test_real_mode_selects_real_runner_only_with_run_flag(self):
        library = Mock()
        with patch.object(ws, "load_websocket", return_value=library), \
                patch.object(ws, "WebSocketReceiver") as receiver, redirect_stdout(StringIO()):
            receiver.return_value.had_error = False
            receiver.return_value.interrupted = False
            self.assertEqual(ws.main(["--device-id", "robot-003", "--run", "--once"]), 0)
        self.assertFalse(receiver.call_args.kwargs["executor"].keywords["dry_run"])
