"""Wi-Fi UDP unit tests: no real network sockets, GPIO, or external BE needed."""

from collections import deque
from contextlib import ExitStack, redirect_stderr
from io import StringIO
from queue import Queue
from threading import Event
import unittest
from unittest.mock import MagicMock, patch

from vehicle_testing.connections.wifi.udp_receiver import UdpReceiver, main, serve_datagrams
from vehicle_testing.tests.test_wifi_udp import BE, CAPTURED_CODE, CAPTURED_EXEC


class DatagramInbox:
    """Feed datagrams/timeouts into the real receive loop without using a port."""

    def __init__(self, packets, stop):
        self.packets = deque(packets)
        self.stop = stop

    def settimeout(self, value):
        pass

    def recvfrom(self, size):
        if not self.packets:
            self.stop.set()
            return b"", BE
        packet = self.packets.popleft()
        if isinstance(packet, BaseException):
            raise packet
        return packet() if callable(packet) else packet


class UdpReceiveLoopTests(unittest.TestCase):
    def test_timeouts_preserve_uploaded_script_until_exec_arrives(self):
        calls, stop = Queue(), Event()

        def execute(program, *, stop_event, reporter):
            calls.put(program)

        with UdpReceiver("robot-003", executor=execute) as receiver:
            self.assertTrue(receiver.handle_datagram(CAPTURED_CODE, BE)["ok"])
            connection = DatagramInbox([TimeoutError(), TimeoutError(), (CAPTURED_EXEC, BE)], stop)
            serve_datagrams(connection, receiver, stop)
            receiver.session.wait(1)
            self.assertEqual(calls.get_nowait().command_count, 4)
            self.assertTrue(calls.empty())
            self.assertFalse(receiver.handle_datagram(CAPTURED_EXEC, BE)["ok"])

    def test_bad_packets_do_not_kill_loop_or_prevent_later_upload_and_exec(self):
        calls, events, stop = Queue(), Queue(), Event()

        def execute(program, *, stop_event, reporter):
            calls.put(program)
            reporter("wifi-test")

        connection = DatagramInbox([
            (b"", BE),
            (b"no-header", BE),
            (b"robot-004\nEXEC", BE),
            (CAPTURED_EXEC, BE),  # No valid upload yet.
            (b"robot-003\n\xff", BE),
            (b'robot-003\nrobot.sendCmd("unknown:1")', BE),
            TimeoutError(),
            (CAPTURED_CODE, BE),
            (CAPTURED_EXEC, BE),
        ], stop)
        with UdpReceiver("robot-003", executor=execute, notify=events.put) as receiver:
            serve_datagrams(connection, receiver, stop)
            receiver.session.wait(1)
            self.assertEqual(calls.get_nowait().command_count, 4)
            self.assertTrue(calls.empty())
            output = []
            while not events.empty():
                output.append(events.get_nowait())
            self.assertEqual(output, [
                {"event": "status", "status": "executing"},
                {"event": "block", "block_id": "wifi-test"},
                {"event": "status", "status": "done"},
            ])

    def test_receive_loop_keeps_reading_while_worker_is_executing(self):
        started, finished, stop = Event(), Event(), Event()

        def execute(program, *, stop_event, reporter):
            started.set()
            if not stop_event.wait(2):
                raise RuntimeError("worker was not cancelled")
            finished.set()

        with UdpReceiver("robot-003", executor=execute) as receiver:
            def next_datagram_while_busy():
                self.assertTrue(started.wait(1))
                self.assertEqual(receiver.session.dispatch({"action": "status"})["status"], "executing")
                return b"robot-004\nEXEC", BE

            connection = DatagramInbox([
                (CAPTURED_CODE, BE), (CAPTURED_EXEC, BE), next_datagram_while_busy,
            ], stop)
            serve_datagrams(connection, receiver, stop)
            self.assertTrue(started.is_set())
            self.assertFalse(finished.is_set())
        self.assertTrue(finished.is_set())


class UdpStartupTests(unittest.TestCase):
    def setUp(self):
        # main() configures the application's root logger; do not leak that
        # configuration into the remaining test suite.
        configuration = patch("vehicle_testing.connections.wifi.udp_receiver.logging.basicConfig")
        configuration.start()
        self.addCleanup(configuration.stop)

    def test_default_cli_binds_all_pi_ips_without_a_manually_configured_be_ip(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        receivers = []

        def inspect_loop(sock, receiver, stop):
            receivers.append(receiver)
            self.assertIs(sock, connection)
            self.assertTrue(receiver.handle_datagram(CAPTURED_CODE, BE)["ok"])
            # No --run: default startup must never drive hardware.
            self.assertEqual(receiver.handle_datagram(CAPTURED_EXEC, BE)["status"], "preview")
            new_be = ("10.0.0.93", 42000)
            self.assertTrue(receiver.handle_datagram(CAPTURED_CODE, new_be)["ok"])
            self.assertEqual(receiver.handle_datagram(CAPTURED_EXEC, new_be)["status"], "preview")
            raise KeyboardInterrupt

        with patch("vehicle_testing.connections.wifi.udp_receiver.socket.socket", return_value=connection), \
                patch("vehicle_testing.connections.wifi.udp_receiver.serve_datagrams", side_effect=inspect_loop):
            self.assertEqual(main(["--device-id", "robot-003"]), 130)
        connection.bind.assert_called_once_with(("0.0.0.0", 50000))
        connection.__exit__.assert_called_once()
        self.assertFalse(receivers[0].handle_datagram(CAPTURED_CODE, BE)["ok"])

    def test_invalid_configuration_fails_before_opening_a_socket(self):
        cases = [
            [], ["--device-id", ""], ["--device-id", "robot\n003"],
            ["--device-id", "robot-003", "--port", "0"],
            ["--device-id", "robot-003", "--port", "65536"],
            ["--device-id", "robot-003", "--sender-ip", "not-an-ip"],
            ["--device-id", "robot-003", "--sender-ip", "::1"],
        ]
        for argv in cases:
            with self.subTest(argv=argv), redirect_stderr(StringIO()), \
                    patch("vehicle_testing.connections.wifi.udp_receiver.socket.socket") as factory:
                with self.assertRaises(SystemExit) as error:
                    main(argv)
                self.assertEqual(error.exception.code, 2)
                factory.assert_not_called()

    def test_port_bind_failure_is_logged_and_socket_is_closed(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.bind.side_effect = OSError("port already in use")
        with patch("vehicle_testing.connections.wifi.udp_receiver.socket.socket", return_value=connection), \
                self.assertLogs("vehicle_testing.connections.wifi.udp_receiver", level="ERROR") as logs:
            self.assertEqual(main(["--device-id", "robot-003"]), 1)
        self.assertIn("port already in use", " ".join(logs.output))
        connection.__exit__.assert_called_once()


class UdpClassroomTests(unittest.TestCase):
    def test_broadcast_to_30_robots_only_uploads_and_runs_selected_uuid(self):
        calls = Queue()

        def executor_for(device_id):
            def execute(program, *, stop_event, reporter):
                calls.put((device_id, program))
            return execute

        with ExitStack() as stack:
            robots = {
                device_id: stack.enter_context(UdpReceiver(device_id, executor=executor_for(device_id)))
                for device_id in (f"robot-{number:03d}" for number in range(1, 31))
            }
            for device_id, receiver in robots.items():
                reply = receiver.handle_datagram(CAPTURED_CODE, BE)
                if device_id == "robot-003":
                    self.assertEqual(reply["status"], "uploaded")
                else:
                    self.assertIsNone(reply)
                self.assertEqual(receiver.session.dispatch({"action": "status"})["uploaded"],
                                 device_id == "robot-003")
            self.assertTrue(calls.empty())
            for device_id, receiver in robots.items():
                reply = receiver.handle_datagram(CAPTURED_EXEC, BE)
                if device_id == "robot-003":
                    self.assertEqual(reply["status"], "accepted")
                else:
                    self.assertIsNone(reply)
            robots["robot-003"].session.wait(1)
            device_id, program = calls.get_nowait()
            self.assertEqual(device_id, "robot-003")
            self.assertEqual(program.command_count, 4)
            self.assertTrue(calls.empty())


class UdpLifecycleTests(unittest.TestCase):
    def test_invalid_upload_cannot_establish_a_new_uploader_or_run_old_script(self):
        with UdpReceiver("robot-003") as receiver:
            receiver.handle_datagram(CAPTURED_CODE, BE)
            new_be = ("10.0.0.93", 42000)
            self.assertFalse(receiver.handle_datagram(b"robot-003\n\xff", new_be)["ok"])
            self.assertFalse(receiver.session.dispatch({"action": "status"})["uploaded"])
            self.assertFalse(receiver.handle_datagram(CAPTURED_EXEC, BE)["ok"])
            self.assertFalse(receiver.handle_datagram(CAPTURED_EXEC, new_be)["ok"])
            self.assertTrue(receiver.handle_datagram(CAPTURED_CODE, BE)["ok"])
            with self.assertLogs("vehicle_testing.connections.wifi.udp_receiver", level="WARNING"):
                self.assertIsNone(receiver.handle_datagram(CAPTURED_EXEC, new_be))
            self.assertEqual(receiver.handle_datagram(CAPTURED_EXEC, BE)["status"], "preview")

    def test_worker_error_is_reported_and_receiver_accepts_a_fresh_upload(self):
        events = Queue()

        def failed_executor(program, *, stop_event, reporter):
            raise RuntimeError("simulated motor failure")

        with UdpReceiver("robot-003", executor=failed_executor, notify=events.put) as receiver:
            receiver.handle_datagram(CAPTURED_CODE, BE)
            with self.assertLogs("vehicle_testing.runtime.session", level="ERROR") as logs:
                self.assertEqual(receiver.handle_datagram(CAPTURED_EXEC, BE)["status"], "accepted")
                receiver.session.wait(1)
            self.assertIn("simulated motor failure", " ".join(logs.output))
            self.assertEqual(events.get_nowait(), {"event": "status", "status": "executing"})
            error = events.get_nowait()
            self.assertEqual(error["event"], "error")
            self.assertIn("simulated motor failure", error["error"])
            self.assertEqual(events.get_nowait(), {"event": "status", "status": "error"})
            self.assertFalse(receiver.handle_datagram(CAPTURED_EXEC, BE)["ok"])
            self.assertTrue(receiver.handle_datagram(CAPTURED_CODE, BE)["ok"])
            self.assertEqual(receiver.session.dispatch({"action": "status"})["status"], "idle")

    def test_close_cancels_a_live_worker_and_restart_requires_upload_again(self):
        started, finished = Event(), Event()

        def execute(program, *, stop_event, reporter):
            started.set()
            if not stop_event.wait(2):
                raise RuntimeError("worker was not cancelled")
            finished.set()

        with UdpReceiver("robot-003", executor=execute) as receiver:
            receiver.handle_datagram(CAPTURED_CODE, BE)
            receiver.handle_datagram(CAPTURED_EXEC, BE)
            self.assertTrue(started.wait(1))
            self.assertFalse(finished.is_set())
            receiver.close()
            self.assertTrue(finished.is_set())
            self.assertFalse(receiver.handle_datagram(CAPTURED_EXEC, BE)["ok"])
        with UdpReceiver("robot-003") as restarted:
            self.assertFalse(restarted.handle_datagram(CAPTURED_EXEC, BE)["ok"])
            self.assertTrue(restarted.handle_datagram(CAPTURED_CODE, BE)["ok"])
            self.assertEqual(restarted.handle_datagram(CAPTURED_EXEC, BE)["status"], "preview")


if __name__ == "__main__":
    unittest.main()
