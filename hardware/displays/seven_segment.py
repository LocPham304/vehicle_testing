"""Reusable four-digit TM1637 display and manual/ultrasonic test session.

Inside vehicle_testing: python3 seven_segment.py
From its parent: python3 -m vehicle_testing.hardware.displays.seven_segment
Numbers select manual mode; auto selects distance; empty input clears; thoat exits.
"""

import argparse
import importlib
import logging
import math
import select
import sys
import time

from vehicle_testing.config import (
    SEVEN_SEGMENT_BRIGHTNESS, SEVEN_SEGMENT_CLK_PIN, SEVEN_SEGMENT_DIO_PIN,
    ULTRASONIC_ECHO_PIN, ULTRASONIC_READ_INTERVAL_SECONDS, ULTRASONIC_TRIG_PIN,
)
from vehicle_testing.hardware.displays.link import DisplayLink
from vehicle_testing.hardware.ultrasonic import UltrasonicSensor


logger = logging.getLogger(__name__)
DIGITS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)


def _brightness(value):
    if type(value) is not int or not 0 <= value <= 7:
        raise ValueError("Do sang phai la so nguyen trong khoang 0..7.")


class SevenSegmentDisplay:
    """Own CLK/DIO only. Numbers, brightness and cleanup are source-independent."""

    def __init__(self, clk=SEVEN_SEGMENT_CLK_PIN, dio=SEVEN_SEGMENT_DIO_PIN,
                 brightness=SEVEN_SEGMENT_BRIGHTNESS, *, gpio=None):
        if clk == dio or any(type(pin) is not int or not 2 <= pin <= 27 for pin in (clk, dio)):
            raise ValueError("CLK/DIO phai la hai GPIO BCM khac nhau trong khoang 2..27.")
        _brightness(brightness)
        if gpio is None:
            try:
                gpio = importlib.import_module("RPi.GPIO")
            except (ImportError, RuntimeError) as error:
                raise RuntimeError("Can Raspberry Pi va RPi.GPIO de dieu khien LED.") from error
        self._gpio = gpio
        self._pins = []
        self._closed = False
        self._warned_ack = False
        self._link = DisplayLink(gpio, clk, dio, ack=True)
        try:
            gpio.setmode(gpio.BCM)
            for pin in (clk, dio):
                gpio.setup(pin, gpio.OUT, initial=gpio.HIGH)
                self._pins.append(pin)
            self._link.show([0] * 4, brightness)
            self._check_ack()
        except BaseException:
            try:
                self.close()
            except Exception:
                logger.exception("Khong don duoc GPIO sau loi khoi tao LED.")
            raise

    def _check_open(self):
        if self._closed:
            raise RuntimeError("LED da dong.")

    def _check_ack(self):
        if self._link.missing_ack and not self._warned_ack:
            logger.warning("TM1637 khong ACK day du; kiem tra nguon va day CLK/DIO.")
            self._warned_ack = True

    def _write(self, frame):
        self._check_open()
        self._link.write_frame(frame)
        self._check_ack()

    def show_number(self, value):
        """Display 0..9999, zero-padded; finite fractions round half up."""
        self._check_open()
        if type(value) not in (int, float) or not 0 <= value <= 9999 or not math.isfinite(value):
            raise ValueError("Gia tri phai la so huu han trong khoang 0..9999.")
        number = math.floor(value + 0.5)
        self._write([DIGITS[int(digit)] for digit in f"{number:04d}"])

    def show_error(self):
        self._write([0x40] * 4)

    def clear(self):
        self._write([0] * 4)

    def set_brightness(self, value):
        self._check_open()
        _brightness(value)
        self._link.send([0x88 | value])
        self._check_ack()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if len(self._pins) == 2:
                self._link.send([0x80])
        finally:
            if self._pins:
                self._gpio.cleanup(self._pins)

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def read_line(timeout):
    """Poll the Linux/SSH terminal so measurements can continue between inputs."""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\r\n")


def run_session(display, *, reader=None, sensor_factory=None, monotonic=time.monotonic,
                interval=ULTRASONIC_READ_INTERVAL_SECONDS, start_auto=False):
    """One writer owns the LED; sensor hardware is acquired only for auto mode."""
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Chu ky doc phai la so huu han lon hon 0.")
    reader = read_line if reader is None else reader
    sensor_factory = UltrasonicSensor if sensor_factory is None else sensor_factory
    sensor = None
    automatic = False
    next_read = 0.0
    previous_ok = None
    pending = "auto" if start_auto else None
    print("Nhap so 0..9999; auto = khoang cach; Enter trong = xoa; thoat/Ctrl+C = dung.")
    print("led7> ", end="", flush=True)
    try:
        while True:
            if pending is not None:
                line, pending = pending, None
            else:
                timeout = min(0.1, max(0, next_read - monotonic())) if automatic else 0.1
                try:
                    line = reader(timeout)
                except EOFError:
                    return
            if line is not None:
                command = line.strip()
                if command.lower() == "thoat":
                    return
                if command.lower() == "auto":
                    try:
                        if sensor is None:
                            sensor = sensor_factory()
                    except (ValueError, RuntimeError, OSError) as error:
                        display.show_error()
                        print(f"Khong bat duoc auto: {error}. Van co the nhap so.")
                    else:
                        automatic = True
                        next_read = 0.0
                        previous_ok = None
                        print("AUTO: hien khoang cach theo cm (lam tron).")
                else:
                    try:
                        if command:
                            display.show_number(float(command))
                        else:
                            display.clear()
                    except ValueError as error:
                        print(f"Lenh khong hop le: {error}. Giu nguyen che do cu.")
                    else:
                        automatic = False
                        if sensor is not None:
                            sensor.close()
                            sensor = None
                        print("THU CONG" if command else "Da xoa man hinh.")
                print("led7> ", end="", flush=True)
            if automatic and monotonic() >= next_read:
                try:
                    display.show_number(sensor.read_distance_cm())
                except (TimeoutError, OSError, ValueError) as error:
                    display.show_error()
                    if previous_ok is not False:
                        print(f"\nKhong doc duoc khoang cach: {error}. LED hien ----; se thu lai.")
                        print("led7> ", end="", flush=True)
                    previous_ok = False
                else:
                    if previous_ok is False:
                        print("\nDa doc duoc khoang cach tro lai.")
                        print("led7> ", end="", flush=True)
                    previous_ok = True
                next_read = monotonic() + interval
    finally:
        if sensor is not None:
            sensor.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="LED 4 so: nhap so hoac go auto de doc sieu am.")
    parser.add_argument("--clk", type=int, default=SEVEN_SEGMENT_CLK_PIN)
    parser.add_argument("--dio", type=int, default=SEVEN_SEGMENT_DIO_PIN)
    parser.add_argument("--brightness", type=int, choices=range(8), default=SEVEN_SEGMENT_BRIGHTNESS)
    parser.add_argument("--number", type=int, default=0)
    parser.add_argument("--auto", action="store_true", help="Bat dau bang khoang cach sieu am")
    parser.add_argument("--trig", type=int, default=ULTRASONIC_TRIG_PIN)
    parser.add_argument("--echo", type=int, default=ULTRASONIC_ECHO_PIN)
    parser.add_argument("--interval", type=float, default=ULTRASONIC_READ_INTERVAL_SECONDS)
    args = parser.parse_args(argv)
    if not 0 <= args.number <= 9999 or not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("So ban dau phai trong khoang 0..9999; chu ky doc phai duong va huu han.")

    def sensor_factory():
        if {args.clk, args.dio} & {args.trig, args.echo}:
            raise ValueError("Chan cam bien trung CLK/DIO cua LED; can kiem tra day.")
        return UltrasonicSensor(trig=args.trig, echo=args.echo)

    try:
        with SevenSegmentDisplay(args.clk, args.dio, args.brightness) as display:
            display.show_number(args.number)
            print(f"LED CLK=BCM{args.clk}, DIO=BCM{args.dio}; sieu am TRIG=BCM{args.trig}, ECHO=BCM{args.echo}.")
            run_session(display, sensor_factory=sensor_factory, interval=args.interval, start_auto=args.auto)
    except KeyboardInterrupt:
        print("\nDa dung LED 7 doan.")
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Loi LED/cam bien: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
