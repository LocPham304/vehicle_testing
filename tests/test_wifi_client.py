from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from vehicle_testing.control_console import run_console
from vehicle_testing.wifi_client import WifiClient, main


class WifiClientTests(unittest.TestCase):
    def test_console_upload_never_implicitly_runs_and_accepts_unicode_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "script.txt"
            code = 'robot.sendCmd("led_strip:tiếng Việt")'
            source.write_text(code, encoding="utf-8-sig")
            client = Mock(closed=False)
            client.request.return_value = {"ok": True}
            lines = iter(["upload", "status", "run", "stop", "exit"])
            prompts = []

            def read(prompt):
                prompts.append(prompt)
                return next(lines)

            run_console(client, input_fn=read, output_fn=lambda text: None,
                        default_file=source, prompt="wifi> ")
            self.assertEqual([call.args[0] for call in client.request.call_args_list],
                             ["upload", "status", "run", "stop"])
            self.assertEqual(client.request.call_args_list[0].kwargs["code"], code)
            self.assertEqual(set(prompts), {"wifi> "})

    def test_json_http_preserves_unicode_and_session_header_and_reads_400(self):
        client = WifiClient("http://pi.local:8765")
        client._token = "private-token"
        response = io.BytesIO(b'{"ok":true,"status":"uploaded"}')
        client._opener = Mock()
        client._opener.open.return_value = response
        self.assertTrue(client.request("upload", code='robot.sendCmd("led_strip:văn bản")')["ok"])
        request = client._opener.open.call_args.args[0]
        self.assertEqual(request.get_header("X-session-token"), "private-token")
        self.assertEqual(json.loads(request.data)["code"], 'robot.sendCmd("led_strip:văn bản")')
        client._opener.open.side_effect = HTTPError("http://pi", 400, "busy", {},
                                                  io.BytesIO(b'{"ok":false,"error":"busy"}'))
        self.assertEqual(client.request("run")["error"], "busy")

    def test_ambiguous_run_network_failure_is_not_retried(self):
        client = WifiClient("http://pi:8765")
        client._token = "token"
        client._opener = Mock()
        client._opener.open.side_effect = URLError("unreachable")
        with self.assertRaises(OSError):
            client.request("run")
        self.assertEqual(client._opener.open.call_count, 1)

    def test_background_detects_failure_closes_and_reports_disconnect(self):
        failed = Event()
        reports = []
        client = WifiClient("http://pi:8765", notify=lambda event: (reports.append(event), failed.set()))
        client._http = Mock(side_effect=[{"ok": True, "token": "t", "cursor": 0},
                                        OSError("wifi lost"), OSError("still offline")])
        client.start()
        try:
            self.assertTrue(failed.wait(2))
            self.assertTrue(client.closed)
            self.assertEqual(reports[0]["event"], "disconnected")
            with self.assertRaises(OSError):
                client.request("run")
        finally:
            client.close()

    def test_close_releases_owner_without_exposing_token_in_start_reply(self):
        client = WifiClient("http://pi:8765")
        client._http = Mock(return_value={"ok": True, "token": "secret", "cursor": 0})
        try:
            reply = client.start()
            self.assertNotIn("token", reply)
        finally:
            client.close()
        self.assertTrue(client.closed)
        self.assertIsNone(client._token)
        self.assertEqual(client._http.call_args.args, ("POST", "/disconnect", {}))

    def test_cli_failure_still_closes_client(self):
        with patch("vehicle_testing.wifi_client.WifiClient") as factory, redirect_stdout(io.StringIO()):
            factory.return_value.start.side_effect = OSError("no Pi")
            self.assertEqual(main(["--host", "192.168.1.40"]), 1)
        factory.return_value.close.assert_called_once_with()

    def test_reject_invalid_url_and_oversized_script_before_network(self):
        for url in ("file:///tmp", "http://", "http://pi/path", "http://name:pass@pi"):
            with self.assertRaises(ValueError):
                WifiClient(url)
        client = WifiClient("http://pi:8765")
        client._token = "token"
        client._http = Mock()
        with self.assertRaises(ValueError):
            client.request("upload", code="x" * 65537)
        client._http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
