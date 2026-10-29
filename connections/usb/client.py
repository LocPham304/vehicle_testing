"""Laptop console: python usb_client.py (choose COM, then upload/run/stop)."""

import argparse
import json
from queue import Empty, Queue
import sys
from threading import Event, Lock, Thread, current_thread
import uuid

from vehicle_testing.connections.usb.protocol import LineDecoder, encode
from vehicle_testing.runtime.console import DEFAULT_FILE, run_console


class USBClient:
    def __init__(self, connection, *, notify=None, transport="USB"):
        self.connection = connection
        self.transport = transport
        self.notify = notify or (lambda event: print("Pi:", json.dumps(event, ensure_ascii=False), flush=True))
        self._done = Event()
        self._lock, self._write_lock = Lock(), Lock()
        self._pending = {}
        self._threads = []

    @property
    def closed(self):
        return self._done.is_set()

    def start(self):
        self._threads = [Thread(target=self._read, name="usb-read", daemon=True),
                         Thread(target=self._heartbeat, name="usb-ping", daemon=True)]
        for thread in self._threads:
            thread.start()

    def _fail(self, error):
        self._done.set()
        with self._lock:
            for queue in self._pending.values():
                queue.put({"ok": False, "error": str(error)})

    def request(self, action, *, code=None, timeout=3):
        if self.closed:
            raise OSError(f"{self.transport} da dong; ket noi lai va upload lai.")
        message = {"id": uuid.uuid4().hex, "action": action}
        if code is not None:
            if len(code.encode("utf-8")) > 65536:
                raise ValueError("Kich ban vuot qua 64 KiB UTF-8.")
            message["code"] = code
        queue = Queue()
        with self._lock:
            self._pending[message["id"]] = queue
        try:
            data = encode(message)
            with self._write_lock:
                if self.closed or self.connection.write(data) != len(data):
                    raise OSError(f"Khong gui day du du lieu {self.transport}.")
            try:
                return queue.get(timeout=timeout)
            except Empty as error:
                raise TimeoutError("Pi chua phan hoi. Khong tu gui lai RUN; kiem tra ket noi.") from error
        finally:
            with self._lock:
                self._pending.pop(message["id"], None)

    def _read(self):
        decoder = LineDecoder()
        try:
            while not self.closed:
                for frame in decoder.feed(self.connection.read(4096)):
                    try:
                        reply = json.loads(frame.decode("utf-8"))
                        if not isinstance(reply, dict):
                            continue
                    except (ValueError, UnicodeError):
                        continue
                    with self._lock:
                        queue = self._pending.get(reply.get("id"))
                    if queue is not None:
                        queue.put(reply)
                    elif "event" in reply:
                        self.notify(reply)
        except Exception as error:
            if not self.closed:
                self._fail(error)
                self.notify({"event": "disconnected", "error": str(error)})

    def _heartbeat(self):
        while not self._done.wait(1):
            try:
                reply = self.request("ping", timeout=2)
                if not reply.get("ok"):
                    raise OSError(reply.get("error", "Heartbeat loi"))
            except Exception as error:
                self._fail(error)
                self.notify({"event": "disconnected", "error": str(error)})
                return

    def close(self):
        try:
            if not self.closed:
                try:
                    self.request("stop", timeout=1)
                except Exception:
                    pass
        finally:
            self._fail(f"{self.transport} da dong.")
            self.connection.close()
            for thread in self._threads:
                if thread is not current_thread():
                    thread.join(2)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Vi du COM5; khong truyen de chon tu danh sach")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--list", action="store_true", help="Chi liet ke cong COM")
    args = parser.parse_args(argv)
    if args.baud <= 0:
        parser.error("Baud phai duong.")
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        print("Cai dependency: python -m pip install -r requirements-usb.txt")
        return 1
    ports = list(list_ports.comports())
    if args.list or not args.port:
        for index, port in enumerate(ports, start=1):
            print(f"{index}. {port.device}: {port.description}")
        if args.list:
            return 0
        if not ports:
            print("Chua co cong COM. Cau hinh USB gadget tren Pi, cam cap du lieu, roi thu lai.")
            return 1
        try:
            index = int(input("Chon so cong COM cua Pi: "))
            if not 1 <= index <= len(ports):
                raise ValueError
            args.port = ports[index - 1].device
        except (ValueError, EOFError):
            print("So cong khong hop le.")
            return 1
        except KeyboardInterrupt:
            return 130
    client = connection = None
    try:
        connection = serial.serial_for_url(args.port, baudrate=args.baud, timeout=0.1, write_timeout=1)
        connection.reset_input_buffer()
        client = USBClient(connection)
        client.start()
        print("Pi:", client.request("status"))
        run_console(client)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, serial.SerialException, ValueError) as error:
        print(f"Loi USB: {error}")
        return 1
    finally:
        if client is not None:
            client.close()
        elif connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
