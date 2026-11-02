"""Receive FE JSON UPLOAD/EXEC over the existing /stem WebSocket server.

The Pi is a client of the existing /stem server. That server must forward FE
messages to the Pi connection. Preview by default; --dry-run simulates the
shared runner and --run enables hardware after UPLOAD then EXEC. No application
messages are sent: registration/response contracts are not yet confirmed.
"""

import argparse
import importlib
import json
import logging
import math
import re
import sys
from threading import Event
from urllib.parse import urlsplit
from functools import partial
from threading import RLock

from vehicle_testing.runtime.parser import format_program, parse_program
from vehicle_testing.runtime.session import RobotSession


logger = logging.getLogger(__name__)
DEFAULT_URL = "ws://192.168.1.93:5000/stem"
MAX_MESSAGE_BYTES = 512 * 1024
MAX_LOG_CHARS = 4096


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ("ws", "wss") or not parsed.hostname
                or parsed.fragment or parsed.username is not None or parsed.password is not None):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except ValueError as error:
        raise ValueError("URL can dang ws://IP:cong/stem hoac wss://host/stem.") from error
    return parsed


def load_websocket():
    try:
        return importlib.import_module("websocket")
    except ImportError as error:
        raise RuntimeError("Thieu websocket-client. Cai: python -m pip install -r requirements-wifi.txt") from error


def validate_device_id(device_id):
    if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", device_id):
        raise ValueError("Device ID can 1..64 ky tu ASCII: chu, so, dau cham, gach ngang/duoi.")


class WebSocketReceiver:
    """Filter UUID, retain one upload, execute once, reset on disconnect."""

    def __init__(self, device_id, *, executor=None, mode="preview"):
        validate_device_id(device_id)
        self.device_id = device_id
        self.mode = mode
        self.current_program = None
        self.connected = False
        self.had_error = False
        self.interrupted = False
        self._armed = self._closed = False
        self._lock = RLock()
        self.session = RobotSession(executor=executor, notify=self._event)

    def _event(self, event):
        # Called from the session worker; never take the receiver lock here.
        logger.info("WS EVENT: %r (chi log tai Pi, chua gui phan hoi server)", event)

    def _reset(self):
        self.connected = False
        self.current_program = None
        self._armed = False
        self.session.reset()

    def on_open(self, connection):
        with self._lock:
            self._reset()
            if self._closed:
                return
            self.connected = True
        logger.info("WS CONNECTED | UUID=%s | mode=%s.", self.device_id, self.mode)
        logger.info("Cho FE UPLOAD/EXEC. Server /stem phai chuyen tiep tin nhan toi ket noi Pi.")

    def on_message(self, connection, message):
        # repr escapes terminal control characters; truncate before formatting.
        snippet = repr(message[:MAX_LOG_CHARS]) if isinstance(message, (str, bytes)) else repr(type(message))
        logger.info("WS RX: %s%s", snippet,
                    " [da cat bot log]" if isinstance(message, (str, bytes)) and len(message) > MAX_LOG_CHARS else "")
        with self._lock:
            return self._handle_message(message)

    def _handle_message(self, message):
        if not self.connected or self._closed:
            return {"ok": False, "error": "WebSocket da ngat."}
        if not isinstance(message, str):
            logger.warning("Bo qua frame binary; hop dong FE da cung cap la JSON text.")
            return {"ok": False, "error": "Can JSON text."}
        try:
            if len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise ValueError("Tin nhan vuot 512 KiB.")
            payload = json.loads(message)
            if not isinstance(payload, dict):
                raise ValueError("Can JSON object.")
        except (ValueError, UnicodeError, RecursionError) as error:
            logger.warning("WS payload khong hop le: %s", error)
            return {"ok": False, "error": str(error)}
        if payload.get("uuid") != self.device_id:
            logger.info("Bo qua payload khong dung UUID=%s.", self.device_id)
            return None
        kind = payload.get("type")
        if kind == "EXEC":
            if payload.get("code") != "":
                return {"ok": False, "error": "Goi EXEC can code rong nhu payload FE da xac nhan."}
            if not self._armed:
                logger.warning("WS EXEC: can upload moi truoc khi chay; moi upload cho phep mot EXEC.")
                return {"ok": False, "error": "Can upload moi truoc EXEC."}
            reply = self.session.dispatch({"action": "run"})
            if reply.get("ok"):
                self._armed = False
            logger.info("WS EXEC UUID=%s: %s", self.device_id, reply)
            return reply
        if kind != "UPLOAD":
            logger.info("WS EVENT UUID=%s type=%r: da bat tin, chua gan vao lenh chay xe.",
                        self.device_id, kind)
            return {"ok": False, "error": "Type chua duoc xac nhan; chi ghi log."}
        if self.session.dispatch({"action": "status"})["status"] == "executing":
            return {"ok": False, "error": "Robot dang chay; khong nhan upload moi."}
        self._armed = False
        self.current_program = None
        reply = self.session.dispatch({"action": "upload", "code": payload.get("code")})
        if not reply.get("ok"):
            logger.warning("WS UPLOAD khong hop le; da xoa ban cho cu: %s", reply)
            return reply
        program = parse_program(payload["code"])
        self.current_program = program
        self._armed = True
        logger.info("WS UPLOAD UUID=%s | %d lenh.\n%s", self.device_id,
                    program.command_count, format_program(program))
        logger.info("Upload KHONG tu chay; cho type EXEC. Mode=%s. Ket qua chi log tai Pi.", self.mode)
        return reply

    def on_error(self, connection, error):
        with self._lock:
            self.had_error = True
            if isinstance(error, KeyboardInterrupt):
                self.interrupted = True
            self._reset()
        if self.interrupted:
            logger.info("WS INTERRUPTED: dung theo Ctrl+C, khong ket noi lai.")
        else:
            logger.error("WS ERROR: %s", error)

    def on_close(self, connection, status, reason):
        self.disconnect()
        logger.info("WS CLOSED: code=%r, reason=%r; da xoa ban cho, yeu cau dung worker.", status, reason)

    def disconnect(self):
        with self._lock:
            self._reset()

    def close(self):
        with self._lock:
            self._closed = True
            self._reset()
        self.session.close()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--once", action="store_true", help="Khong ket noi lai khi ngat/loi")
    parser.add_argument("--reconnect-seconds", type=float, default=2)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="EXEC chay motor/LED that sau UPLOAD hop le")
    mode.add_argument("--dry-run", action="store_true", help="EXEC qua runner mo phong, khong mo GPIO")
    args = parser.parse_args(argv)
    try:
        endpoint = validate_url(args.url)
        # Validate identity/options before importing a socket library or opening hardware.
        validate_device_id(args.device_id)
        if not math.isfinite(args.reconnect_seconds) or args.reconnect_seconds <= 0:
            raise ValueError("Thoi gian ket noi lai phai duong huu han.")
    except ValueError as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", stream=sys.stdout)
    try:
        websocket = load_websocket()
    except RuntimeError as error:
        logger.error("%s", error)
        return 1
    executor = None
    if args.run or args.dry_run:
        from vehicle_testing.runtime.runner import execute_program
        executor = partial(execute_program, dry_run=args.dry_run)
    receiver = WebSocketReceiver(args.device_id, executor=executor,
                                mode="hardware" if args.run else "dry-run" if args.dry_run else "preview")
    # websocket-client uses this timeout for the initial socket connection.
    websocket.setdefaulttimeout(10)
    retry = Event()
    try:
        while True:
            logger.info("WS CONNECT: %s | mode=%s | Ctrl+C de thoat.", args.url, receiver.mode)
            app = websocket.WebSocketApp(
                args.url, on_open=receiver.on_open, on_message=receiver.on_message,
                on_error=receiver.on_error, on_close=receiver.on_close,
            )
            try:
                app.run_forever(ping_interval=20, ping_timeout=10,
                                http_no_proxy=[endpoint.hostname])
            finally:
                app.close()
                receiver.disconnect()
            # websocket-client 1.9 may report Ctrl+C to on_error then swallow it.
            if receiver.interrupted:
                return 130
            if args.once:
                return 1 if receiver.had_error else 0
            logger.info("Thu ket noi lai sau %g giay; khong phat lai tin nhan.", args.reconnect_seconds)
            retry.wait(args.reconnect_seconds)
    except KeyboardInterrupt:
        logger.info("Da yeu cau dung va dong listener WebSocket.")
        return 130
    finally:
        receiver.close()


if __name__ == "__main__":
    raise SystemExit(main())
