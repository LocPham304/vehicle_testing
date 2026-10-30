"""Inspect PWM device-tree metadata and calibration; never export/enable PWM."""

import argparse
from pathlib import Path

from vehicle_testing.config import (
    CLAW_BCM_PIN, CLAW_PWM_CHIP, SERVO_BCM_PIN, SERVO_CALIBRATED,
    SERVO_DOWN_PULSE_US, SERVO_UP_PULSE_US,
)
from vehicle_testing.hardware.pwm import (
    PWM_SYSFS_ROOT, find_gpio_pwm_chip, find_hardware_pwm_chip,
)
from vehicle_testing.hardware.servos import validate_hand_calibration


def main(argv=None, *, sysfs_root: Path = PWM_SYSFS_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        hw_chip = find_hardware_pwm_chip(CLAW_PWM_CHIP, sysfs_root)
    except RuntimeError as error:
        print(f"LOI: {error}")
        return 1
    print(
        f"BCM {SERVO_BCM_PIN} (ALT5) & BCM {CLAW_BCM_PIN} (ALT0): "
        f"pwmchip{hw_chip}, channel 0 (chia se PWM0 phan cung)."
    )
    if hw_chip != CLAW_PWM_CHIP:
        print(
            f"Ghi chu: CLAW_PWM_CHIP={CLAW_PWM_CHIP} nhung driver brcm,bcm2835-pwm "
            f"dang o pwmchip{hw_chip}; chuong trinh se tu chon pwmchip{hw_chip}."
        )
    try:
        gpio_chip = find_gpio_pwm_chip(SERVO_BCM_PIN, sysfs_root)
    except RuntimeError:
        pass
    else:
        print(
            f"Ghi chu: phat hien pwmchip{gpio_chip} (pwm-gpio tren BCM {SERVO_BCM_PIN}) "
            "nhung main.py da chuyen sang PWM0 phan cung de tranh rung/giat."
        )
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
