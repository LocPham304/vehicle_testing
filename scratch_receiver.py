"""Receive Scratch as data; preview by default or run through the hardware API.

Inside vehicle_testing:
  python3 scratch_receiver.py --file examples/scratch_sample.txt
  python3 scratch_receiver.py --broker BROKER_IP --device-id DEVICE_UUID
  python3 scratch_receiver.py --broker BROKER_IP --device-id DEVICE_UUID --run
"""

import argparse
import logging
from pathlib import Path
import sys
from threading import Event, RLock, Thread
import time
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing.scratch_parser import ScratchParseError, ScratchProgram, format_program, parse_program


logger = logging.getLogger(__name__)


class ScratchReceiver:
    """Cache validated immutable programs from one device's MQTT topics."""

    def __init__(self, device_id: str, *, executor=None):
        if not device_id or any(char in "/+#" or char.isspace() or ord(char) < 32 for char in device_id):
            raise ValueError("Device ID phai khac rong, khong chua /, +, # hay khoang trang.")
        self.device_id = device_id
        self.topic_code = f"device/{device_id}/code"
        self.topic_execute = f"device/{device_id}/execute"
        self.topic_status = f"device/{device_id}/status"
        self.topic_stop = f"device/{device_id}/stop"
        self.current_program: ScratchProgram | None = None
        self.executor = executor
        self._lock = RLock()
        self._busy = False
        self._closing = False
        self._worker = None
        self._stop_event = None

    @property
    def busy(self):
        with self._lock:
            return self._busy

    def wait_for_execution(self, timeout=None):
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join(timeout)
            return not worker.is_alive()
        return True

    def close(self):
        # Do not tear down MQTT or GPIO until the worker has stopped and cleaned up.
        with self._lock:
            self._closing = True
            self.current_program = None
            if self._stop_event is not None:
                self._stop_event.set()
        self.wait_for_execution()

    def _publish_status(self, client, status):
        try:
            if client.is_connected():
                info = client.publish(self.topic_status, status, qos=1, retain=False)
                if info.rc != 0:
                    logger.warning("Khong gui duoc status %s: %s", status, info.rc)
        except Exception as error:
            logger.warning("Khong gui duoc status %s: %s", status, error)

    def _start_execution(self, client, program):
        # Caller holds _lock; reserve ownership before starting a worker.
        if self._busy:
            logger.warning("Robot dang ban; bo qua EXECUTE, khong xep hang chay lai.")
            return
        self._stop_event = Event()
        self._busy = True
        self._worker = Thread(target=self._execute, args=(client, program, self._stop_event),
                              name=f"scratch-run-{self.device_id}", daemon=False)
        self._publish_status(client, "executing")
        try:
            self._worker.start()
        except Exception:
            self._worker = None
            self._busy = False
            self._publish_status(client, "error")
            logger.exception("Khong khoi dong duoc luong thuc thi.")

    def _execute(self, client, program, stop_event):
        from vehicle_testing.scratch_runner import ExecutionCancelled

        status = "done"
        try:
            logger.info("EXECUTE: bat dau %d lenh cua kich ban da nhan qua MQTT.", program.command_count)
            self.executor(program, stop_event=stop_event)
            if stop_event.is_set():
                status = "stopped"
        except ExecutionCancelled:
            status = "stopped"
        except Exception:
            status = "error"
            logger.exception("Loi khi thuc thi kich ban MQTT.")
        finally:
            # Publish completion only after execute_program has closed its devices.
            with self._lock:
                self._busy = False
                self._publish_status(client, status)
                logger.info("EXECUTE ket thuc: %s.", status)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error("Broker tu choi ket noi: %s", reason_code)
            return
        topics = [(self.topic_code, 1), (self.topic_execute, 1)]
        if self.executor is not None:
            topics.append((self.topic_stop, 1))
        result, _ = client.subscribe(topics)
        if result != 0:
            logger.error("Khong gui duoc yeu cau subscribe: %s", result)
        else:
            logger.info("Da ket noi broker; dang subscribe %s va %s.", self.topic_code, self.topic_execute)

    def on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            logger.error("Broker tu choi subscribe: %s", reason_codes)
        else:
            logger.info("San sang nhan Scratch. %s", "EXECUTE qua runner; /stop de dung."
                        if self.executor is not None else "CHI PARSE/PREVIEW, khong chay phan cung.")

    def on_connect_fail(self, client, userdata):
        logger.warning("Chua ket noi duoc broker; se tu dong thu lai.")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        with self._lock:
            self.current_program = None
            if self._stop_event is not None:
                self._stop_event.set()
        if reason_code.is_failure:
            logger.warning("Mat ket noi broker; da xoa kich ban dang cho. Can upload lai sau khi ket noi.")

    def on_message(self, client, userdata, message):
        with self._lock:
            if not self._closing:
                self._handle_message(client, message)

    def _handle_message(self, client, message):
        topics = (self.topic_code, self.topic_execute)
        if self.executor is not None:
            topics += (self.topic_stop,)
        if message.topic not in topics:
            return
        if message.topic == self.topic_code:
            # Never fall back to an older valid program after a bad replacement.
            self.current_program = None
        try:
            payload = message.payload.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Payload tren %s khong phai UTF-8; bo qua.", message.topic)
            return
        if message.topic == self.topic_code:
            try:
                program = parse_program(payload)
                if self.executor is not None:
                    from vehicle_testing.scratch_runner import validate_program
                    validate_program(program)
            except (ScratchParseError, ValueError) as error:
                logger.warning("Upload khong hop le: %s. Da xoa kich ban dang cho.", error)
                return
            self.current_program = program
            logger.info("Nhan CODE (%d byte).\n%s", len(message.payload), format_program(program))
            logger.info("Da giu kich ban trong RAM; cho /execute de %s.",
                        "chay qua runner" if self.executor is not None else "in lai ban preview")
        elif message.topic == self.topic_stop:
            if message.retain or getattr(message, "dup", False) or payload != "stop":
                logger.warning("Bo qua STOP retained/trung lap hoac payload khac 'stop'.")
                return
            if self._busy:
                self._stop_event.set()
                logger.info("Nhan STOP; da yeu cau dung kich ban dang chay.")
        else:
            if message.retain:
                logger.warning("Bo qua EXECUTE retained; can lenh moi sau upload.")
                return
            if self.executor is not None and getattr(message, "dup", False):
                logger.warning("Bo qua EXECUTE MQTT danh dau trung lap.")
                return
            if payload != "execute":
                logger.warning("Payload EXECUTE chua duoc ho tro: %r (can 'execute').", payload)
                return
            program = self.current_program
            if program is None:
                logger.warning("Nhan EXECUTE nhung chua co kich ban hop le; can upload lai.")
                return
            if self.executor is None:
                logger.info("PREVIEW EXECUTE - CHI IN KICH BAN, KHONG DIEU KHIEN PHAN CUNG.\n%s", format_program(program))
            else:
                self._start_execution(client, program)

    def publish_heartbeat(self, client):
        with self._lock:
            self._publish_status(client, "executing" if self._busy else "idle")


def create_client(receiver: ScratchReceiver):
    try:
        import paho.mqtt.client as mqtt
    except ImportError as error:
        raise RuntimeError(
            "Thieu paho-mqtt. Trong vehicle_testing, chay: "
            "python3 -m pip install -r requirements-mqtt.txt"
        ) from error
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"scratch-receiver-{receiver.device_id}-{uuid.uuid4().hex[:8]}",
        clean_session=True,
        protocol=mqtt.MQTTv311,
    )
    client.connect_timeout = 10
    client.reconnect_delay_set(min_delay=2, max_delay=30)
    client.on_connect = receiver.on_connect
    client.on_subscribe = receiver.on_subscribe
    client.on_connect_fail = receiver.on_connect_fail
    client.on_disconnect = receiver.on_disconnect
    client.on_message = receiver.on_message
    return client


def main(argv=None):
    # Windows redirected stdout can default to cp1252, which cannot print Vietnamese.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", type=Path, help="Doc va parse file cuc bo, khong ket noi MQTT")
    mode.add_argument("--broker", help="IP/hostname MQTT broker, khong gom tcp:// hay so cong")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--device-id", help="UUID robot, phai trung voi robot dang chon tren web")
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument("--run", action="store_true", help="/execute chay motor/LED that tren Pi")
    execution.add_argument("--dry-run", action="store_true", help="/execute chay runner mo phong, khong mo phan cung")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port phai nam trong khoang 1..65535.")
    if args.file is not None and (args.run or args.dry_run):
        parser.error("--run/--dry-run dung voi --broker; chay file bang scratch_runner.py.")
    if args.broker is not None and (not args.device_id or not args.broker.strip() or "://" in args.broker):
        parser.error("Che do MQTT can --broker IP/hostname va --device-id UUID.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", stream=sys.stdout)
    if args.file is not None:
        try:
            program = parse_program(args.file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ScratchParseError) as error:
            logger.error("Khong parse duoc file: %s", error)
            return 1
        print(format_program(program))
        print("CHI PARSE/PREVIEW; khong chay lenh, khong ket noi MQTT hay phan cung.")
        return 0
    try:
        executor = None
        if args.run or args.dry_run:
            from functools import partial
            from vehicle_testing.scratch_runner import execute_program
            executor = partial(execute_program, dry_run=args.dry_run)
        receiver = ScratchReceiver(args.device_id, executor=executor)
    except ValueError as error:
        parser.error(str(error))
    client = None
    result = 0
    try:
        label = "CHAY PHAN CUNG THAT" if args.run else "RUNNER MO PHONG" if args.dry_run else "PARSE/PREVIEW"
        logger.info("CHE DO %s. Tien/lui: giay; quay: do; led_strip: chuoi goc.", label)
        logger.info("Broker %s:%d; UUID=%s.", args.broker, args.port, args.device_id)
        client = create_client(receiver)
        client.connect_async(args.broker, args.port, keepalive=30)
        client.loop_start()
        while True:
            receiver.publish_heartbeat(client)
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Dang dong receiver...")
        result = 130
    except Exception as error:
        logger.error("Receiver khong the tiep tuc: %s", error)
        result = 1
    finally:
        try:
            receiver.close()
        except KeyboardInterrupt:
            logger.warning("Nhan ngat trong khi cho luong thuc thi dung.")
            result = 130
        except Exception as error:
            logger.error("Loi dong luong thuc thi: %s", error)
            result = 1
        finally:
            if client is not None:
                try:
                    try:
                        client.disconnect()
                    finally:
                        client.loop_stop()
                except Exception as error:
                    logger.error("Loi dong ket noi MQTT: %s", error)
                    result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
