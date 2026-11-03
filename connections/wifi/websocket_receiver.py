"""Pi WebSocket server: Windows Local Helper connects to ws://<PI_IP>:50000/stem.

Listen on 0.0.0.0:50000. Answer action=identify with identify_response, UUID
and deviceName for LAN discovery. Preview by default; --dry-run simulates UPLOAD/EXEC;
--run enables the shared hardware runner. Discovery never claims control.
Use --setup once to save this Pi's registered UUID/name, then start without identity flags.
"""

import argparse
import importlib
import json
import logging
import sys
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit
from functools import partial
from threading import RLock

from vehicle_testing.runtime.identity import (
    DEFAULT_IDENTITY_FILE, DeviceIdentity, load_identity, save_identity,
    validate_device_id, validate_device_name,
)
from vehicle_testing.runtime.parser import format_program, parse_program
from vehicle_testing.runtime.session import RobotSession


logger = logging.getLogger(__name__)
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 50000
MAX_MESSAGE_BYTES = 512 * 1024
MAX_LOG_CHARS = 4096
MAX_RAW_LOG_CHARS = 200


def load_websocket_server():
    try:
        return importlib.import_module("websockets.sync.server")
    except ImportError as error:
        raise RuntimeError("Thieu websockets. Cai: python -m pip install -r requirements-wifi.txt") from error


def control_fields(payload):
    """Read the FE action/payload format or the existing type/code format."""
    if "type" in payload:
        return payload.get("type"), payload.get("code")
    action = payload.get("action")
    kind = ({"upload": "UPLOAD", "exec": "EXEC"}.get(action.lower(), action)
            if isinstance(action, str) else action)
    return kind, payload.get("payload")


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
        logger.info("WS EXECUTION EVENT: %r (log tai Pi)", event)

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
        logger.info("Nhan truc tiep UPLOAD/EXEC tu ket noi FE dang dieu khien.")

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
        kind, code = control_fields(payload)
        if kind == "EXEC":
            if code != "":
                return {"ok": False, "error": "Goi EXEC can payload/code rong; can UPLOAD truoc khi chay."}
            if not self._armed:
                logger.warning("WS EXEC: can upload moi truoc khi chay; moi upload cho phep mot EXEC.")
                return {"ok": False, "error": "Can upload moi truoc EXEC."}
            reply = self.session.dispatch({"action": "exec"})
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
        reply = self.session.dispatch({"action": "upload", "code": code})
        if not reply.get("ok"):
            logger.warning("WS UPLOAD khong hop le; da xoa ban cho cu: %s", reply)
            return reply
        program = parse_program(code)
        self.current_program = program
        self._armed = True
        logger.info("WS UPLOAD UUID=%s | %d block marker | %d lenh | %d byte code.\n%s", self.device_id,
                    program.marker_count, program.command_count, len(code.encode("utf-8")),
                    format_program(program))
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


class RobotWebSocketServer:
    """Allow concurrent discovery probes and one active control connection."""

    def __init__(self, device_id, *, name=None, executor=None, mode="preview"):
        self.name = name if name is not None else f"Robot {device_id}"
        validate_device_name(self.name)
        self.device_id = device_id
        self.receiver = WebSocketReceiver(device_id, executor=executor, mode=mode)
        self.owner = None
        self._lock = RLock()
        self._connections = set()
        self._closed = False

    def process_request(self, connection, request):
        if urlsplit(request.path).path not in ("/stem", "/"):
            return connection.respond(HTTPStatus.NOT_FOUND, "WebSocket endpoint: /stem\n")
        return None

    @staticmethod
    def _remote_address(connection):
        # The receive thread may already have closed the underlying socket.
        try:
            return getattr(connection, "remote_address", None)
        except OSError:
            return None

    def handle_message(self, connection, message):
        truncated = isinstance(message, (str, bytes)) and len(message) > MAX_RAW_LOG_CHARS
        logger.info("WS RX RAW tu %s: %r%s", self._remote_address(connection),
                    message[:MAX_RAW_LOG_CHARS] if isinstance(message, (str, bytes)) else type(message),
                    f" [log rut gon: {MAX_RAW_LOG_CHARS}/{len(message)} ky tu; khong cat message]"
                    if truncated else "")
        if not isinstance(message, str):
            return {"ok": False, "error": "Can JSON text hoac identify."}
        if len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
            return {"ok": False, "error": "Tin nhan vuot 512 KiB."}
        try:
            payload = {"type": "identify"} if message.strip().lower() == "identify" else json.loads(message)
            if not isinstance(payload, dict):
                raise ValueError("Can JSON object.")
        except (ValueError, UnicodeError, RecursionError) as error:
            return {"ok": False, "error": str(error)}
        kind, _ = control_fields(payload)
        with self._lock:
            if self._closed:
                return {"ok": False, "error": "Server dang dong."}
            if "uuid" in payload and payload["uuid"] != self.device_id:
                logger.info("WS IGNORE UUID: nhan=%r, UUID cua Pi=%s.", payload["uuid"], self.device_id)
                return None
            if isinstance(kind, str) and kind.lower() == "identify":
                logger.info("WS IDENTIFY: UUID=%s, name=%r.", self.device_id, self.name)
                return {"action": "identify_response", "uuid": self.device_id, "deviceName": self.name}
            if payload.get("uuid") != self.device_id:
                return None
            if self.owner is None:
                if kind != "UPLOAD":
                    return {"ok": False, "error": "Can UPLOAD tren ket noi nay truoc EXEC."}
                self.owner = connection
                self.receiver.on_open(connection)
            elif self.owner is not connection:
                return {"ok": False, "error": "Robot dang co ket noi dieu khien khac."}
            return self.receiver.on_message(connection, message)

    def handle_connection(self, connection):
        with self._lock:
            if self._closed:
                connection.close(code=1001, reason="Server stopping")
                return
            self._connections.add(connection)
        remote_address = self._remote_address(connection)
        logger.info("WS CLIENT CONNECTED: %s", remote_address)
        try:
            for message in connection:
                reply = self.handle_message(connection, message)
                if reply is not None:
                    connection.send(json.dumps(reply, ensure_ascii=False))
        except Exception as error:
            logger.warning("WS CLIENT CLOSED/ERROR: %s", error)
        finally:
            logger.info("WS CLIENT CLOSED: %s code=%r reason=%r",
                        remote_address,
                        getattr(connection, "close_code", None),
                        getattr(connection, "close_reason", None))
            with self._lock:
                self._connections.discard(connection)
                if self.owner is connection:
                    self.receiver.disconnect()
                    self.owner = None

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connections = list(self._connections)
        try:
            self.receiver.close()
        finally:
            for connection in connections:
                try:
                    connection.close(code=1001, reason="Server stopping")
                except Exception:
                    logger.exception("Khong dong duoc mot ket noi FE.")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, help="Dia chi lang nghe tren Pi, mac dinh 0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--identity-file", type=Path, default=DEFAULT_IDENTITY_FILE,
                        help="File UUID/ten rieng cua Pi; mac dinh device_identity.json o goc project")
    parser.add_argument("--device-id", help="Ghi de UUID cho lan chay nay; --setup de luu lau dai")
    parser.add_argument("--name", help="Ten robot tren FE; --setup de luu lau dai")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true", help="Gan UUID/ten mot lan, luu file va thoat")
    mode.add_argument("--run", action="store_true", help="EXEC chay motor/LED that sau UPLOAD hop le")
    mode.add_argument("--dry-run", action="store_true", help="EXEC qua runner mo phong, khong mo GPIO")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("Port phai trong [1, 65535].")
        if args.setup:
            print("Gan dinh danh cho Pi nay. Nhap UUID/ten dung voi robot da dang ky tren FE.")
            device_id = args.device_id if args.device_id is not None else input("UUID (vi du robot-003): ").strip()
            name = args.name if args.name is not None else input("Ten robot tren FE: ").strip()
            identity = DeviceIdentity(device_id, name)
            save_identity(args.identity_file, identity)
            print(f"Da luu UUID={identity.uuid}, name={identity.name!r} tai {args.identity_file.resolve()}")
            config_option = ("" if args.identity_file.resolve() == DEFAULT_IDENTITY_FILE.resolve()
                             else f' --identity-file "{args.identity_file.resolve()}"')
            print(f"Lan sau chay: python wifi_websocket_receiver.py{config_option} --dry-run")
            return 0
        if args.device_id is not None:
            name = args.name if args.name is not None else f"Robot {args.device_id}"
            identity = DeviceIdentity(args.device_id, name)
        else:
            identity = load_identity(args.identity_file)
            if args.name is not None:
                identity = DeviceIdentity(identity.uuid, args.name)
    except (ValueError, OSError, EOFError) as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", stream=sys.stdout)
    logger.info("WS IDENTITY: UUID=%s | name=%r | source=%s.", identity.uuid, identity.name,
                "CLI" if args.device_id is not None else args.identity_file.resolve())
    try:
        websocket = load_websocket_server()
    except RuntimeError as error:
        logger.error("%s", error)
        return 1
    executor = None
    if args.run or args.dry_run:
        from vehicle_testing.runtime.runner import execute_program
        executor = partial(execute_program, dry_run=args.dry_run)
    controller = RobotWebSocketServer(identity.uuid, name=identity.name, executor=executor,
                                    mode="hardware" if args.run else "dry-run" if args.dry_run else "preview")
    try:
        with websocket.serve(
                controller.handle_connection, args.host, args.port,
                process_request=controller.process_request, max_size=MAX_MESSAGE_BYTES,
                ping_interval=20, ping_timeout=10, open_timeout=10, close_timeout=3,
                compression=None) as server:
            logger.info("WS SERVER LISTENING: %s:%d/stem | UUID=%s | name=%r | mode=%s.",
                        args.host, args.port, identity.uuid, controller.name, controller.receiver.mode)
            logger.info("Windows Local Helper ket noi ws://<IP_PI>:%d/stem, gui action=identify; "
                        "xem IP Pi bang hostname -I. Ctrl+C de dung.", args.port)
            try:
                server.serve_forever()
            finally:
                controller.close()
        return 0
    except KeyboardInterrupt:
        logger.info("Da dung WebSocket server va dong ket noi FE.")
        return 130
    except OSError as error:
        logger.error("Khong mo/chay duoc WebSocket server %s:%d: %s", args.host, args.port, error)
        return 1
    finally:
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
