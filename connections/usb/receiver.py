"""Pi USB serial receiver. Run: python3 usb_receiver.py --run

Requires a configured CDC ACM gadget, normally /dev/ttyGS0.
Without --run/--dry-run, RUN only previews the uploaded script.
"""

import argparse
from functools import partial
import logging
import sys
from threading import Event, Lock
import time

from vehicle_testing.runtime.session import RobotSession
from vehicle_testing.runtime.runner import execute_program
from vehicle_testing.connections.usb.protocol import LineDecoder, RequestHandler, encode


logger = logging.getLogger(__name__)
LINK_TIMEOUT_SECONDS = 5.0


class SerialWriter:
    def __init__(self, connection):
        self.connection = connection
        self.lock = Lock()

    def send(self, message):
        data = encode(message)
        with self.lock:
            sent = self.connection.write(data)
            if sent != len(data):
                raise OSError("USB write khong day du; ket noi da loi.")


def serve_connection(connection, session, *, clock=time.monotonic,
                     should_stop=None, writer=None, link_timeout=LINK_TIMEOUT_SECONDS):
    """Preserve partial frames across read timeouts; stop on lost host heartbeat."""
    writer = writer or SerialWriter(connection)
    should_stop = should_stop or Event()
    handler, decoder = RequestHandler(session), LineDecoder()
    last_seen, expired = clock(), False
    try:
        while not should_stop.is_set():
            data = connection.read(4096)
            dropped = decoder.dropped
            for frame in decoder.feed(data):
                reply = handler.handle(frame)
                if reply.get("ok"):
                    last_seen, expired = clock(), False
                writer.send(reply)
            if decoder.dropped != dropped:
                writer.send({"event": "error", "error": "Khung USB qua lon; da bo qua."})
            if not expired and clock() - last_seen >= link_timeout:
                session.reset()
                handler.recent.clear()
                decoder = LineDecoder()
                expired = True
                logger.warning("USB mat heartbeat; yeu cau dung va xoa kich ban cho. Upload lai sau khi noi lai.")
    finally:
        session.reset()
        session.wait()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyGS0")
    parser.add_argument("--baud", type=int, default=115200)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="RUN dieu khien motor/LED that")
    mode.add_argument("--dry-run", action="store_true", help="RUN qua runner mo phong")
    args = parser.parse_args(argv)
    if args.baud <= 0:
        parser.error("Baud phai duong.")
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s: %(message)s")
    try:
        import serial
    except ImportError:
        logger.error("Cai dependency: python3 -m pip install -r requirements-usb.txt")
        return 1
    executor = partial(execute_program, dry_run=args.dry_run) if args.run or args.dry_run else None
    label = "PHAN CUNG THAT" if args.run else "RUNNER MO PHONG" if args.dry_run else "PREVIEW"
    logger.info("USB %s, port=%s, baud=%d; upload khong tu chay.", label, args.port, args.baud)
    try:
        while True:
            connection = session = None
            try:
                connection = serial.serial_for_url(args.port, baudrate=args.baud, timeout=0.1, write_timeout=1)
                connection.reset_input_buffer()
                writer = SerialWriter(connection)
                session = RobotSession(executor=executor, notify=writer.send)
                logger.info("San sang USB; dung usb_client.py tren laptop de upload/run/stop.")
                serve_connection(connection, session, writer=writer)
            except (OSError, serial.SerialException) as error:
                logger.warning("Chua noi duoc USB hoac cap da rut: %s. Thu lai sau 1 giay.", error)
            finally:
                try:
                    if session is not None:
                        session.close()
                finally:
                    if connection is not None:
                        connection.close()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Da yeu cau dung va dong USB.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
