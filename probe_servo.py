"""Probe one candidate BCM pin without importing the vehicle or motor driver.

This does not establish board connector mapping or confirm physical movement.
"""

import argparse
import importlib
import time
from typing import Callable


def main(argv: list[str] | None = None,
         sleeper: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=int, required=True, choices=(12, 13, 18, 19),
                        help="BCM pin candidate from the repository's GPIO examples; not a port number")
    parser.add_argument("--dry-run", action="store_true", help="Print requests without opening GPIO")
    args = parser.parse_args(argv)
    print(f"{'MO PHONG' if args.dry_run else 'THU GPIO'}: BCM {args.pin}, PWM 50 Hz.")
    print("Thoat main.py va cac chuong trinh dieu khien servo truoc khi thu that.")
    print("Chi gui goc yeu cau 40 -> 30 -> 40; khong do duoc servo da quay hay chua.")
    if args.dry_run:
        for angle in (40, 30, 40):
            print(f"BCM {args.pin}: goc {angle} do; xung {500 + angle / 180 * 2000:.2f} us")
        return 0

    gpio = None
    configured = False
    pwm = None
    result = 0
    try:
        gpio = importlib.import_module("RPi.GPIO")
        gpio.setmode(gpio.BCM)
        configured = True
        gpio.setup(args.pin, gpio.OUT)
        pwm = gpio.PWM(args.pin, 50)
        pwm.start(0)
        for angle in (40, 30, 40):
            pulse_us = 500 + angle / 180 * 2000
            pwm.ChangeDutyCycle(pulse_us / 20000 * 100)
            print(f"BCM {args.pin}: goc yeu cau {angle} do; xung {pulse_us:.2f} us", flush=True)
            sleeper(2)
    except KeyboardInterrupt:
        print("Da nhan Ctrl+C.")
        result = 130
    except Exception as error:
        print(f"Loi thu servo: {error}")
        result = 1
    finally:
        try:
            try:
                if pwm is not None:
                    try:
                        pwm.ChangeDutyCycle(0)
                    finally:
                        pwm.stop()
            finally:
                if configured:
                    gpio.cleanup(args.pin)
        except KeyboardInterrupt:
            print("Ngat khi don GPIO.")
            result = 130
        except Exception as error:
            print(f"Loi giai phong GPIO: {error}")
            result = 1
    print("Da ket thuc phep thu; PWM khong con duoc yeu cau giu tay.")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
