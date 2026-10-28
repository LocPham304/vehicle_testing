"""Read a TRIG/ECHO ultrasonic sensor without opening motor or servo hardware.

Run from the repository root: python3 -m vehicle_testing.ultrasonic
Or inside vehicle_testing: python3 ultrasonic.py
Each read returns raw centimeters or raises TimeoutError; it does not stop motors.
Callers should space readings apart (the CLI uses 0.2 seconds between readings).
"""

import argparse
import importlib
import logging
import math
import sys
import time
from collections.abc import Callable
from pathlib import Path

# Match main.py: support both direct script execution and package imports.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing.config import (
    ULTRASONIC_ECHO_PIN,
    ULTRASONIC_READ_INTERVAL_SECONDS,
    ULTRASONIC_TIMEOUT_SECONDS,
    ULTRASONIC_TRIG_PIN,
)


logger = logging.getLogger(__name__)


class UltrasonicSensor:
    """Own two BCM GPIO pins and measure ECHO pulse width with bounded waits."""

    def __init__(
        self,
        trig: int = ULTRASONIC_TRIG_PIN,
        echo: int = ULTRASONIC_ECHO_PIN,
        timeout: float = ULTRASONIC_TIMEOUT_SECONDS,
        *,
        gpio=None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if trig == echo or any(type(pin) is not int or not 2 <= pin <= 27 for pin in (trig, echo)):
            raise ValueError("TRIG/ECHO phai la hai GPIO BCM khac nhau trong khoang 2..27.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout phai la so huu han lon hon 0, don vi giay.")
        if gpio is None:
            try:
                gpio = importlib.import_module("RPi.GPIO")
            except (ImportError, RuntimeError) as error:
                raise RuntimeError("Can Raspberry Pi va thu vien RPi.GPIO de doc cam bien.") from error

        self._gpio = gpio
        self._trig, self._echo = trig, echo
        self._timeout = timeout
        self._clock, self._sleep = monotonic, sleeper
        self._configured: list[int] = []
        self._closed = False
        try:
            gpio.setmode(gpio.BCM)
            gpio.setup(trig, gpio.OUT, initial=gpio.LOW)
            self._configured.append(trig)
            gpio.setup(echo, gpio.IN)
            self._configured.append(echo)
            self._sleep(0.1)
        except BaseException:
            try:
                self.close()
            except Exception:
                logger.exception("Loi don GPIO sau khi khoi tao cam bien that bai.")
            raise

    def _wait_for_echo(self, level: int) -> float:
        deadline = self._clock() + self._timeout
        while self._gpio.input(self._echo) != level:
            if self._clock() >= deadline:
                edge = "len HIGH" if level else "xuong LOW"
                raise TimeoutError(f"ECHO khong {edge} trong {self._timeout * 1000:g} ms.")
        return self._clock()

    def read_distance_cm(self) -> float:
        """Return a single raw reading; out-of-range values are not clamped."""
        if self._closed:
            raise RuntimeError("Cam bien da dong.")
        if self._gpio.input(self._echo):
            raise TimeoutError("ECHO dang HIGH truoc khi do; kiem tra day va cam bien.")
        self._gpio.output(self._trig, self._gpio.LOW)
        self._sleep(0.000002)
        self._gpio.output(self._trig, self._gpio.HIGH)
        try:
            self._sleep(0.00001)
        finally:
            self._gpio.output(self._trig, self._gpio.LOW)
        started = self._wait_for_echo(1)
        ended = self._wait_for_echo(0)
        return (ended - started) * 34300 / 2

    def close(self) -> None:
        """Release only sensor pins, leaving other robot GPIO owners alone."""
        if not self._closed:
            self._closed = True
            if self._configured:
                self._gpio.cleanup(self._configured)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Doc cam bien sieu am, in khoang cach theo cm.")
    parser.add_argument("--trig", type=int, default=ULTRASONIC_TRIG_PIN, help="GPIO BCM TRIG")
    parser.add_argument("--echo", type=int, default=ULTRASONIC_ECHO_PIN, help="GPIO BCM ECHO")
    args = parser.parse_args(argv)
    try:
        with UltrasonicSensor(trig=args.trig, echo=args.echo) as sensor:
            print(f"TRIG=GPIO{args.trig}, ECHO=GPIO{args.echo} (BCM). Nhan Ctrl+C de thoat.", flush=True)
            while True:
                stamp = time.strftime("%H:%M:%S")
                try:
                    distance = sensor.read_distance_cm()
                    note = "" if 3 <= distance <= 400 else " (ngoai khoang 3-400 cm; kiem tra lai)"
                    print(f"[{stamp}] Khoang cach: {distance:.1f} cm{note}", flush=True)
                except TimeoutError as error:
                    print(f"[{stamp}] KHONG DOC DUOC: {error}", flush=True)
                time.sleep(ULTRASONIC_READ_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nDa dung doc cam bien.")
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Loi cam bien: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
