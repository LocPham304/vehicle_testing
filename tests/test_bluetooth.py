import json
from queue import Empty, Queue
from threading import Event, Thread
import unittest
from unittest.mock import Mock

from vehicle_testing.connections.bluetooth.receiver import BluetoothReceiver, serve_connection
from vehicle_testing.connections.usb.protocol import encode
from vehicle_testing.runtime.session import RobotSession


SOURCE = 'report_block("bluetooth-only")\nrobot.sendCmd("move_forward:2")\nrobot.sendCmd("led_strip:tiếng Việt")'


class MemorySocket:
    """A bidirectional stream with timeouts, EOF and forced byte fragmentation."""
    def __init__(self):
        self.incoming = Queue()
        self.closed = False
        self.writes = []

    def settimeout(self, timeout):
        pass

    def recv(self, size):
        if self.closed:
            return b""
        try:
            return self.incoming.get(timeout=0.02)
        except Empty:
            raise TimeoutError

    def sendall(self, data):
        if self.closed or self.other.closed:
            raise OSError("link closed")
        self.writes.append(data)
        for offset in range(0, len(data), 7):
            self.other.incoming.put(data[offset:offset + 7])

    def shutdown(self, how):
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.other.incoming.put(b"")


def pair():
    left, right = MemorySocket(), MemorySocket()
    left.other, right.other = right, left
    return left, right


def frame(sock, message):
    sock.sendall(encode(message))


class BluetoothTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = pair()
        self.started, self.release = Event(), Event()
        self.calls = []

        def execute(program, *, stop_event, reporter):
            self.calls.append((program, stop_event))
            reporter("bluetooth-only")
            self.started.set()
            if not self.release.wait(3):
                raise RuntimeError("worker not released")

        self.receiver = BluetoothReceiver(executor=execute, mode="dry-run")
        self.addCleanup(self.receiver.close)
        self.addCleanup(self.release.set)
        self.addCleanup(self.left.close)
        self.receiver.accept("/device/laptop", self.right)

    def request(self, action, request_id=None, **data):
        frame(self.left, {"id": request_id or action, "action": action, **data})

    def wait_reply(self, request_id):
        # Responses/events are each atomically written as a full JSON frame.
        for _ in range(100):
            for raw in list(self.right.writes):
                reply = json.loads(raw)
                if reply.get("id") == request_id:
                    return reply
            Event().wait(0.01)
        self.fail(f"missing reply {request_id}")

    def start_run(self):
        self.request("upload", code=SOURCE)
        self.assertTrue(self.wait_reply("upload")["ok"])
        self.assertEqual(self.calls, [])
        self.request("run")
        self.assertEqual(self.wait_reply("run")["status"], "accepted")
        self.assertTrue(self.started.wait(1))

    def test_unicode_upload_only_and_explicit_run_busy_dedup_and_stop(self):
        self.start_run()
        self.assertEqual(self.calls[0][0].events[-1].value, "tiếng Việt")
        self.request("run")  # Replay same request ID, not another worker.
        self.request("run", request_id="busy")
        self.assertFalse(self.wait_reply("busy")["ok"])
        self.assertEqual(len(self.calls), 1)
        self.request("status")
        self.assertEqual(self.wait_reply("status")["mode"], "dry-run")
        self.request("stop")
        self.assertTrue(self.wait_reply("stop")["ok"])
        self.assertTrue(self.calls[0][1].is_set())

    def test_reject_second_connection_and_keep_owner_until_worker_finishes(self):
        extra, extra_peer = pair()
        self.addCleanup(extra.close)
        with self.assertRaises(RuntimeError):
            self.receiver.accept("/device/other", extra_peer)
        self.assertTrue(extra_peer.closed)
        self.start_run()
        self.receiver.disconnect("/device/laptop")
        self.assertTrue(self.right.closed)
        self.assertTrue(self.calls[0][1].is_set())
        with self.assertRaises(RuntimeError):
            self.receiver.accept("/device/new", pair()[1])

    def test_disconnect_other_device_does_not_interrupt_owner(self):
        self.start_run()
        self.receiver.disconnect("/device/other")
        self.assertFalse(self.calls[0][1].is_set())
        self.assertFalse(self.right.closed)

    def test_eof_cancels_active_run_and_new_connection_requires_upload(self):
        self.start_run()
        self.left.close()
        self.assertTrue(self.calls[0][1].wait(1))
        self.release.set()
        self.assertTrue(self.receiver.wait(1))
        left, right = pair()
        self.addCleanup(left.close)
        self.receiver.accept("/device/reconnected", right)
        frame(left, {"id": "no-upload", "action": "run"})
        for _ in range(100):
            if right.writes:
                break
            Event().wait(0.01)
        self.assertFalse(json.loads(right.writes[0])["ok"])

    def test_malformed_frame_recovers_and_invalid_upload_clears_pending(self):
        self.left.sendall(b'not json\n')
        self.request("upload", code=SOURCE)
        self.assertTrue(self.wait_reply("upload")["ok"])
        self.request("upload", request_id="bad", code='import os')
        self.assertFalse(self.wait_reply("bad")["ok"])
        self.request("run")
        self.assertFalse(self.wait_reply("run")["ok"])
        self.assertEqual(self.calls, [])


class BluetoothTimeoutTests(unittest.TestCase):
    def test_oversized_frame_is_dropped_then_ping_still_works(self):
        connection, session = Mock(), RobotSession()
        data = b"x" * (512 * 1024 + 1) + b"\n" + encode({"id": "ping", "action": "ping"})
        connection.recv.side_effect = [data[i:i+4096] for i in range(0, len(data), 4096)] + [b""]
        serve_connection(connection, session, mode="preview")
        replies = [json.loads(call.args[0]) for call in connection.sendall.call_args_list]
        self.assertTrue(any(r.get("event") == "error" for r in replies))
        self.assertTrue(any(r.get("id") == "ping" and r["ok"] for r in replies))

    def test_heartbeat_loss_cancels_without_another_packet(self):
        left, right = pair()
        now, cancelled, started = [0], Event(), Event()

        def execute(program, *, stop_event, reporter):
            started.set()
            if stop_event.wait(2):
                cancelled.set()

        receiver = BluetoothReceiver(executor=execute, clock=lambda: now[0])
        try:
            receiver.accept("/lost", right)
            frame(left, {"id": "upload", "action": "upload", "code": SOURCE})
            frame(left, {"id": "run", "action": "run"})
            self.assertTrue(started.wait(1))
            for _ in range(100):
                if any(json.loads(raw).get("id") == "run" for raw in list(right.writes)):
                    break
                Event().wait(0.01)
            else:
                self.fail("RUN ACK missing")
            now[0] = 6
            self.assertTrue(cancelled.wait(1))
            self.assertTrue(receiver.wait(1))
            self.assertTrue(right.closed)
        finally:
            left.close()
            receiver.close()

    def test_write_failure_requests_stop_before_exit(self):
        connection, session = Mock(), Mock()
        session.dispatch.return_value = {"ok": True}
        connection.recv.return_value = encode({"id": "x", "action": "ping"})
        connection.sendall.side_effect = OSError("lost")
        with self.assertRaises(OSError):
            serve_connection(connection, session)
        session.reset.assert_called()
        session.wait.assert_called()


if __name__ == "__main__":
    unittest.main()
