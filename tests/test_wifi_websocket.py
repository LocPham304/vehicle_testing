"""WebSocket capture/UPLOAD tests; never open GPIO or real network sockets."""

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
from threading import Event, Thread
from types import SimpleNamespace
from http import HTTPStatus

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


class FakeConnection:
    def __init__(self, messages=()):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    def __iter__(self):
        return self.messages

    def send(self, data):
        self.sent.append(json.loads(data))

    def close(self, **kwargs):
        self.closed = True


class ClosedSocketConnection(FakeConnection):
    close_code = 1000
    close_reason = "Test complete"

    @property
    def remote_address(self):
        if self.closed:
            raise OSError(9, "Bad file descriptor")
        return ("192.168.1.10", 56110)

    def __iter__(self):
        try:
            yield from self.messages
        finally:
            self.closed = True


class WebSocketServerTests(TestCase):
    def setUp(self):
        self.server = ws.RobotWebSocketServer("robot-003", name="Robot Gamma")
        self.addCleanup(self.server.close)

    def test_identify_text_and_json_return_uuid_name_without_touching_hardware(self):
        for message in ("identify", '{"type":"identify"}', '{"type":"IDENTIFY"}', '{"action":"identify"}'):
            with self.subTest(message=message):
                connection = FakeConnection([message])
                self.server.handle_connection(connection)
                self.assertEqual(connection.sent, [{"action": "identify_response", "uuid": "robot-003", "deviceName": "Robot Gamma"}])
                self.assertIsNone(self.server.owner)
                self.assertIsNone(self.server.receiver.current_program)

    def test_identify_with_explicit_wrong_uuid_does_not_reply(self):
        connection = FakeConnection(['{"action":"identify","uuid":"robot-001"}'])
        self.server.handle_connection(connection)
        self.assertEqual(connection.sent, [])
        self.assertIsNone(self.server.owner)

    def test_identify_with_matching_uuid_returns_this_robot(self):
        connection = FakeConnection(['{"action":"identify","uuid":"robot-003"}'])
        self.server.handle_connection(connection)
        self.assertEqual(connection.sent, [{"action": "identify_response", "uuid": "robot-003",
                                           "deviceName": "Robot Gamma"}])

    def test_discovery_socket_cannot_clear_another_socket_upload(self):
        probe = FakeConnection(['{"type":"identify"}'])

        def messages():
            yield json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE})
            self.server.handle_connection(probe)
            yield '{"type":"EXEC","uuid":"robot-003","code":""}'

        owner = FakeConnection(messages())
        self.server.handle_connection(owner)
        self.assertEqual([reply["status"] for reply in owner.sent], ["uploaded", "preview"])
        self.assertEqual(probe.sent[0]["uuid"], "robot-003")

    def test_other_client_cannot_replace_or_execute_current_upload(self):
        other = FakeConnection([json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE}),
                                '{"type":"EXEC","uuid":"robot-003","code":""}'])

        def messages():
            yield json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE})
            self.server.handle_connection(other)
            yield '{"type":"EXEC","uuid":"robot-003","code":""}'

        owner = FakeConnection(messages())
        self.server.handle_connection(owner)
        self.assertTrue(all(not reply["ok"] for reply in other.sent))
        self.assertEqual(owner.sent[-1]["status"], "preview")

    def test_disconnect_clears_upload_before_another_client_exec(self):
        owner = FakeConnection([json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE})])
        self.server.handle_connection(owner)
        other = FakeConnection(['{"type":"EXEC","uuid":"robot-003","code":""}'])
        self.server.handle_connection(other)
        self.assertFalse(other.sent[-1]["ok"])
        self.assertIsNone(self.server.receiver.current_program)

    def test_closed_socket_logging_preserves_address_and_releases_owner(self):
        upload = json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE})
        connection = ClosedSocketConnection([upload])
        error = None
        with self.assertLogs(ws.logger, level="INFO") as logs:
            try:
                self.server.handle_connection(connection)
            except OSError as caught:
                error = caught
        self.assertIsNone(error, "Reading the closed socket must not interrupt cleanup")
        self.assertTrue(connection.sent[0]["ok"])
        self.assertIsNone(self.server.owner)
        self.assertIsNone(self.server.receiver.current_program)
        self.assertNotIn(connection, self.server._connections)
        self.assertIn("WS CLIENT CLOSED: ('192.168.1.10', 56110) code=1000 reason='Test complete'",
                      "\n".join(logs.output))

    def test_raw_message_log_tolerates_socket_closed_by_receive_thread(self):
        connection = ClosedSocketConnection()
        connection.closed = True
        result = None
        error = None
        try:
            result = self.server.handle_message(connection, '{"action":"identify"}')
        except OSError as caught:
            error = caught
        self.assertIsNone(error, "Diagnostic logging must not prevent message handling")
        self.assertEqual(result, {"action": "identify_response", "uuid": "robot-003",
                                  "deviceName": "Robot Gamma"})

    def test_wrong_uuid_does_not_claim_control_and_bad_json_returns_error(self):
        connection = FakeConnection(['{"type":"UPLOAD","uuid":"robot-004","code":"bad"}', "invalid", "[]", b"binary"])
        self.server.handle_connection(connection)
        self.assertIsNone(self.server.owner)
        self.assertEqual(len(connection.sent), 3)
        self.assertTrue(all(not reply["ok"] for reply in connection.sent))

    def test_websocket_paths_allow_stem_and_root_discovery(self):
        connection = Mock()
        for path in ("/stem", "/stem?probe=1", "/"):
            self.assertIsNone(self.server.process_request(connection, SimpleNamespace(path=path)))
        self.server.process_request(connection, SimpleNamespace(path="/other"))
        self.assertEqual(connection.respond.call_args.args[0], HTTPStatus.NOT_FOUND)

    def test_shutdown_closes_connected_clients(self):
        connection = FakeConnection()

        def messages():
            self.server.close()
            yield "identify"

        connection.messages = messages()
        self.server.handle_connection(connection)
        self.assertTrue(connection.closed)


class WebSocketCliTests(TestCase):
    def server_library(self):
        library = Mock()
        library.serve.return_value.__enter__ = Mock(return_value=library.serve.return_value)
        library.serve.return_value.__exit__ = Mock(return_value=False)
        return library

    def test_default_is_a_server_bound_to_all_pi_interfaces(self):
        library = self.server_library()
        with patch.object(ws, "load_websocket_server", return_value=library), redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003", "--name", "Robot Gamma"]), 0)
        call = library.serve.call_args
        self.assertEqual(call.args[1:], ("0.0.0.0", 50000))
        self.assertIsNone(call.args[0].__self__.receiver.session.executor)
        self.assertEqual(call.kwargs["max_size"], ws.MAX_MESSAGE_BYTES)
        library.serve.return_value.serve_forever.assert_called_once()

    def test_invalid_options_rejected_before_loading_library(self):
        for flags in (["--port", "0"], ["--port", "65536"], ["--device-id", "bad/id"], ["--name", " "]):
            with self.subTest(flags=flags), patch.object(ws, "load_websocket_server") as loader, \
                    patch("sys.stderr", new=StringIO()), self.assertRaises(SystemExit):
                ws.main(["--device-id", "robot-003", *flags])
            loader.assert_not_called()

    def test_interrupt_stops_server_without_reconnect(self):
        library = self.server_library()
        library.serve.return_value.serve_forever.side_effect = KeyboardInterrupt
        with patch.object(ws, "load_websocket_server", return_value=library), redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003"]), 130)
        self.assertEqual(library.serve.call_count, 1)
        self.assertTrue(library.serve.call_args.args[0].__self__._closed)

    def test_missing_dependency_or_port_busy_returns_clear_error(self):
        with patch.object(ws, "load_websocket_server", side_effect=RuntimeError("requirements-wifi.txt")), redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003"]), 1)
        library = self.server_library()
        library.serve.side_effect = OSError("port busy")
        with patch.object(ws, "load_websocket_server", return_value=library), redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003"]), 1)

    def test_dry_run_still_executes_confirmed_fe_payload_via_shared_runner(self):
        library = self.server_library()
        def serve():
            connection = FakeConnection(["identify", json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE}),
                                         '{"type":"EXEC","uuid":"robot-003","code":""}'])
            handler = library.serve.call_args.args[0]
            original_send = connection.send
            def send(data):
                original_send(data)
                if connection.sent[-1].get("status") == "accepted":
                    handler.__self__.receiver.session.wait(1)
            connection.send = send
            handler(connection)
            self.assertEqual(connection.sent[0]["uuid"], "robot-003")
        library.serve.return_value.serve_forever.side_effect = serve
        with patch.object(ws, "load_websocket_server", return_value=library), \
                self.assertLogs("vehicle_testing.runtime.runner", level="INFO") as logs, redirect_stdout(StringIO()):
            self.assertEqual(ws.main(["--device-id", "robot-003", "--dry-run"]), 0)
        self.assertIn("move_forward:5", "\n".join(logs.output))


@skipUnless(os.environ.get("RUN_WEBSOCKET_INTEGRATION") == "1",
            "Set RUN_WEBSOCKET_INTEGRATION=1 with websockets installed for loopback checks")
class WebSocketLoopbackTests(TestCase):
    def setUp(self):
        from websockets.sync.server import serve
        from websockets.sync.client import connect
        self.connect = connect
        self.controller = ws.RobotWebSocketServer("robot-003", name="Robot Gamma")
        self.server = serve(self.controller.handle_connection, "127.0.0.1", 0,
                            process_request=self.controller.process_request,
                            max_size=ws.MAX_MESSAGE_BYTES, close_timeout=1)
        self.uri = f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}/stem"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        try:
            self.controller.close()
        finally:
            self.server.shutdown()
            self.thread.join(2)

    def open(self, uri=None):
        return self.connect(uri or self.uri, proxy=None, open_timeout=2, close_timeout=1)

    def test_real_identify_frames_on_stem_and_root(self):
        for uri in (self.uri, self.uri.removesuffix("stem")):
            with self.subTest(uri=uri), self.open(uri) as client:
                for message in ('{"action":"identify"}', "identify", '{"type":"identify"}'):
                    client.send(message)
                    self.assertEqual(json.loads(client.recv(timeout=2)),
                                     {"action": "identify_response", "uuid": "robot-003", "deviceName": "Robot Gamma"})

    def test_helper_tcp_probe_then_websocket_identify_returns_discovery_row(self):
        import socket
        address = self.server.socket.getsockname()
        # The Windows Helper first checks TCP, then identifies over WebSocket.
        with socket.create_connection(address, timeout=2):
            pass
        with self.open() as client:
            client.send('{"action":"identify"}')
            reply = json.loads(client.recv(timeout=2))
        self.assertEqual(reply["action"], "identify_response")
        row = {"uuid": reply["uuid"], "ip": address[0], "deviceName": reply["deviceName"]}
        self.assertEqual(row, {"uuid": "robot-003", "ip": "127.0.0.1", "deviceName": "Robot Gamma"})
        self.assertIsNone(self.controller.owner)

    def test_real_upload_exec_and_discovery_on_separate_connections(self):
        with self.open() as client:
            client.send(json.dumps({"type": "UPLOAD", "uuid": "robot-003", "code": CODE}))
            self.assertEqual(json.loads(client.recv(timeout=2))["status"], "uploaded")
            with self.open() as probe:
                probe.send("identify")
                self.assertEqual(json.loads(probe.recv(timeout=2))["uuid"], "robot-003")
            client.send('{"type":"EXEC","uuid":"robot-003","code":""}')
            self.assertEqual(json.loads(client.recv(timeout=2))["status"], "preview")
            client.send('{"type":"EXEC","uuid":"robot-003","code":""}')
            self.assertFalse(json.loads(client.recv(timeout=2))["ok"])

    def test_real_handshake_rejects_unknown_path(self):
        from websockets.exceptions import InvalidStatus
        with self.assertRaises(InvalidStatus) as error:
            with self.open(self.uri.replace("/stem", "/wrong")):
                self.fail("Wrong endpoint must not complete the WebSocket handshake")
        self.assertEqual(error.exception.response.status_code, 404)
