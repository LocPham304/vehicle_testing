"""Pi Bluetooth SPP receiver: python3 bluetooth_receiver.py --dry-run."""

import argparse
from functools import partial
import logging
import math
import socket
import sys
from threading import Event, Lock, Thread
import time

from vehicle_testing.connections.usb.protocol import LineDecoder, RequestHandler, encode
from vehicle_testing.runtime.runner import execute_program
from vehicle_testing.runtime.session import RobotSession


logger = logging.getLogger(__name__)


class SocketWriter:
    def __init__(self, connection):
        self.connection = connection
        self.lock = Lock()

    def send(self, message):
        data = encode(message)
        with self.lock:
            self.connection.sendall(data)


def close_socket(connection):
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    finally:
        connection.close()


def serve_connection(connection, session, *, mode="preview", should_stop=None,
                     writer=None, clock=time.monotonic, link_timeout=5):
    """One RFCOMM stream; a timeout invalidates the entire connection/session."""
    stop = should_stop or Event()
    writer = writer or SocketWriter(connection)
    handler, decoder = RequestHandler(session), LineDecoder()
    last_seen = clock()
    try:
        connection.settimeout(0.2)
        while not stop.is_set():
            if clock() - last_seen >= link_timeout:
                logger.warning("Bluetooth mat heartbeat; yeu cau dung, dong link va xoa ban cho.")
                return
            try:
                data = connection.recv(4096)
            except TimeoutError:
                continue
            if not data:  # RFCOMM EOF is a disconnect, not a read timeout.
                return
            dropped = decoder.dropped
            for frame in decoder.feed(data):
                if stop.is_set():
                    return
                reply = handler.handle(frame)
                if reply.get("ok"):
                    last_seen = clock()
                if "mode" in reply:
                    reply = {**reply, "mode": mode}
                writer.send(reply)
            if decoder.dropped != dropped:
                writer.send({"event": "error", "error": "Khung Bluetooth vuot 512 KiB; da bo qua."})
    finally:
        session.reset()
        session.wait()


class BluetoothReceiver:
    """Keep D-Bus callbacks responsive while a single worker owns the script."""
    def __init__(self, *, executor=None, mode="preview", clock=time.monotonic, link_timeout=5):
        if not math.isfinite(link_timeout) or link_timeout <= 0:
            raise ValueError("Link timeout phai duong va huu han.")
        self.executor, self.mode = executor, mode
        self.clock, self.link_timeout = clock, link_timeout
        self._lock = Lock()
        self._closed = False
        self._thread = self._connection = self._session = self._device = self._stop = None

    def accept(self, device, connection):
        """Take ownership even on rejection, so a BlueZ-delivered FD never leaks."""
        with self._lock:
            if self._closed or (self._thread is not None and self._thread.is_alive()):
                close_socket(connection)
                raise RuntimeError("Bluetooth dang co controller hoac dang don lan chay cu.")
            self._device, self._connection = str(device), connection
            self._stop = Event()
            writer = SocketWriter(connection)
            self._session = RobotSession(executor=self.executor, notify=writer.send)
            self._thread = Thread(target=self._serve, args=(connection, self._session, self._stop, writer),
                                  name="bluetooth-connection", daemon=False)
            try:
                self._thread.start()
            except Exception:
                self._session.close()
                close_socket(connection)
                self._thread = self._connection = self._session = self._device = self._stop = None
                raise
        logger.info("Bluetooth da noi %s; cho upload/run/stop. Mode=%s.", device, self.mode)

    def _serve(self, connection, session, stop, writer):
        try:
            serve_connection(connection, session, writer=writer, should_stop=stop,
                             mode=self.mode, clock=self.clock, link_timeout=self.link_timeout)
        except OSError as error:
            logger.info("Bluetooth link da dong: %s", error)
        finally:
            try:
                session.close()
            finally:
                close_socket(connection)
                with self._lock:
                    self._connection = self._session = self._device = self._stop = None

    def disconnect(self, device=None):
        with self._lock:
            if self._connection is not None and (device is None or str(device) == self._device):
                self._stop.set()
                self._session.reset()
                # Close the FD before returning to BlueZ; wait for hardware
                # cleanup outside the D-Bus callback, in the connection worker.
                close_socket(self._connection)

    def wait(self, timeout=None):
        with self._lock:
            worker = self._thread
        if worker is not None:
            worker.join(timeout)
            return not worker.is_alive()
        return True

    def close(self):
        with self._lock:
            self._closed = True
        self.disconnect()
        self.wait()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, default=3, help="Kenh RFCOMM 1..30, mac dinh 3")
    parser.add_argument("--link-timeout", type=float, default=5)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="RUN chay motor/LED that")
    mode.add_argument("--dry-run", action="store_true", help="Mo phong, khong mo GPIO/I2C")
    args = parser.parse_args(argv)
    if not 1 <= args.channel <= 30:
        parser.error("Channel phai trong 1..30.")
    if not math.isfinite(args.link_timeout) or args.link_timeout < 3:
        parser.error("Link timeout phai huu han va >= 3 giay.")
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s: %(message)s")
    label = "hardware" if args.run else "dry-run" if args.dry_run else "preview"
    executor = partial(execute_program, dry_run=args.dry_run) if args.run or args.dry_run else None
    receiver = BluetoothReceiver(executor=executor, mode=label, link_timeout=args.link_timeout)
    try:
        from vehicle_testing.connections.bluetooth.bluez import run_profile
        logger.info("Bluetooth SPP mode=%s, channel=%d; upload KHONG tu run.", label, args.channel)
        run_profile(receiver, channel=args.channel)
        return 0
    except KeyboardInterrupt:
        return 130
    except (ImportError, OSError, RuntimeError) as error:
        logger.error("Bluetooth receiver: %s", error)
        return 1
    finally:
        receiver.close()


if __name__ == "__main__":
    raise SystemExit(main())
