import json
from threading import Event
import unittest
from unittest.mock import Mock

from vehicle_testing.runtime.session import RobotSession
from vehicle_testing.connections.usb.protocol import LineDecoder, encode, RequestHandler
from vehicle_testing.connections.usb.receiver import serve_connection


SOURCE = 'report_block("from-usb")\nrobot.sendCmd("move_forward:2")\nrobot.sendCmd("led_strip:văn bản")'


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.events, self.calls = [], []
        self.started, self.release = Event(), Event()

        def execute(program, *, stop_event, reporter):
            self.calls.append((program, stop_event))
            reporter("from-usb")
            self.started.set()
            if not self.release.wait(3):
                raise RuntimeError("test worker not released")

        self.session = RobotSession(executor=execute, notify=self.events.append)
        self.addCleanup(self.session.close)
        self.addCleanup(self.release.set)

    def test_upload_never_runs_and_run_uses_uploaded_program(self):
        reply = self.session.dispatch({"action": "upload", "code": SOURCE})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["commands"], 2)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.session.dispatch({"action": "run"})["ok"])
        self.assertTrue(self.started.wait(1))
        self.assertEqual(self.calls[0][0].events[-1].value, "văn bản")
        self.assertEqual(self.session.dispatch({"action": "status"})["status"], "executing")
        self.release.set()
        self.session.wait(1)
        self.assertIn("done", [event.get("status") for event in self.events])

    def test_busy_refuses_second_run_and_new_upload_does_not_change_active_program(self):
        self.session.dispatch({"action": "upload", "code": SOURCE})
        self.session.dispatch({"action": "run"})
        self.assertTrue(self.started.wait(1))
        self.session.dispatch({"action": "upload", "code": 'robot.sendCmd("turn_right:15")'})
        self.assertFalse(self.session.dispatch({"action": "run"})["ok"])
        self.assertEqual(self.calls[0][0].events[1].command, "move_forward")
        self.assertEqual(len(self.calls), 1)

    def test_bad_upload_invalidates_previous_source_before_hardware_runs(self):
        for invalid in ("import os", 'robot.sendCmd("led_strip:🙂")', "", None):
            self.session.dispatch({"action": "upload", "code": SOURCE})
            self.assertFalse(self.session.dispatch({"action": "upload", "code": invalid})["ok"])
            self.assertFalse(self.session.dispatch({"action": "run"})["ok"])
        self.assertEqual(self.calls, [])

    def test_stop_cancels_without_blocking_receiver(self):
        self.session.dispatch({"action": "upload", "code": SOURCE})
        self.session.dispatch({"action": "run"})
        self.assertTrue(self.started.wait(1))
        self.assertTrue(self.session.dispatch({"action": "stop"})["ok"])
        self.assertTrue(self.calls[0][1].is_set())
        self.release.set()
        self.session.wait(1)
        self.assertIn("stopped", [event.get("status") for event in self.events])

    def test_link_loss_cancels_and_requires_new_upload(self):
        self.session.dispatch({"action": "upload", "code": SOURCE})
        self.session.dispatch({"action": "run"})
        self.assertTrue(self.started.wait(1))
        self.session.reset()
        self.assertTrue(self.calls[0][1].is_set())
        self.release.set()
        self.session.wait(1)
        self.assertFalse(self.session.dispatch({"action": "run"})["ok"])

    def test_preview_does_not_open_hardware_and_close_refuses_requests(self):
        preview = RobotSession()
        self.assertTrue(preview.dispatch({"action": "upload", "code": SOURCE})["ok"])
        self.assertEqual(preview.dispatch({"action": "run"})["status"], "preview")
        preview.close()
        self.assertFalse(preview.dispatch({"action": "upload", "code": SOURCE})["ok"])

    def test_worker_failure_reports_error_and_does_not_lock_session(self):
        self.session.executor = Mock(side_effect=OSError("I2C"))
        self.session.dispatch({"action": "upload", "code": SOURCE})
        self.session.dispatch({"action": "run"})
        self.session.wait(1)
        self.assertIn("error", [event.get("status") for event in self.events])
        self.assertEqual(self.session.dispatch({"action": "status"})["status"], "idle")


class ProtocolTests(unittest.TestCase):
    def test_fragmented_utf8_multiline_source_and_multiple_frames(self):
        decoder = LineDecoder()
        data = encode({"id": "1", "action": "upload", "code": SOURCE}) + encode({"id": "2", "action": "run"})
        frames = []
        for byte in data:
            frames.extend(decoder.feed(bytes([byte])))
        self.assertEqual([json.loads(frame)["action"] for frame in frames], ["upload", "run"])
        self.assertEqual(json.loads(frames[0])["code"], SOURCE)

    def test_oversize_frame_is_discarded_to_newline_then_recovers(self):
        decoder = LineDecoder(max_bytes=16)
        self.assertEqual(decoder.feed(b"x" * 20), [])
        self.assertEqual(decoder.feed(b'ignored\n{"ok":true}\n'), [b'{"ok":true}'])
        self.assertEqual(decoder.dropped, 1)

    def test_duplicate_run_id_is_replayed_without_running_twice(self):
        session = Mock()
        session.dispatch.return_value = {"ok": True, "status": "accepted"}
        handler = RequestHandler(session)
        request = encode({"id": "one", "action": "run"}).rstrip(b"\n")
        self.assertEqual(handler.handle(request), handler.handle(request))
        session.dispatch.assert_called_once()
        different = encode({"id": "one", "action": "stop"}).rstrip(b"\n")
        self.assertFalse(handler.handle(different)["ok"])
        session.dispatch.assert_called_once()

    def test_bad_json_utf8_shape_and_action_are_rejected(self):
        session = Mock()
        handler = RequestHandler(session)
        for frame in (b"not json", b"\xff", b"[]", b"{}", b'{"id":"x","action":"exec"}'):
            self.assertFalse(handler.handle(frame)["ok"])
        session.dispatch.assert_not_called()


class ConnectionTests(unittest.TestCase):
    def test_fragmented_upload_ack_and_timeout_invalidate_pending_script(self):
        clock = Mock(side_effect=[0, 0, 0, 6, 6, 6])
        request = encode({"id": "1", "action": "upload", "code": SOURCE})
        done = Event()
        serial = Mock()
        reads = iter([request[:30], request[30:], b""])

        def read(size):
            try:
                return next(reads)
            except StopIteration:
                done.set()
                return b""

        serial.read.side_effect = read
        serial.write.side_effect = lambda data: len(data)
        session = RobotSession()
        serve_connection(serial, session, clock=clock, should_stop=done)
        replies = [json.loads(c.args[0]) for c in serial.write.call_args_list]
        self.assertTrue(any(r.get("status") == "uploaded" for r in replies))
        self.assertFalse(session.dispatch({"action": "run"})["ok"])

    def test_read_failure_cancels_before_propagating(self):
        serial, session = Mock(), Mock()
        serial.read.side_effect = OSError("unplugged")
        with self.assertRaises(OSError):
            serve_connection(serial, session)
        session.reset.assert_called()
        session.wait.assert_called()


if __name__ == "__main__":
    unittest.main()
