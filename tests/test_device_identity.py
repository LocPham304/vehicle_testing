"""Per-Pi identity setup and routing checks; no GPIO or physical robots."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from vehicle_testing.connections.wifi import websocket_receiver as ws


class DeviceIdentityTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "device_identity.json"

    def require_identity_api(self):
        for name in ("DeviceIdentity", "load_identity", "save_identity"):
            self.assertTrue(callable(getattr(ws, name, None)), f"Missing identity API: {name}")

    def write_config(self, **updates):
        data = {"uuid": "robot-003", "name": "🚗 Robot Gamma"}
        data.update(updates)
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def server_library(self):
        library = Mock()
        library.serve.return_value.__enter__ = Mock(return_value=library.serve.return_value)
        library.serve.return_value.__exit__ = Mock(return_value=False)
        return library

    def run_cli(self, flags):
        error_output = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(error_output):
            try:
                return ws.main(flags)
            except SystemExit as error:
                self.fail(f"Expected CLI success, got exit {error.code}: {error_output.getvalue()}")

    def test_unicode_identity_is_persisted_and_reloaded_without_changing_uuid(self):
        self.require_identity_api()
        identity = ws.DeviceIdentity("robot-003", "🚗 Robot Gamma")
        ws.save_identity(self.path, identity)
        self.assertEqual(ws.load_identity(self.path), identity)
        self.assertEqual(ws.load_identity(self.path), identity)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"uuid": "robot-003", "name": "🚗 Robot Gamma"})

    def test_invalid_identity_does_not_replace_a_valid_assignment(self):
        self.require_identity_api()
        self.write_config()
        before = self.path.read_bytes()
        for device_id, name in (("", "Robot"), ("bad/id", "Robot"), (None, "Robot"),
                                ("x" * 65, "Robot"), ("robot-003", " "),
                                ("robot-003", None), ("robot-003", "x" * 129)):
            with self.subTest(device_id=device_id, name=name), self.assertRaises(ValueError):
                ws.save_identity(self.path, ws.DeviceIdentity(device_id, name))
        self.assertEqual(self.path.read_bytes(), before)

    def test_malformed_or_incomplete_config_is_rejected(self):
        self.require_identity_api()
        for content in ("not-json", "[]", "null", "{}", '{"uuid":"robot-003"}',
                        '{"uuid":"bad/id","name":"Robot"}',
                        '{"uuid":"robot-003","name":" "}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    ws.load_identity(self.path)

    def test_utf8_bom_config_created_on_windows_is_supported(self):
        self.require_identity_api()
        self.path.write_text('{"uuid":"robot-003","name":"Robot Gamma"}', encoding="utf-8-sig")
        self.assertEqual(ws.load_identity(self.path).uuid, "robot-003")

    def test_failed_atomic_replace_keeps_previous_assignment_and_removes_temp_file(self):
        self.require_identity_api()
        self.write_config()
        before = self.path.read_bytes()
        with patch("vehicle_testing.runtime.identity.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                ws.save_identity(self.path, ws.DeviceIdentity("robot-002", "Robot Beta"))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_setup_prompts_once_and_exits_without_loading_server(self):
        with patch("builtins.input", side_effect=["robot-003", "🚗 Robot Gamma"]) as prompt, \
                patch.object(ws, "load_websocket_server") as loader:
            self.assertEqual(self.run_cli(["--setup", "--identity-file", str(self.path)]), 0)
        self.assertEqual(prompt.call_count, 2)
        loader.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"uuid": "robot-003", "name": "🚗 Robot Gamma"})

    def test_setup_accepts_explicit_flags_without_prompting(self):
        with patch("builtins.input") as prompt, patch.object(ws, "load_websocket_server") as loader:
            self.assertEqual(self.run_cli(["--setup", "--identity-file", str(self.path),
                                           "--device-id", "robot-002", "--name", "Robot Beta"]), 0)
        prompt.assert_not_called()
        loader.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["uuid"], "robot-002")

    def test_setup_rejects_invalid_input_without_writing_or_starting_server(self):
        with patch("builtins.input", side_effect=["bad/id", "Robot"]), \
                patch.object(ws, "load_websocket_server") as loader, \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            ws.main(["--setup", "--identity-file", str(self.path)])
        self.assertFalse(self.path.exists())
        loader.assert_not_called()

    def test_startup_loads_saved_identity_and_keeps_dry_run_mode(self):
        self.write_config()
        library = self.server_library()
        with patch.object(ws, "load_websocket_server", return_value=library):
            self.assertEqual(self.run_cli(["--identity-file", str(self.path), "--dry-run"]), 0)
        server = library.serve.call_args.args[0].__self__
        self.assertEqual((server.device_id, server.name), ("robot-003", "🚗 Robot Gamma"))
        self.assertEqual(server.receiver.mode, "dry-run")
        self.assertTrue(server.receiver.session.executor.keywords["dry_run"])

    def test_missing_identity_gives_setup_instruction_before_loading_server(self):
        error_output = StringIO()
        with patch.object(ws, "load_websocket_server") as loader, \
                redirect_stderr(error_output), self.assertRaises(SystemExit):
            ws.main(["--identity-file", str(self.path), "--dry-run"])
        self.assertIn("--setup", error_output.getvalue())
        loader.assert_not_called()

    def test_corrupt_identity_stops_before_loading_server(self):
        self.path.write_text("not-json", encoding="utf-8")
        with patch.object(ws, "load_websocket_server") as loader, \
                redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            ws.main(["--identity-file", str(self.path)])
        loader.assert_not_called()

    def test_explicit_uuid_does_not_inherit_another_robots_saved_name(self):
        self.write_config()
        library = self.server_library()
        with patch.object(ws, "load_websocket_server", return_value=library):
            self.assertEqual(self.run_cli(["--identity-file", str(self.path),
                                           "--device-id", "robot-005"]), 0)
        server = library.serve.call_args.args[0].__self__
        self.assertEqual((server.device_id, server.name), ("robot-005", "Robot robot-005"))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["uuid"], "robot-003")

    def test_name_only_override_keeps_saved_uuid_and_does_not_change_config(self):
        self.write_config()
        before = self.path.read_bytes()
        library = self.server_library()
        with patch.object(ws, "load_websocket_server", return_value=library):
            self.assertEqual(self.run_cli(["--identity-file", str(self.path),
                                           "--name", "Temporary name"]), 0)
        server = library.serve.call_args.args[0].__self__
        self.assertEqual((server.device_id, server.name), ("robot-003", "Temporary name"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_setup_can_reassign_an_existing_config_without_starting_server(self):
        self.write_config()
        with patch.object(ws, "load_websocket_server") as loader:
            self.assertEqual(self.run_cli(["--setup", "--identity-file", str(self.path),
                                           "--device-id", "robot-002", "--name", "Robot Beta"]), 0)
        loader.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"uuid": "robot-002", "name": "Robot Beta"})

    def test_default_identity_is_loaded_from_any_working_directory(self):
        self.assertTrue(getattr(ws, "DEFAULT_IDENTITY_FILE", Path()).is_absolute(),
                        "Default identity path must be absolute")
        self.write_config()
        other_directory = self.directory / "other"
        other_directory.mkdir()
        library = self.server_library()
        previous_directory = Path.cwd()
        try:
            os.chdir(other_directory)
            with patch.object(ws, "DEFAULT_IDENTITY_FILE", self.path), \
                    patch.object(ws, "load_websocket_server", return_value=library):
                self.assertEqual(self.run_cli(["--dry-run"]), 0)
        finally:
            os.chdir(previous_directory)
        self.assertEqual(library.serve.call_args.args[0].__self__.device_id, "robot-003")

    def test_five_saved_identities_only_selected_robot_accepts_upload_and_exec(self):
        self.require_identity_api()
        for index in range(1, 6):
            identity = ws.DeviceIdentity(f"robot-{index:03d}", f"Robot {index}")
            path = self.directory / f"robot-{index}.json"
            ws.save_identity(path, identity)
            saved = ws.load_identity(path)
            server = ws.RobotWebSocketServer(saved.uuid, name=saved.name)
            connection = object()
            try:
                reply = server.handle_message(connection, '{"action":"identify"}')
                self.assertEqual((reply["uuid"], reply["deviceName"]), (saved.uuid, saved.name))
                upload = server.handle_message(connection, json.dumps({
                    "type": "UPLOAD", "uuid": "robot-003",
                    "code": 'report_block("block-test")\nrobot.sendCmd("move_forward:1")'}))
                execute = server.handle_message(connection,
                                                '{"type":"EXEC","uuid":"robot-003","code":""}')
                if index == 3:
                    self.assertEqual(upload["status"], "uploaded")
                    self.assertEqual(execute["status"], "preview")
                else:
                    self.assertIsNone(upload)
                    self.assertIsNone(execute)
                    self.assertIsNone(server.receiver.current_program)
            finally:
                server.close()
