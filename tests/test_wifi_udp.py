"""External BE datagrams captured on the user's Pi, not an invented JSON API."""

from importlib.util import find_spec
import os
from queue import Queue
import socket
from threading import Event, Thread
import time
import unittest


CAPTURED_CODE = b'''robot-003
report_block(")xzR$@uEnJi(Jj%.p)n7")
report_block("V0D(SIWG2DO%83`i0VG0")
robot.sendCmd("move_forward:1")
report_block("7lIkr1v4}y+nMv_DzTWw")
robot.sendCmd("turn_left:90")
report_block(".!?.i@/T~|ws!,B4hn{K")
robot.sendCmd("move_backward:1")
report_block("V:3!r7+L6__yvW{LcVC}")
robot.sendCmd("led_strip:abcd")
'''
CAPTURED_EXEC = b"robot-003\nEXEC"
BE = ("192.168.1.93", 58711)


class AvailabilityTests(unittest.TestCase):
    def test_udp_adapter_exists_for_captured_be_protocol(self):
        self.assertIsNotNone(find_spec("vehicle_testing.connections.wifi.udp_receiver"))


class UdpControlTests(unittest.TestCase):
    def setUp(self):
        from vehicle_testing.connections.wifi.udp_receiver import UdpReceiver
        self.started, self.release = Event(), Event()
        self.calls = []

        def execute(program, *, stop_event, reporter):
            self.calls.append((program, stop_event))
            reporter("udp-block")
            self.started.set()
            self.release.wait(3)

        self.control = UdpReceiver("robot-003", executor=execute, sender_ip=BE[0])
        self.addCleanup(self.control.close)
        self.addCleanup(self.release.set)

    def send(self, data, sender=BE):
        return self.control.handle_datagram(data, sender)

    def start_run(self):
        self.assertTrue(self.send(CAPTURED_CODE)["ok"])
        self.assertTrue(self.send(CAPTURED_EXEC)["ok"])
        self.assertTrue(self.started.wait(1))

    def test_exact_live_capture_upload_does_not_run_and_exec_runs_parsed_snapshot(self):
        self.assertEqual(len(CAPTURED_CODE), 322)
        self.assertEqual(len(CAPTURED_EXEC), 14)
        reply = self.send(CAPTURED_CODE)
        self.assertEqual(reply["status"], "uploaded")
        self.assertEqual(reply["commands"], 4)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.send(CAPTURED_EXEC)["status"], "accepted")
        self.assertTrue(self.started.wait(1))
        program = self.calls[0][0]
        self.assertEqual(program.events[2].value, 1)
        self.assertEqual(program.events[4].value, 90)
        self.assertEqual(program.events[-1].value, "abcd")

    def test_exec_before_upload_is_rejected(self):
        self.assertFalse(self.send(CAPTURED_EXEC)["ok"])
        self.assertEqual(self.calls, [])

    def test_other_uuid_and_other_sender_cannot_replace_or_execute_program(self):
        self.send(CAPTURED_CODE)
        self.assertIsNone(self.send(b"robot-004\n\xff"))
        self.assertIsNone(self.send(CAPTURED_EXEC, ("192.168.1.94", 123)))
        self.assertIsNone(self.send(b"robot-004\nEXEC"))
        self.assertTrue(self.send(CAPTURED_EXEC)["ok"])
        self.assertTrue(self.started.wait(1))

    def test_uuid_prefix_does_not_match_another_robot(self):
        self.assertIsNone(self.send(b"robot-003-extra\nEXEC"))

    def test_sender_port_may_change(self):
        self.send(CAPTURED_CODE)
        self.assertTrue(self.send(CAPTURED_EXEC, (BE[0], 60000))["ok"])

    def test_invalid_owned_replacement_disarms_previous_program(self):
        for body in (b"", b"\xff", b'robot.sendCmd("unknown:1")', b"EXEC\n",
                     b"exec", b"EXEC ", b"STOP", b"x" * 65536):
            with self.subTest(body=body[:40]):
                self.send(CAPTURED_CODE)
                self.assertFalse(self.send(b"robot-003\n" + body)["ok"])
                self.assertFalse(self.send(CAPTURED_EXEC)["ok"])
        self.assertEqual(self.calls, [])

    def test_missing_separator_is_ignored_and_cannot_run(self):
        self.assertIsNone(self.send(b"robot-003EXEC"))
        self.assertIsNone(self.send(b"robot-003"))
        self.assertEqual(self.calls, [])

    def test_utf8_text_is_preserved(self):
        data = 'robot-003\nrobot.sendCmd("led_strip:văn bản")'.encode("utf-8")
        self.assertTrue(self.send(data)["ok"])
        self.send(CAPTURED_EXEC)
        self.assertTrue(self.started.wait(1))
        self.assertEqual(self.calls[0][0].events[0].value, "văn bản")

    def test_duplicate_exec_during_and_after_run_cannot_repeat_movement(self):
        self.start_run()
        self.assertFalse(self.send(CAPTURED_EXEC)["ok"])
        self.release.set()
        self.control.session.wait(1)
        self.assertFalse(self.send(CAPTURED_EXEC)["ok"])
        self.assertEqual(len(self.calls), 1)
        self.send(CAPTURED_CODE)
        self.assertTrue(self.send(CAPTURED_EXEC)["ok"])
        self.control.session.wait(1)
        self.assertEqual(len(self.calls), 2)

    def test_busy_upload_is_rejected_without_changing_active_snapshot(self):
        self.start_run()
        self.assertFalse(self.send(b'robot-003\nrobot.sendCmd("turn_right:30")')["ok"])
        self.assertEqual(self.calls[0][0].events[2].command, "move_forward")

    def test_close_requests_cancellation(self):
        self.start_run()
        self.release.set()
        self.control.close()
        self.assertTrue(self.calls[0][1].is_set())
        self.assertFalse(self.send(CAPTURED_CODE)["ok"])

    def test_default_mode_only_previews(self):
        from vehicle_testing.connections.wifi.udp_receiver import UdpReceiver
        with UdpReceiver("robot-003") as preview:
            preview.handle_datagram(CAPTURED_CODE, BE)
            self.assertEqual(preview.handle_datagram(CAPTURED_EXEC, BE)["status"], "preview")


@unittest.skipUnless(os.environ.get("RUN_WIFI_UDP_INTEGRATION") == "1", "opt-in UDP loopback")
class UdpLoopbackTests(unittest.TestCase):
    def test_actual_udp_upload_and_exec_use_dry_run_runner(self):
        from functools import partial
        from vehicle_testing.connections.wifi.udp_receiver import UdpReceiver, serve_datagrams
        from vehicle_testing.runtime.runner import execute_program

        events, stop = Queue(), Event()
        with UdpReceiver("robot-003", executor=partial(execute_program, dry_run=True),
                         notify=events.put) as control:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
                server.bind(("127.0.0.1", 0))
                thread = Thread(target=serve_datagrams, args=(server, control, stop))
                thread.start()
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                        client.sendto(CAPTURED_CODE, server.getsockname())
                        deadline = time.monotonic() + 2
                        while not control.session.dispatch({"action": "status"})["uploaded"]:
                            self.assertLess(time.monotonic(), deadline)
                            stop.wait(0.01)
                        self.assertTrue(events.empty())
                        client.sendto(CAPTURED_EXEC, server.getsockname())
                        statuses, blocks = [], []
                        while "done" not in statuses:
                            event = events.get(timeout=2)
                            statuses.append(event.get("status"))
                            if "block_id" in event:
                                blocks.append(event["block_id"])
                        self.assertEqual(len(blocks), 5)
                        self.assertIn("executing", statuses)
                finally:
                    stop.set()
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
