from functools import partial
from pathlib import Path
from contextlib import redirect_stdout
import io
from queue import Empty, Queue
import tempfile
from threading import Event, Thread
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from vehicle_testing.script_session import RobotSession
from vehicle_testing.scratch_runner import execute_program
from vehicle_testing.usb_receiver import SerialWriter, serve_connection
from vehicle_testing.usb_client import USBClient, run_console
from vehicle_testing import usb_client


class MemorySerial:
    def __init__(self):
        self.incoming = Queue()
        self.closed = False

    def read(self, size):
        if self.closed:
            raise OSError("closed")
        try:
            return self.incoming.get(timeout=0.02)
        except Empty:
            return b""

    def write(self, data):
        if self.other.closed:
            raise OSError("disconnected")
        # Model arbitrary USB read fragmentation, including UTF-8 boundaries.
        for offset in range(0, len(data), 7):
            self.other.incoming.put(data[offset:offset + 7])
        return len(data)

    def close(self):
        self.closed = True


class ClientTests(unittest.TestCase):
    def test_startup_reset_failure_closes_already_open_port(self):
        connection = Mock()
        connection.reset_input_buffer.side_effect = OSError("unplugged during startup")
        serial = ModuleType("serial")
        serial.SerialException = OSError
        serial.serial_for_url = Mock(return_value=connection)
        tools = ModuleType("serial.tools")
        tools.list_ports = SimpleNamespace(comports=lambda: [])
        with patch.dict("sys.modules", {"serial": serial, "serial.tools": tools}), redirect_stdout(io.StringIO()):
            self.assertEqual(usb_client.main(["--port", "COM5"]), 1)
        connection.close.assert_called_once_with()

    def test_console_upload_and_run_are_separate_user_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "script.txt"
            source.write_text('robot.sendCmd("led_strip:HELLO")', encoding="utf-8")
            client = Mock()
            client.closed = False
            client.request.return_value = {"ok": True}
            lines = iter(["upload", "status", "exit"])
            run_console(client, input_fn=lambda prompt: next(lines), output_fn=lambda text: None, default_file=source)
            self.assertEqual([c.args[0] for c in client.request.call_args_list], ["upload", "status"])
            self.assertEqual(client.request.call_args_list[0].kwargs["code"], source.read_text(encoding="utf-8"))

    def test_real_client_and_receiver_exchange_multiline_unicode_script_and_status(self):
        left, right = MemorySerial(), MemorySerial()
        left.other, right.other = right, left
        stop, done = Event(), Event()
        received = []
        writer = SerialWriter(right)

        def execute(program, **kwargs):
            received.append(program)
            execute_program(program, dry_run=True, **kwargs)

        session = RobotSession(executor=execute, notify=writer.send)
        server = Thread(target=serve_connection, args=(right, session),
                        kwargs={"writer": writer, "should_stop": stop})
        server.start()
        client = USBClient(left, notify=lambda event: done.set() if event.get("status") == "done" else None)
        client.start()
        try:
            code = 'report_block("usb-test")\nrobot.sendCmd("led_strip:tiếng Việt")'
            reply = client.request("upload", code=code)
            self.assertTrue(reply["ok"], reply)
            self.assertEqual(received, [])
            self.assertEqual(client.request("run")["status"], "accepted")
            self.assertTrue(done.wait(2))
            self.assertEqual(received[0].events[-1].value, "tiếng Việt")
            self.assertEqual(client.request("status")["status"], "idle")
        finally:
            client.close()
            stop.set()
            server.join(2)
            session.close()
        self.assertFalse(server.is_alive())


if __name__ == "__main__":
    unittest.main()
