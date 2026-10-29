from functools import partial
from http.client import HTTPConnection
import json
import os
from threading import Event, Thread
import unittest
from unittest.mock import patch

from vehicle_testing.wifi_receiver import WifiController, WifiServer
from vehicle_testing.wifi_client import WifiClient
from vehicle_testing.scratch_runner import execute_program


SOURCE = 'report_block("network-block")\nrobot.sendCmd("move_forward:2")\nrobot.sendCmd("led_strip:văn bản")'


class WifiControlTests(unittest.TestCase):
    def setUp(self):
        self.started, self.release = Event(), Event()
        self.calls = []
        self.now = 0

        def execute(program, *, stop_event, reporter):
            self.calls.append((program, stop_event))
            reporter("network-block")
            self.started.set()
            if not self.release.wait(4):
                raise RuntimeError("test did not release worker")

        self.control = WifiController(executor=execute, mode="dry-run", clock=lambda: self.now)
        self.addCleanup(self.control.close)
        self.addCleanup(self.release.set)
        status, reply = self.control.request("POST", "/connect", {"client_id": "laptop"})
        self.assertEqual(status, 200)
        self.token = reply["token"]

    def send(self, path, **data):
        data.setdefault("id", path)
        return self.control.request("POST", path, data, token=self.token)

    def start(self):
        self.assertEqual(self.send("/upload", code=SOURCE)[0], 200)
        self.assertTrue(self.send("/run")[1]["ok"])
        self.assertTrue(self.started.wait(1))

    def test_upload_only_stores_and_run_uses_exact_uploaded_program(self):
        code, reply = self.send("/upload", code=SOURCE)
        self.assertEqual(code, 200)
        self.assertEqual(reply["commands"], 2)
        self.assertEqual(self.calls, [])
        self.send("/run")
        self.assertTrue(self.started.wait(1))
        self.assertEqual(self.calls[0][0].events[-1].value, "văn bản")
        self.release.set()
        self.control.session.wait(1)
        code, reply = self.control.request("GET", "/events?after=0", token=self.token)
        self.assertEqual(code, 200)
        self.assertIn("done", [item.get("status") for item in reply["events"]])
        self.assertIn("network-block", [item.get("block_id") for item in reply["events"]])

    def test_busy_and_duplicate_run_never_start_second_worker(self):
        self.start()
        self.assertTrue(self.send("/run")[1]["ok"])  # same ID, replay ACK
        self.assertFalse(self.send("/run", id="another-run")[1]["ok"])
        self.assertEqual(len(self.calls), 1)

    def test_new_upload_preserves_active_snapshot(self):
        self.start()
        self.send("/upload", id="replacement", code='robot.sendCmd("turn_right:15")')
        self.assertEqual(self.calls[0][0].events[1].command, "move_forward")

    def test_bad_replacement_clears_program_and_run_fails(self):
        self.send("/upload", code=SOURCE)
        code, reply = self.send("/upload", id="bad", code='robot.sendCmd("led_strip:🙂")')
        self.assertFalse(reply["ok"])
        self.assertFalse(self.send("/run")[1]["ok"])
        self.assertEqual(self.calls, [])

    def test_second_controller_and_missing_or_wrong_token_refused(self):
        self.assertEqual(self.control.request("POST", "/connect", {"client_id": "other"})[0], 409)
        for token in (None, "wrong", "sai tiếng Việt"):
            self.assertEqual(self.control.request("POST", "/run", {"id": "x"}, token=token)[0], 403)
        self.assertNotIn("token", self.control.request("GET", "/status")[1])

    def test_expiry_cancels_active_run_clears_pending_and_invalidates_token(self):
        self.start()
        self.now = 6
        self.control.expire()
        self.assertTrue(self.calls[0][1].is_set())
        self.assertEqual(self.send("/run", id="late")[0], 403)
        self.release.set()
        self.control.session.wait(1)
        code, reply = self.control.request("POST", "/connect", {"client_id": "new"})
        self.assertEqual(code, 200)
        self.assertNotEqual(reply["token"], self.token)
        self.assertFalse(self.control.request("POST", "/run", {"id": "new-run"}, token=reply["token"])[1]["ok"])

    def test_ping_extends_lease_but_observer_status_does_not(self):
        self.now = 4
        self.assertTrue(self.send("/ping")[1]["ok"])
        self.now = 8
        self.control.expire()
        self.assertEqual(self.send("/ping", id="second-ping")[0], 200)
        self.now = 14
        self.control.request("GET", "/status")
        self.assertEqual(self.send("/ping", id="late")[0], 403)

    def test_stop_and_disconnect_cancel_without_waiting_for_worker(self):
        self.start()
        self.assertTrue(self.send("/stop")[1]["ok"])
        self.assertTrue(self.calls[0][1].is_set())
        self.assertEqual(self.control.request("POST", "/disconnect", {}, token=self.token)[0], 200)
        self.assertEqual(self.control.request("POST", "/connect", {"client_id": "other"})[0], 200)

    def test_preview_and_unknown_method_or_endpoint(self):
        control = WifiController()
        self.addCleanup(control.close)
        _, reply = control.request("POST", "/connect", {"client_id": "preview"})
        token = reply["token"]
        control.request("POST", "/upload", {"id": "u", "code": SOURCE}, token=token)
        self.assertEqual(control.request("POST", "/run", {"id": "r"}, token=token)[1]["status"], "preview")
        self.assertEqual(control.request("GET", "/run")[0], 405)
        self.assertEqual(control.request("GET", "/missing")[0], 404)
        self.assertEqual(control.request("GET", "/status")[1]["mode"], "preview")

    def test_bounded_events_and_cursor_does_not_repeat_consumed_reports(self):
        for i in range(2000):
            self.control.record_event({"event": "block", "block_id": str(i)})
        _, reply = self.control.request("GET", "/events?after=0", token=self.token)
        self.assertLessEqual(len(reply["events"]), 256)
        self.assertTrue(reply["truncated"])
        _, next_reply = self.control.request("GET", f'/events?after={reply["cursor"]}', token=self.token)
        self.assertEqual(next_reply["events"], [])

    def test_control_fields_cannot_override_action_and_old_id_cannot_change_content(self):
        self.assertEqual(self.send("/upload", code=SOURCE, action="run")[0], 400)
        self.assertFalse(self.send("/run")[1]["ok"])
        self.send("/upload", code=SOURCE)
        self.assertEqual(self.send("/upload", code='robot.sendCmd("move_forward:10")')[0], 400)
        self.send("/run", id="valid-run")
        self.assertTrue(self.started.wait(1))
        self.assertEqual(self.calls[0][0].events[1].value, 2)

    def test_events_memory_bounded_by_bytes_as_well_as_count(self):
        for i in range(20):
            self.control.record_event({"event": "block", "block_id": "x" * 60000})
        _, reply = self.control.request("GET", "/events?after=0", token=self.token)
        self.assertLess(len(json.dumps(reply).encode()), 300000)
        self.assertTrue(reply["truncated"])


@unittest.skipUnless(os.environ.get("RUN_WIFI_HTTP_INTEGRATION") == "1", "Enable loopback HTTP with RUN_WIFI_HTTP_INTEGRATION=1")
class WifiHTTPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.control = WifiController(executor=partial(execute_program, dry_run=True), mode="dry-run")
        self.server = WifiServer(("127.0.0.1", 0), self.control)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()
        self.host, self.port = self.server.server_address
        self.url = f"http://{self.host}:{self.port}"
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()

    def http(self, method, path, body=None, *, token=None, headers=None):
        connection = HTTPConnection(self.host, self.port, timeout=3)
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        if token:
            request_headers["X-Session-Token"] = token
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_real_http_client_upload_run_blocks_done_and_disconnect_release(self):
        done = Event()
        events = []

        def notify(event):
            events.append(event)
            if event.get("status") == "done":
                done.set()

        client = WifiClient(self.url, notify=notify)
        self.addCleanup(client.close)
        self.assertEqual(client.start()["mode"], "dry-run")
        with patch.object(self.control.session, "executor", wraps=self.control.session.executor) as execute:
            self.assertTrue(client.request("upload", code=SOURCE)["ok"])
            execute.assert_not_called()
            self.assertEqual(client.request("run")["status"], "accepted")
            self.assertTrue(done.wait(3))
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[0].events[-1].value, "văn bản")
        self.assertEqual([item["block_id"] for item in events if item.get("event") == "block"], ["network-block"])
        client.close()
        other = WifiClient(self.url)
        self.addCleanup(other.close)
        other.start()
        self.assertFalse(other.request("status")["uploaded"])

    def test_malformed_oversized_wrong_content_type_and_unauthorized_http(self):
        self.assertEqual(self.http("POST", "/upload", b'{broken')[0], 400)
        self.assertEqual(self.http("POST", "/connect", b'[]')[0], 400)
        self.assertEqual(self.http("POST", "/run", b'{"id":"run"}')[0], 403)
        self.assertEqual(self.http("GET", "/run")[0], 405)
        self.assertEqual(self.http("GET", "/missing")[0], 404)
        self.assertEqual(self.http("POST", "/connect", b'{}', headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.http("POST", "/upload", b' ', headers={"Content-Length": "524289"})[0], 413)
        self.assertEqual(self.http("GET", "/status")[1]["mode"], "dry-run")

    def test_watchdog_cancels_when_client_traffic_stops_without_more_http(self):
        # Fake monotonic advance; a worker blocks until the independent watchdog
        # requests cancellation, with no further client requests to trigger expiry.
        now = [0]
        self.control.clock = lambda: now[0]
        started, cancelled = Event(), Event()

        def execute(program, *, stop_event, reporter):
            started.set()
            if stop_event.wait(2):
                cancelled.set()

        self.control.session.executor = execute
        _, connection = self.http("POST", "/connect", b'{"client_id":"lost-client"}')
        token = connection["token"]
        self.http("POST", "/upload", json.dumps({"id": "upload", "code": SOURCE}).encode(), token=token)
        self.http("POST", "/run", b'{"id":"run"}', token=token)
        self.assertTrue(started.wait(1))
        now[0] = 6
        self.assertTrue(cancelled.wait(1))
        self.assertFalse(self.http("GET", "/status")[1]["uploaded"])
        self.assertEqual(self.http("POST", "/ping", b'{"id":"late"}', token=token)[0], 403)


if __name__ == "__main__":
    unittest.main()
