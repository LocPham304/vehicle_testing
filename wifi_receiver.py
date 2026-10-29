"""Receive Scratch scripts directly over LAN HTTP, independently of MQTT."""

import argparse
from collections import deque
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
from pathlib import Path
import secrets
import sys
from threading import Event, Lock, RLock, Thread, current_thread
import time
from urllib.parse import parse_qs, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing.script_session import RobotSession
from vehicle_testing.scratch_runner import execute_program
from vehicle_testing.usb_protocol import MAX_FRAME_BYTES, RequestHandler, encode


logger = logging.getLogger(__name__)
MAX_EVENTS = 256
MAX_EVENT_BYTES = 256 * 1024


class WifiController:
    """One controller lease; session owns the immutable active script snapshot."""

    def __init__(self, *, executor=None, mode="preview", clock=time.monotonic, link_timeout=5):
        if not math.isfinite(link_timeout) or link_timeout <= 0:
            raise ValueError("Link timeout phai duong va huu han.")
        self.mode, self.clock, self.link_timeout = mode, clock, link_timeout
        self._lock, self._event_lock = RLock(), Lock()
        self._events = deque()
        self._event_bytes = self._sequence = 0
        self._token = self._client_id = None
        self._last_seen = 0
        self._closed = False
        self.session = RobotSession(executor=executor, notify=self.record_event)
        self.handler = RequestHandler(self.session)

    def record_event(self, event):
        # This callback must never take _lock: the worker calls it under its
        # session lock, while HTTP dispatch takes _lock before the session lock.
        with self._event_lock:
            self._sequence += 1
            item = {**event, "sequence": self._sequence}
            size = len(encode(item))
            self._events.append((item, size))
            self._event_bytes += size
            while len(self._events) > MAX_EVENTS or self._event_bytes > MAX_EVENT_BYTES:
                self._event_bytes -= self._events.popleft()[1]

    def _release(self):
        self.session.reset()
        self.handler.recent.clear()
        self._token = self._client_id = None

    def expire(self):
        with self._lock:
            if self._token is not None and self.clock() - self._last_seen >= self.link_timeout:
                logger.warning("Wi-Fi mat heartbeat; yeu cau dung va xoa kich ban cho.")
                self._release()

    @staticmethod
    def error(status, message):
        return status, {"ok": False, "error": message}

    def request(self, method, target, body=None, *, token=None):
        url = urlsplit(target)
        path = url.path
        routes = {"/connect": "POST", "/disconnect": "POST", "/upload": "POST",
                  "/run": "POST", "/stop": "POST", "/ping": "POST",
                  "/status": "GET", "/events": "GET"}
        with self._lock:
            self.expire()
            if self._closed:
                return self.error(503, "Receiver da dong.")
            if path not in routes:
                return self.error(404, "Endpoint khong ton tai.")
            if routes[path] != method:
                return self.error(405, "HTTP method khong duoc ho tro tai endpoint nay.")
            if method == "POST" and not isinstance(body, dict):
                return self.error(400, "Can JSON object.")
            if path == "/status":
                return 200, {**self.session.dispatch({"action": "status"}),
                             "mode": self.mode, "controller_connected": self._token is not None}
            if path == "/connect":
                client_id = body.get("client_id")
                if (set(body) != {"client_id"} or not isinstance(client_id, str)
                        or not 1 <= len(client_id) <= 64):
                    return self.error(400, "Can client_id chuoi 1..64 ky tu.")
                if self._token is not None:
                    return self.error(409, "Da co laptop dieu khien. Thoat client cu hoac cho het heartbeat.")
                self._client_id, self._token = client_id, secrets.token_urlsafe(32)
                self._last_seen = self.clock()
                with self._event_lock:
                    cursor = self._sequence
                return 200, {"ok": True, "token": self._token, "cursor": cursor,
                             "mode": self.mode, "link_timeout": self.link_timeout}
            if (not isinstance(token, str) or self._token is None
                    or not secrets.compare_digest(token.encode("utf-8"), self._token.encode("ascii"))):
                return self.error(403, "Phien khong hop le hoac da het han; ket noi va upload lai.")
            if path == "/events":
                try:
                    query = parse_qs(url.query, strict_parsing=True)
                    if set(query) != {"after"} or len(query["after"]) != 1:
                        raise ValueError
                    after = int(query["after"][0])
                    if after < 0:
                        raise ValueError
                except (ValueError, KeyError):
                    return self.error(400, "Can /events?after=SO_KHONG_AM.")
                # Polling events does not substitute for the controller heartbeat.
                with self._event_lock:
                    oldest = self._events[0][0]["sequence"] if self._events else self._sequence + 1
                    return 200, {"ok": True,
                                 "events": [item for item, _ in self._events if item["sequence"] > after],
                                 "cursor": self._sequence, "truncated": after < oldest - 1}
            if path == "/disconnect":
                if body:
                    return self.error(400, "Disconnect can JSON rong {}.")
                self._release()
                return 200, {"ok": True, "status": "disconnected"}
            allowed = {"id", "code"} if path == "/upload" else {"id"}
            if set(body) - allowed:
                return self.error(400, "Truong du lieu chua duoc ho tro.")
            reply = self.handler.handle(encode({**body, "action": path[1:]}))
            if reply.get("ok"):
                self._last_seen = self.clock()
            return (200 if reply.get("ok") else 400), reply

    def close(self):
        with self._lock:
            self._closed = True
            self._release()
        self.session.close()


class WifiRequestHandler(BaseHTTPRequestHandler):
    server_version = "RobotHTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(2)  # Bound header reads as well as JSON body reads.

    def _reply(self, status, reply):
        data = encode(reply)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _serve(self):
        body = None
        try:
            if self.command == "POST":
                if self.headers.get("Transfer-Encoding"):
                    self._reply(400, {"ok": False, "error": "Can Content-Length; khong ho tro chunked."})
                    return
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 <= length <= MAX_FRAME_BYTES:
                    self._reply(413, {"ok": False, "error": "JSON body phai trong 512 KiB."})
                    return
                if self.headers.get_content_type() != "application/json":
                    self._reply(415, {"ok": False, "error": "Can Content-Type: application/json."})
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("JSON body chua day du.")
                body = json.loads(raw.decode("utf-8"))
            status, reply = self.server.control.request(
                self.command, self.path, body, token=self.headers.get("X-Session-Token"))
        except (ValueError, UnicodeError, RecursionError) as error:
            status, reply = 400, {"ok": False, "error": str(error)}
        except (TimeoutError, ConnectionError):
            status, reply = 408, {"ok": False, "error": "Het thoi gian nhan HTTP body."}
        try:
            self._reply(status, reply)
        except OSError:
            pass  # Owner lease expires even if a reply cannot reach the laptop.

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = do_HEAD = _serve

    def log_message(self, format, *args):
        logger.debug(format, *args)


class WifiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, control):
        self.control = control
        self._done = Event()
        super().__init__(address, WifiRequestHandler)
        self._watchdog = Thread(target=self._watch, name="wifi-watchdog", daemon=True)
        self._watchdog.start()

    def _watch(self):
        while not self._done.wait(0.1):
            self.control.expire()

    def server_close(self):
        self._done.set()
        if hasattr(self, "_watchdog") and self._watchdog is not current_thread():
            self._watchdog.join(1)
        try:
            self.control.close()
        finally:
            super().server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Dia chi lang nghe tren Pi")
    parser.add_argument("--port", type=int, default=8765)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Chay motor/LED that khi nhan RUN")
    mode.add_argument("--dry-run", action="store_true", help="Mo phong runner; khong dung phan cung")
    parser.add_argument("--link-timeout", type=float, default=5)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port phai trong 1..65535.")
    if not math.isfinite(args.link_timeout) or args.link_timeout < 3:
        parser.error("Link timeout phai huu han va >= 3 giay.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    execution_mode = "hardware" if args.run else "dry-run" if args.dry_run else "preview"
    executor = partial(execute_program, dry_run=args.dry_run) if args.run or args.dry_run else None
    control = WifiController(executor=executor, mode=execution_mode, link_timeout=args.link_timeout)
    server = None
    try:
        server = WifiServer((args.host, args.port), control)
        logger.info("Wi-Fi HTTP %s tai %s:%s; upload KHONG tu run; khong can MQTT.",
                    execution_mode, args.host, args.port)
        server.serve_forever(poll_interval=0.2)
        return 0
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        logger.error("Khong mo duoc HTTP receiver: %s", error)
        return 1
    finally:
        if server is not None:
            server.server_close()
        else:
            control.close()


if __name__ == "__main__":
    raise SystemExit(main())
