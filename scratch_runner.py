"""Run a local Scratch scenario, without MQTT or a web server.

Inside vehicle_testing:
  python3 scratch_runner.py             # run examples/scratch_sample.txt on Pi
  python3 scratch_runner.py --dry-run   # simulate immediately, no hardware
"""

import argparse
from contextlib import ExitStack
import logging
from pathlib import Path
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing.controller import DryRunOutput, MotorController, PCA9685Output
from vehicle_testing.display_link import DisplayLink
from vehicle_testing.scratch_parser import BlockMarker, parse_program
from vehicle_testing.test_displays import text_columns, text_frames


DEFAULT_FILE = Path(__file__).resolve().parent / "examples" / "scratch_sample.txt"
logger = logging.getLogger(__name__)


class ExecutionCancelled(Exception):
    """A requested stop, distinct from a hardware failure."""


def cancellable_sleep(stop_event):
    """Wake timed motor/LED waits immediately when the owner requests stop."""
    def sleep(seconds):
        if stop_event.wait(seconds):
            raise ExecutionCancelled("Da yeu cau dung kich ban.")
    return sleep


def validate_program(program):
    """Check every text glyph before any movement or hardware initialization."""
    for event in program.events:
        if not isinstance(event, BlockMarker) and event.command == "led_strip":
            try:
                text_columns(event.value)
            except ValueError as error:
                raise ValueError(f"Dong {event.line}: {error}") from error


class MatrixTextDisplay:
    """Own TM1640 GPIO and show each string for one finite pass."""

    def __init__(self, *, gpio=None, link_factory=DisplayLink, sleeper=time.sleep):
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except (ImportError, RuntimeError) as error:
                raise RuntimeError("Can Raspberry Pi va RPi.GPIO de chay LED; tren PC dung --dry-run.") from error
        self.gpio = gpio
        self._sleep = sleeper
        self._pins = []
        self._link = None
        self._closed = False
        try:
            gpio.setmode(gpio.BCM)
            for pin in (7, 5):
                gpio.setup(pin, gpio.OUT, initial=gpio.HIGH)
                self._pins.append(pin)
            self._link = link_factory(gpio, 7, 5, ack=False)
            self._link.show([0] * 16, 2)
        except BaseException:
            try:
                self.close()
            except Exception:
                logger.exception("Khong don duoc GPIO sau loi khoi tao LED.")
            raise

    def show_text(self, text):
        normalized, columns = text_columns(text)
        logger.info("LED MATRIX: %r -> %s (mot luot)", text, normalized or "(xoa)")
        for frame in text_frames(columns):
            self._link.write_frame(frame)
            self._sleep(0.1 if len(columns) > 16 else 1.0)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._link is not None:
                self._link.send([0x80])
        finally:
            if self._pins:
                self.gpio.cleanup(self._pins)


class DryRunMatrix:
    def show_text(self, text):
        normalized, _ = text_columns(text)
        logger.info("[MO PHONG] LED MATRIX: %r -> %s (mot luot)", text, normalized or "(xoa)")


def open_motor(*, sleeper=time.sleep):
    output = PCA9685Output()
    try:
        return MotorController(output, sleeper=sleeper)
    except BaseException:
        output.close()
        raise


def report_block(block_id):
    logger.info("BLOCK: %r", block_id)


def run_program(program, motor, matrix, reporter=report_block, *, stop_event=None):
    """Dispatch validated data in order; always request a motor stop on exit.

    Resource ownership belongs to the caller. No received Python is evaluated.
    """
    validate_program(program)
    try:
        for event in program.events:
            if stop_event is not None and stop_event.is_set():
                raise ExecutionCancelled("Da yeu cau dung kich ban.")
            if isinstance(event, BlockMarker):
                reporter(event.block_id)
                continue
            logger.info("CHAY dong %d: %s:%s; block=%r", event.line, event.command, event.value, event.block_id)
            if event.command == "move_forward":
                motor.move("forward", event.value)
            elif event.command == "move_backward":
                motor.move("backward", event.value)
            elif event.command == "turn_left":
                motor.turn_left(event.value)
            elif event.command == "turn_right":
                motor.turn_right(event.value)
            elif event.command == "led_strip":
                matrix.show_text(event.value)
            else:
                raise ValueError(f"Lenh chua duoc ho tro: {event.command!r}")
    finally:
        if motor is not None:
            motor.stop()


def execute_program(program, *, dry_run=False, stop_event=None, reporter=report_block):
    """Own all hardware for one parsed program; also usable by the MQTT worker."""
    validate_program(program)
    sleep = cancellable_sleep(stop_event) if stop_event is not None else time.sleep
    if stop_event is not None:
        sleep(0)
    needs_motor = any(not isinstance(event, BlockMarker) and event.command != "led_strip" for event in program.events)
    needs_matrix = any(not isinstance(event, BlockMarker) and event.command == "led_strip" for event in program.events)
    with ExitStack() as resources:
        motor = matrix = None
        if needs_motor:
            if dry_run:
                motor = MotorController(DryRunOutput(), sleeper=lambda seconds: None)
            else:
                motor = open_motor(sleeper=sleep) if stop_event is not None else open_motor()
            resources.callback(motor.close)
            motor.stop()
        if stop_event is not None:
            sleep(0)
        if needs_matrix:
            if dry_run:
                matrix = DryRunMatrix()
            else:
                matrix = MatrixTextDisplay(sleeper=sleep) if stop_event is not None else MatrixTextDisplay()
                resources.callback(matrix.close)
        run_program(program, motor, matrix, reporter, stop_event=stop_event)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="File Scratch UTF-8; mac dinh examples/scratch_sample.txt")
    parser.add_argument("--dry-run", action="store_true", help="Mo phong thu tu lenh, khong mo phan cung, khong cho theo thoi gian")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stdout)
    try:
        program = parse_program(args.file.read_text(encoding="utf-8-sig"))
        validate_program(program)
        print(f"KICH BAN HOP LE: {program.marker_count} block marker, {program.command_count} lenh.", flush=True)
        logger.info("%s; file=%s", "MO PHONG - KHONG MO PHAN CUNG" if args.dry_run else "CHAY PHAN CUNG - Ctrl+C de dung", args.file)
        execute_program(program, dry_run=args.dry_run)
        logger.info("HOAN TAT kich ban; da dong thiet bi.")
        return 0
    except KeyboardInterrupt:
        logger.info("Da nhan Ctrl+C; da yeu cau dung va giai phong thiet bi.")
        return 130
    except Exception as error:
        logger.error("Khong chay duoc kich ban: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
