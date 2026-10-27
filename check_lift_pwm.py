"""Inspect PWM device-tree metadata and calibration; never export/enable PWM."""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing.config import (
    CLAW_PWM_CHIP, SERVO_BCM_PIN, SERVO_CALIBRATED,
    SERVO_DOWN_PULSE_US, SERVO_UP_PULSE_US,
)
from vehicle_testing.gpio_pwm import PWM_SYSFS_ROOT, find_gpio_pwm_chip, validate_claw_pwm_chip
from vehicle_testing.hand import validate_hand_calibration


def main(argv=None, *, sysfs_root: Path = PWM_SYSFS_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        chip = find_gpio_pwm_chip(SERVO_BCM_PIN, sysfs_root)
    except RuntimeError as error:
        print(f"LOI: {error}")
        return 1
    print(f"BCM {SERVO_BCM_PIN}: pwmchip{chip}, channel 0 (pwm-gpio, PWM phan mem trong kernel).")
    try:
        validate_claw_pwm_chip(CLAW_PWM_CHIP, sysfs_root)
    except RuntimeError as error:
        print(f"CAN KIEM TRA CANG: {error}")
        for candidate in Path(sysfs_root).glob("pwmchip*"):
            suffix = candidate.name.removeprefix("pwmchip")
            if suffix.isdecimal():
                try:
                    validate_claw_pwm_chip(int(suffix), sysfs_root)
                except RuntimeError:
                    continue
                print(f"Driver PWM phan cung cua cang: {candidate.name}; kiem tra CLAW_PWM_CHIP.")
    else:
        print(f"Cang BCM 12: pwmchip{CLAW_PWM_CHIP}, channel 0 (PWM phan cung).")
    try:
        validate_hand_calibration()
    except ValueError as error:
        print(f"CAU HINH XUNG KHONG HOP LE: {error}")
    else:
        if SERVO_CALIBRATED:
            print("Da khai bao hieu chinh; phep kiem tra nay khong do vi tri co khi.")
        else:
            print("CHE DO THU: nang/ha da cho phep chay; hai moc xung chua do tren xe.")
        print(f"Ha -10 do: {SERVO_DOWN_PULSE_US:g} us; nang 80 do: {SERVO_UP_PULSE_US:g} us.")
    print("Chi doc metadata; khong export kenh, khong phat xung, khong di chuyen servo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
