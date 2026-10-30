"""Receive external BE packets: UUID + LF + source, or UUID + LF + EXEC."""

import argparse
from functools import partial
import ipaddress
import logging
import re
import socket
from threading import Event, RLock

from vehicle_testing.runtime.runner import execute_program
from vehicle_testing.runtime.session import RobotSession


logger = logging.getLogger(__name__)
MAX_DATAGRAM_BYTES = 65507  # Maximum IPv4 UDP payload, including our UUID header.


class UdpReceiver:
    """One complete script per datagram; each valid upload arms one EXEC."""

    def __init__(self, device_id, *, executor=None, sender_ip=None, notify=None):
        if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", device_id):
            raise ValueError("Device ID can 1..64 ky tu ASCII: chu, so, dau cham, gach ngang/duoi.")
        if sender_ip is not None:
            sender_ip = str(ipaddress.IPv4Address(sender_ip))
        self.device_id, self.sender_ip = device_id, sender_ip
        self._header = device_id.encode("ascii")
        self._armed = self._closed = False
        self._lock = RLock()
        self.session = RobotSession(executor=executor, notify=notify or self._log_event)

    @staticmethod
    def _log_event(event):
        logger.info("UDP event: %s", event)

    def handle_datagram(self, data, sender):
        """Return a local result; no response wire format has been supplied by BE."""
        with self._lock:
            if self._closed:
                return {"ok": False, "error": "Receiver da dong."}
            if self.sender_ip is not None and sender[0] != self.sender_ip:
                return None
            header, separator, body = data.partition(b"\n")
            if not separator or header != self._header:
                return None  # Other robots must not invalidate this robot's upload.
            if body == b"EXEC":
                if not self._armed:
                    reply = {"ok": False, "error": "Can upload moi truoc EXEC; moi upload chi chay mot lan."}
                else:
                    reply = self.session.dispatch({"action": "run"})
                    if reply.get("ok"):
                        self._armed = False
                logger.info("UDP EXEC %s tu %s: %s", self.device_id, sender, reply)
                return reply
            if self.session.dispatch({"action": "status"})["status"] == "executing":
                return {"ok": False, "error": "Robot dang chay; khong nhan upload moi."}
            self._armed = False
            if len(data) > MAX_DATAGRAM_BYTES:
                self.session.reset()
                reply = {"ok": False, "error": "Khung UDP qua lon; can kich ban tron ven trong mot goi."}
            else:
                try:
                    code = body.decode("utf-8")
                except UnicodeDecodeError:
                    self.session.reset()
                    reply = {"ok": False, "error": "Kich ban khong phai UTF-8 hop le."}
                else:
                    reply = self.session.dispatch({"action": "upload", "code": code})
                    self._armed = bool(reply.get("ok"))
            logger.info("UDP UPLOAD %s tu %s (%s byte): %s", self.device_id, sender, len(body), reply)
            return reply

    def close(self):
        with self._lock:
            self._closed = True
            self._armed = False
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def serve_datagrams(connection, receiver, stop_event):
    """Keep reading while RobotSession runs commands on its separate worker."""
    connection.settimeout(0.2)
    while not stop_event.is_set():
        try:
            data, sender = connection.recvfrom(65535)
        except TimeoutError:
            continue
        receiver.handle_datagram(data, sender)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True, help="UUID rieng cua xe, vi du robot-003")
    parser.add_argument("--host", default="0.0.0.0", help="Dia chi lang nghe tren Pi")
    parser.add_argument("--port", type=int, default=50000)
    parser.add_argument("--sender-ip", help="Chi nhan tu IPv4 cua BE, vi du 192.168.1.93")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Chay motor/LED that khi nhan EXEC")
    mode.add_argument("--dry-run", action="store_true", help="Mo phong runner, khong dung GPIO")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port phai trong 1..65535.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    executor = partial(execute_program, dry_run=args.dry_run) if args.run or args.dry_run else None
    try:
        receiver = UdpReceiver(args.device_id, executor=executor, sender_ip=args.sender_ip)
    except ValueError as error:
        parser.error(str(error))
    try:
        with receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.bind((args.host, args.port))
            logger.info("Wi-Fi UDP %s tai %s:%s; UUID=%s; sender=%s.",
                        "hardware" if args.run else "dry-run" if args.dry_run else "preview",
                        args.host, args.port, args.device_id, args.sender_ip or "any")
            logger.info("Upload KHONG tu chay; EXEC chay mot lan; upload lai de chay tiep. Ctrl+C de dung.")
            serve_datagrams(connection, receiver, Event())
        return 0
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        logger.error("Loi Wi-Fi UDP receiver: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
