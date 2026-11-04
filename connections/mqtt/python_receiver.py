"""Experimental MQTT -> ConvertBlockToPython -> .py -> child process -> robot_sdk.

Start from the stem workspace: python3 -m vehicle_testing.connections.mqtt.python_receiver
--broker BROKER_IP --device-id ROBOT_UUID --dry-run. Use --run explicitly for hardware.
"""

import argparse
from functools import partial
import json
import logging
import math
from pathlib import Path
import sys
from threading import Event
import time

# Direct script execution starts inside connections/mqtt, outside the package root.
# Resolve from this file so the caller's working directory does not matter.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from vehicle_testing.connections.mqtt.receiver import ScratchReceiver, create_client
from vehicle_testing.runtime.python_program import prepare_program, execute_python_program


logger = logging.getLogger(__name__)
DEFAULT_PROGRAM_DIR = Path(__file__).resolve().parents[2] / 'received_programs'


class PythonMqttReceiver(ScratchReceiver):
    def __init__(self, device_id, *, program_dir=DEFAULT_PROGRAM_DIR, dry_run=True,
                 timeout=30, speed=0.25, lift_start_lowered=False, executor=None):
        self.program_dir = Path(program_dir)
        self._faulted = Event()
        self._dry_run = dry_run
        self._lift_start_lowered = lift_start_lowered
        self._lift_used = False
        super().__init__(device_id, executor=executor or partial(
            execute_python_program, dry_run=dry_run, timeout=timeout, speed=speed,
            notify=self._notify, lift_start_lowered=lift_start_lowered))
        self._client = None

    def _notify(self, event):
        if event.get('event') == 'unsafe_stop':
            self._faulted.set()
        client = self._client
        if client is None:
            return
        topic = f'device/{self.device_id}/block' if event.get('event') == 'block' else f'device/{self.device_id}/log'
        body = {**event, 'status': 'executing', 'timestamp': time.time()}
        try:
            client.publish(topic, json.dumps(body, ensure_ascii=False), qos=1, retain=False)
        except Exception:
            logger.exception('Không gửi được sự kiện Python về broker.')

    def _handle_message(self, client, message):
        self._client = client
        if message.topic != self.topic_code:
            return super()._handle_message(client, message)
        if self._busy or self._faulted.is_set():
            logger.warning('Từ chối upload: đang chạy hoặc cần kiểm tra sau dừng cưỡng bức.')
            return
        if getattr(message, 'dup', False):
            return
        self.current_program = None
        if message.retain:
            logger.warning('Bỏ qua CODE retained; cần upload mới từ FE.')
            return
        try:
            source = message.payload.decode('utf-8')
            self.current_program = prepare_program(source, self.program_dir)
            if ('hand' in self.current_program.resources and not self._dry_run
                    and (not self._lift_start_lowered or self._lift_used)):
                self.current_program = None
                raise ValueError('Nâng thật cần hạ tay trước, mở receiver với --lift-start-lowered; '
                                 'mỗi lần mở receiver chỉ cho một lượt nâng.')
        except (ValueError, OSError) as error:
            logger.error('UPLOAD ERROR: %s', error)
            self._publish_status(client, 'error')
            return
        logger.info('UPLOADED | %s | chờ Chạy Code, chưa chạy xe.', self.current_program.path)
        self._publish_status(client, 'uploaded')

    def _start_execution(self, client, program):
        if not self._dry_run and 'hand' in program.resources:
            self._lift_used = True
        super()._start_execution(client, program)
        if self._busy:
            self.current_program = None  # One execute per upload, including repeated button clicks.


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broker', required=True, help='Cùng broker backend dùng; chỉ IP/hostname')
    parser.add_argument('--port', type=int, default=1883)
    parser.add_argument('--device-id', required=True, help='UUID đúng robot FE đang chọn')
    parser.add_argument('--program-dir', type=Path, default=DEFAULT_PROGRAM_DIR)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--speed', type=float, default=0.25, help='PWM tiến/lùi trong (0,1]')
    parser.add_argument('--lift-start-lowered', action='store_true',
                        help='Xác nhận tay đang hạ; cho một lượt nâng thật rồi phải đặt lại và mở receiver lại')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--run', action='store_true', help='Cho phép phần cứng thật')
    modes.add_argument('--dry-run', action='store_true', help='Mô phỏng (mặc định)')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or '://' in args.broker or not args.broker.strip():
        parser.error('Broker chỉ gồm IP/hostname; port từ 1 đến 65535.')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('Timeout phải hữu hạn > 0.')
    if not math.isfinite(args.speed) or not 0 < args.speed <= 1:
        parser.error('Speed phải trong (0, 1].')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', stream=sys.stdout)
    try:
        receiver = PythonMqttReceiver(args.device_id, program_dir=args.program_dir,
                                      dry_run=not args.run, timeout=args.timeout, speed=args.speed,
                                      lift_start_lowered=args.lift_start_lowered)
    except ValueError as error:
        parser.error(str(error))
    client = None
    result = 0
    try:
        logger.info('PYTHON PIPELINE: %s; broker=%s:%s; UUID=%s',
                    'PHAN CUNG THAT' if args.run else 'MO PHONG', args.broker, args.port, args.device_id)
        client = create_client(receiver)
        client.connect_async(args.broker, args.port, keepalive=30)
        client.loop_start()
        while True:
            receiver.publish_heartbeat(client)
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info('Đang Stop và đóng Python receiver...')
        result = 130
    except Exception:
        logger.exception('Receiver lỗi.')
        result = 1
    finally:
        receiver.close()
        if client is not None:
            client.disconnect()
            client.loop_stop()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
