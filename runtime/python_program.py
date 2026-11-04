"""Convert and save FE input, then supervise the generated file in a child Python."""

from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
import uuid

from vehicle_testing.helpers.ConvertBlockToPython import (
    ConvertBlockToPython, Command, get_required_resources, parse_commands,
)
from vehicle_testing.runtime.runner import ExecutionCancelled


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PythonProgram:
    program_id: str
    source_path: Path
    path: Path
    command_count: int
    resources: tuple[str, ...]


def prepare_program(source, program_dir):
    events = parse_commands(source, keep_block_ids=True)
    # Do not discover an unsupported glyph after an earlier motor action.
    from vehicle_testing.hardware.displays.matrix import text_columns
    for event in events:
        if isinstance(event, Command) and event.name == 'led_strip':
            text_columns(event.arg)
    generated = ConvertBlockToPython().convert(source)
    folder = Path(program_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    program_id = uuid.uuid4().hex
    original = folder / f'{program_id}.fe.txt'
    target = folder / f'{program_id}.py'
    original.write_text(source, encoding='utf-8')
    target.write_text(generated, encoding='utf-8')
    logger.info('CONVERT OK | file=%s\n%s', target, generated)
    return PythonProgram(program_id, original, target,
                         sum(isinstance(event, Command) for event in events), get_required_resources(events))


def execute_python_program(program, *, dry_run=True, stop_event, notify=lambda event: None,
                           timeout=30.0, speed=0.25, lift_start_lowered=False):
    if stop_event.is_set():
        raise ExecutionCancelled('Đã dừng trước khi mở chương trình.')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout phải là số giây hữu hạn > 0.')
    with TemporaryDirectory(prefix='stem-python-run-') as directory:
        stop_file = Path(directory) / 'stop'
        args = [sys.executable, '-u', '-B', '-m', 'vehicle_testing.runtime.python_worker',
                '--file', str(program.path), '--stop-file', str(stop_file), '--speed', str(speed),
                '--dry-run' if dry_run else '--run']
        if lift_start_lowered:
            args.append('--lift-start-lowered')
        environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        process = subprocess.Popen(args, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                   errors='replace', start_new_session=os.name == 'posix')
        lines = Queue()

        def read_output():
            with process.stdout:
                for line in process.stdout:
                    lines.put(line.rstrip('\r\n'))

        reader = Thread(target=read_output, name='python-output', daemon=True)
        reader.start()
        started = time.monotonic()
        cancellation_started = None
        timed_out = forced = unsafe_stop = False
        try:
            while process.poll() is None or reader.is_alive() or not lines.empty():
                now = time.monotonic()
                if process.poll() is None and (stop_event.is_set() or now - started >= timeout):
                    if cancellation_started is None:
                        timed_out = not stop_event.is_set()
                        stop_file.touch()
                        cancellation_started = now
                    elif now - cancellation_started >= 3:
                        # SIGTERM is handled by the worker so normal cleanup can still run.
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            forced = True
                            process.kill()
                            process.wait(timeout=2)
                try:
                    line = lines.get(timeout=0.02)
                except Empty:
                    continue
                logger.info('PYTHON | %s', line)
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    event = None
                if not isinstance(event, dict) or event.get('event') not in ('block', 'unsafe_stop'):
                    event = {'event': 'log', 'message': line}
                if event.get('event') == 'unsafe_stop':
                    unsafe_stop = True
                notify({**event, 'program_id': program.program_id})
            returncode = process.wait()
            if forced:
                notify({'event': 'unsafe_stop', 'message': 'Buộc kill; chưa xác nhận PWM đã về 0.'})
                raise RuntimeError('Buộc kill Python; kiểm tra/dừng nguồn motor trước khi thử tiếp.')
            if unsafe_stop:
                raise RuntimeError('SDK báo lỗi dừng thiết bị; cần kiểm tra phần cứng trước khi thử tiếp.')
            if timed_out:
                raise TimeoutError(f'Chương trình vượt {timeout:g} giây.')
            if returncode not in (0, 130):
                raise RuntimeError(f'Python kết thúc với mã lỗi {returncode}.')
            if stop_event.is_set() or returncode == 130:
                raise ExecutionCancelled('Chương trình đã dừng.')
        finally:
            if process.poll() is None:
                stop_file.touch()
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                    notify({'event': 'unsafe_stop', 'message': 'Dừng cưỡng bức trong cleanup.'})
            reader.join(timeout=2)
