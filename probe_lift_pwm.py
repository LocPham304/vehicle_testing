"""Manually probe a small lift pulse window using the BCM 18 kernel provider.

No pulse is emitted at launch. Each +/- command requests one short burst,
then disables PWM. This does not measure shaft position or detect a stop.
"""

import argparse
import importlib
import math
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing.config import SERVO_BCM_PIN, SERVO_PWM_FREQUENCY_HZ
from vehicle_testing.gpio_pwm import find_gpio_pwm_chip


def create_lift_pwm():
    chip = find_gpio_pwm_chip(SERVO_BCM_PIN)
    module = importlib.import_module("rpi_hardware_pwm")
    return module.HardwarePWM(pwm_channel=0, hz=SERVO_PWM_FREQUENCY_HZ, chip=chip)


def main(argv=None, *, input_fn=input, sleeper=time.sleep, pwm_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-us", required=True, type=float,
                        help="Reference pulse only; NOT emitted at launch")
    parser.add_argument("--min-us", type=float, help="Window lower bound; default start - 100 us")
    parser.add_argument("--max-us", type=float, help="Window upper bound; default start + 100 us")
    parser.add_argument("--step-us", type=int, choices=(5, 10, 20), default=10)
    parser.add_argument("--on-seconds", type=float, default=0.04,
                        help="Requested PWM burst duration, 0.02..0.1 s (default 0.04)")
    parser.add_argument("--dry-run", action="store_true", help="Print only, never create PWM")
    args = parser.parse_args(argv)
    lower = args.min_us if args.min_us is not None else max(500, args.start_us - 100)
    upper = args.max_us if args.max_us is not None else min(2500, args.start_us + 100)
    if (not all(math.isfinite(value) for value in (lower, upper, args.start_us))
            or not 500 <= lower <= args.start_us <= upper <= 2500 or lower >= upper
            or upper - lower > 200):
        parser.error("Cua so phai trong 500..2500 us, rong toi da 200 us, va chua --start-us.")
    if not math.isfinite(args.on_seconds) or not 0.02 <= args.on_seconds <= 0.1:
        parser.error("--on-seconds phai trong 0.02..0.1 giay.")
    if not args.dry_run and input_fn is input and not sys.stdin.isatty():
        parser.error("Thu that can nhap tung lenh truc tiep o terminal; khong pipe kich ban.")

    print(f"{'MO PHONG' if args.dry_run else 'THU XUNG NGAN'}: BCM {SERVO_BCM_PIN}, {SERVO_PWM_FREQUENCY_HZ} Hz.")
    print(f"Moc tham chieu {args.start_us:g} us: chua phat xung. Cua so [{lower:g}, {upper:g}] us.")
    print(f"Nhap + hoac - roi Enter: doi {args.step_us} us, phat {args.on_seconds:g} giay roi tat PWM.")
    print("Enter rong xem moc; thoat/Ctrl+C ket thuc. Khong tu quet hoac tu sua config.py.")
    print("Thoat main.py truoc. Xung ngan van co the tao luc vao diem chan; neu giat, dung phep thu.")
    print("Tat PWM khong giu luc do tay. Cong cu khong do vi tri hoac do rong xung thuc te.")

    current = args.start_us
    pwm = None
    status = 0
    try:
        while True:
            command = input_fn("xung> ").strip().lower()
            if command in ("thoat", "q", "quit"):
                break
            if not command:
                print(f"Moc dang chon: {current:g} us (khong phat xung).")
                continue
            if command not in ("+", "-"):
                print("Chi nhan +, -, Enter rong hoac thoat; khong gui xung.")
                continue
            candidate = current + (args.step_us if command == "+" else -args.step_us)
            if not lower <= candidate <= upper:
                print(f"Ngoai cua so [{lower:g}, {upper:g}] us; khong gui xung.")
                continue
            print(f"{'MO PHONG' if args.dry_run else 'YEU CAU'}: {candidate:g} us, {args.on_seconds:g} giay.", flush=True)
            if not args.dry_run:
                if pwm is None:
                    pwm = (pwm_factory or create_lift_pwm)()
                    pwm.stop()
                try:
                    pwm.start(candidate / (1_000_000 / SERVO_PWM_FREQUENCY_HZ) * 100)
                    sleeper(args.on_seconds)
                finally:
                    pwm.stop()
                print("Da gui yeu cau tat PWM.")
            current = candidate
    except EOFError:
        pass
    except KeyboardInterrupt:
        print("Da nhan Ctrl+C.")
        status = 130
    except Exception as error:
        print(f"Loi thu PWM: {error}")
        status = 1
    finally:
        if pwm is not None:
            try:
                pwm.stop()
            except KeyboardInterrupt:
                status = 130
            except Exception as error:
                print(f"Khong tat duoc PWM: {error}")
                status = 1
    print(f"Moc xung cuoi da chon: {current:g} us; chua xac nhan day la mot vi tri tay an toan.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
