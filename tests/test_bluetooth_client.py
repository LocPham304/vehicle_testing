from contextlib import redirect_stdout
import io
import os
import socket
from threading import Event
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from vehicle_testing.connections.bluetooth.client import BluetoothClient, main
from vehicle_testing.connections.bluetooth.receiver import BluetoothReceiver
from vehicle_testing.runtime.runner import execute_program
from vehicle_testing.tests.test_bluetooth import pair


class SocketSerial:
    def __init__(self, socket):
        self.socket = socket

    def read(self, size):
        try:
            data = self.socket.recv(size)
        except TimeoutError:
            return b""
        if not data:
            raise OSError("Bluetooth EOF")
        return data

    def write(self, data):
        self.socket.sendall(data)
        return len(data)

    def close(self):
        self.socket.close()


class BluetoothClientTests(unittest.TestCase):
    def test_real_client_stream_exchange_returns_unicode_blocks_done_and_explicit_mode(self):
        left, right = pair()
        done, events, received = Event(), [], []

        def execute(program, **kwargs):
            received.append(program)
            execute_program(program, dry_run=True, **kwargs)

        receiver = BluetoothReceiver(executor=execute, mode="dry-run")
        receiver.accept("/paired-laptop", right)

        def notify(event):
            events.append(event)
            if event.get("status") == "done":
                done.set()

        client = BluetoothClient(SocketSerial(left), notify=notify)
        client.start()
        try:
            self.assertEqual(client.request("status")["mode"], "dry-run")
            code = 'report_block("bt-code")\nrobot.sendCmd("led_strip:tiếng Việt")'
            self.assertTrue(client.request("upload", code=code)["ok"])
            self.assertEqual(received, [])
            self.assertEqual(client.request("run")["status"], "accepted")
            self.assertTrue(done.wait(2))
            self.assertEqual(received[0].events[-1].value, "tiếng Việt")
            self.assertEqual([e["block_id"] for e in events if e.get("event") == "block"], ["bt-code"])
        finally:
            client.close()
            receiver.close()

    def test_cli_port_selection_is_bluetooth_and_closes_on_failure(self):
        connection = Mock()
        connection.reset_input_buffer.side_effect = OSError("disconnected")
        serial = ModuleType("serial")
        serial.SerialException = OSError
        serial.serial_for_url = Mock(return_value=connection)
        tools = ModuleType("serial.tools")
        tools.list_ports = SimpleNamespace(comports=lambda: [SimpleNamespace(device="COM8", description="Bluetooth SPP")])
        with patch.dict("sys.modules", {"serial": serial, "serial.tools": tools}), \
                patch("builtins.input", return_value="1"), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 1)
        self.assertIn("Bluetooth", output.getvalue())
        self.assertEqual(serial.serial_for_url.call_args.args, ("COM8",))
        connection.close.assert_called_once_with()

    def test_help_does_not_require_linux_bluetooth_dependencies(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit:
            main(["--help"])
        self.assertEqual(exit.exception.code, 0)

    @unittest.skipUnless(os.environ.get("RUN_BT_STREAM_INTEGRATION") == "1", "Enable actual socket stream with RUN_BT_STREAM_INTEGRATION=1")
    def test_actual_socket_stream_with_simulated_runner(self):
        left, right = socket.socketpair()
        left.settimeout(0.1)
        done = Event()
        receiver = BluetoothReceiver(executor=lambda program, **kwargs: execute_program(program, dry_run=True, **kwargs),
                                     mode="dry-run")
        receiver.accept("/loopback-only", right)
        client = BluetoothClient(SocketSerial(left), notify=lambda event: done.set() if event.get("status") == "done" else None)
        client.start()
        try:
            self.assertEqual(client.request("status")["mode"], "dry-run")
            self.assertTrue(client.request("upload", code='robot.sendCmd("led_strip:KẾT NỐI BT")')["ok"])
            self.assertEqual(client.request("run")["status"], "accepted")
            self.assertTrue(done.wait(2))
        finally:
            client.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
