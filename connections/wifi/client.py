"""Laptop HTTP console: python wifi_client.py --host 192.168.1.40."""

import argparse
import json
import sys
from threading import Event, Thread, current_thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import uuid

from vehicle_testing.runtime.console import run_console
from vehicle_testing.connections.usb.protocol import MAX_FRAME_BYTES, encode


class WifiClient:
    def __init__(self, base_url, *, notify=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username):
            raise ValueError("Can URL goc, vi du http://192.168.1.40:8765.")
        self.base_url = base_url.rstrip("/")
        self.notify = notify or (lambda event: print("Pi:", json.dumps(event, ensure_ascii=False), flush=True))
        self._opener = build_opener(ProxyHandler({}))
        self._done = Event()
        self._thread = None
        self._token = None
        self._cursor = 0

    @property
    def closed(self):
        return self._done.is_set()

    def _http(self, method, path, body=None, *, timeout=2):
        headers = {"Content-Type": "application/json"}
        if self._token is not None:
            headers["X-Session-Token"] = self._token
        request = Request(self.base_url + path, data=encode(body) if body is not None else None,
                          headers=headers, method=method)
        try:
            try:
                response = self._opener.open(request, timeout=timeout)
            except HTTPError as error:
                response = error  # Read structured errors such as busy/expired lease.
            with response:
                raw = response.read(MAX_FRAME_BYTES + 1)
            if len(raw) > MAX_FRAME_BYTES:
                raise ValueError("Phan hoi HTTP qua lon.")
            reply = json.loads(raw.decode("utf-8"))
            if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
                raise ValueError("Phan hoi Pi khong dung JSON protocol.")
            return reply
        except URLError as error:
            raise OSError(f"Khong ket noi duoc Pi: {error.reason}") from error

    def start(self):
        if self._thread is not None or self.closed:
            raise ValueError("Client da khoi dong hoac da dong.")
        reply = self._http("POST", "/connect", {"client_id": uuid.uuid4().hex})
        if not reply.get("ok"):
            raise OSError(reply.get("error", "Khong tao duoc phien Wi-Fi."))
        self._token, self._cursor = reply["token"], reply["cursor"]
        self._thread = Thread(target=self._heartbeat, name="wifi-ping-events", daemon=True)
        self._thread.start()
        return {key: value for key, value in reply.items() if key != "token"}

    def request(self, action, *, code=None, timeout=2, request_id=None):
        if self.closed or self._token is None:
            raise OSError("Wi-Fi da dong; khoi dong client va upload lai.")
        if action not in {"upload", "run", "stop", "status", "ping"}:
            raise ValueError("Action chua duoc ho tro.")
        if action == "status":
            return self._http("GET", "/status", timeout=timeout)
        body = {"id": request_id or uuid.uuid4().hex}
        if code is not None:
            if action != "upload" or len(code.encode("utf-8")) > 65536:
                raise ValueError("Chi upload nhan code, toi da 64 KiB UTF-8.")
            body["code"] = code
        # No automatic retry: an ambiguous RUN timeout is not permission to run twice.
        return self._http("POST", "/" + action, body, timeout=timeout)

    def _heartbeat(self):
        while not self._done.wait(1):
            try:
                reply = self.request("ping")
                if self.closed:
                    return
                if not reply.get("ok"):
                    raise OSError(reply.get("error", "Heartbeat loi."))
                events = self._http("GET", f"/events?after={self._cursor}")
                if not events.get("ok"):
                    raise OSError(events.get("error", "Khong doc duoc events."))
                if events["truncated"]:
                    self.notify({"event": "warning", "error": "Da bo qua events cu do vuot gioi han bo dem."})
                for event in events["events"]:
                    self.notify(event)
                self._cursor = events["cursor"]
            except (OSError, ValueError, KeyError, TypeError) as error:
                if self.closed:
                    return
                self._done.set()
                self.notify({"event": "disconnected", "error": str(error)})
                return

    def close(self):
        self._done.set()
        if self._token is not None:
            try:
                self._http("POST", "/disconnect", {}, timeout=1)
            except (OSError, ValueError):
                pass
        if self._thread is not None and self._thread is not current_thread():
            self._thread.join(5)
        self._token = None


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="IP hoac ten Pi; bo trong de nhap")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port phai trong 1..65535.")
    client = None
    try:
        host = args.host or input("IP cua Pi (vi du 192.168.1.40): ").strip()
        client = WifiClient(f"http://{host}:{args.port}")
        print("Pi:", client.start())
        print("Pi:", client.request("status"))
        run_console(client, prompt="wifi> ")
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, EOFError) as error:
        print(f"Loi Wi-Fi: {error}")
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
