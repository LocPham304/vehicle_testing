"""Probe one candidate BCM pin without importing the vehicle or motor driver.

This does not establish board connector mapping or confirm physical movement.
"""

import argparse
import importlib
import math
import time
from typing import Callable


def main(argv: list[str] | None = None,
         sleeper: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=int, required=True, choices=(12, 13, 18, 19),
                        help="BCM pin candidate from the repository's GPIO examples; not a port number")
    parser.add_argument("--dry-run", action="store_true", help="Print requests without opening GPIO")
    parser.add_argument("--pulse-us", type=float,
                        help="Send one raw pulse (1000..2000 us); disconnect mechanical linkage first")
    parser.add_argument("--seconds", type=float, default=2,
                        help="Hold each request for 0.05..3 seconds (default: 2)")
    args = parser.parse_args(argv)
    if args.pulse_us is not None and (not math.isfinite(args.pulse_us) or not 1000 <= args.pulse_us <= 2000):
        parser.error("--pulse-us phai la so huu han trong 1000..2000 us.")
    if not math.isfinite(args.seconds) or not 0.05 <= args.seconds <= 3:
        parser.error("--seconds phai la so huu han trong 0.05..3 giay.")
    print(f"{'MO PHONG' if args.dry_run else 'THU GPIO'}: BCM {args.pin}, PWM 50 Hz.")
    print("Thoat main.py va cac chuong trinh dieu khien servo truoc khi thu that.")
    if args.pulse_us is not None:
        print("THU XUNG THO: chi chay khi da tach lien ket co khi cua servo khoi cang.")
        print("1500 us chi la moc thu; khong dam bao dung hoac la vi tri an toan cua servo nay.")
        requests = [(f"xung tho {args.pulse_us:g} us", args.pulse_us)]
    else:
        print("Chi gui goc yeu cau 40 -> 30 -> 40; khong do duoc servo da quay hay chua.")
        requests = [(f"goc yeu cau {angle} do", 500 + angle / 180 * 2000) for angle in (40, 30, 40)]
    if args.dry_run:
        for description, pulse_us in requests:
            print(f"BCM {args.pin}: {description}; xung {pulse_us:.2f} us, {args.seconds:g} giay")
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
        for description, pulse_us in requests:
            pwm.ChangeDutyCycle(pulse_us / 20000 * 100)
            print(f"BCM {args.pin}: {description}; xung {pulse_us:.2f} us, {args.seconds:g} giay", flush=True)
            sleeper(args.seconds)
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
