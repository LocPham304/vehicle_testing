#!/usr/bin/env python3
"""Standalone lift-angle experiment on BCM 18 (Python 3.10+).

Install on the Pi, inside its virtual environment:
    python -m pip install adafruit-circuitpython-motor rpi-hardware-pwm

Run from raspberry-py, or copy this single file to the Pi:
    python stem_project_test/test_lift_angle.py --dry-run
    python stem_project_test/test_lift_angle.py --run
    python stem_project_test/test_lift_angle.py --run --hold --seconds 3

Commands execute immediately, without 'chay':
    nang 60       absolute target 60 degrees, NOT 60 seconds or +60 degrees
    ha 20         absolute target 20 degrees
    nang 90 3     target 90 degrees over 3 seconds
    thoat         release PWM and exit; Ctrl+C does the same

Prepare the arm at the lowered position before starting (assumed angle 0).
If it is already at another KNOWN position, pass --start-angle <0..90>.
There is no position sensor: reported angles are requests, not measurements.
The existing 450/1400 us endpoints are relabelled 0/90 for this experiment;
measure/calibrate the mechanism before treating these as physical degrees.
PWM is released after each move, like the current lift configuration.
Use --hold to keep PWM between moves; it is always released on exit/error.
After manual movement or sag under load, restart with the actual start angle.

Keep the existing dtoverlay=pwm-gpio,gpio=18 and stop other lift programs.
Do not route hardware PWM0 to BCM 18: the claw uses PWM0 on BCM 12.
ServoKit requires PCA9685; here we use its Adafruit Servo class with a
kernel pwm-gpio adapter, leaving the motor PCA9685 at 0x40 untouched.
No project imports, config changes, motor output, I2C access or auto sweep.
API: https://docs.circuitpython.org/projects/motor/en/latest/api.html
"""

import argparse
import math
import sys
import time
from pathlib import Path


MIN_ANGLE = 0.0
MAX_ANGLE = 90.0
BCM_PIN = 18
FREQUENCY_HZ = 50
# Reuse the current lift's tested endpoints, not Adafruit's generic defaults.
DOWN_PULSE_US = 450
UP_PULSE_US = 1400
UPDATE_SECONDS = 0.02
SETTLE_SECONDS = 0.1


def number_in_range(value, low, high, label):
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} phai trong [{low:g}, {high:g}].")
    return number


def parse_command(line, default_seconds):
    parts = line.lower().split()
    if len(parts) not in (2, 3) or parts[0] not in ("nang", "ha"):
        raise ValueError("Cu phap: nang <goc> [giay] hoac ha <goc> [giay].")
    angle = number_in_range(parts[1], MIN_ANGLE, MAX_ANGLE, "Goc (do)")
    seconds = number_in_range(
        parts[2] if len(parts) == 3 else default_seconds, 0.2, 60, "Thoi gian (giay)"
    )
    return angle, seconds


def find_lift_chip(root=Path("/sys/class/pwm")):
    """Read-only device-tree discovery; never guess a PWM chip number."""
    matches = []
    for chip in root.glob("pwmchip*"):
        suffix = chip.name.removeprefix("pwmchip")
        if not suffix.isdecimal():
            continue
        node = chip / "device/of_node"
        try:
            compatible = (node / "compatible").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        if b"pwm-gpio" not in compatible:
            continue
        gpios = (node / "gpios").read_bytes()
        if len(gpios) != 12:
            raise RuntimeError(f"Metadata gpios khong hop le: {chip}")
        if int.from_bytes(gpios[4:8], "big") != BCM_PIN:
            continue
        if int((chip / "npwm").read_text(encoding="ascii")) != 1:
            raise RuntimeError(f"Can pwm-gpio mot kenh: {chip}")
        matches.append(int(suffix))
    if len(matches) != 1:
        raise RuntimeError(
            f"Can dung 1 pwm-gpio BCM 18, tim thay {len(matches)}. "
            "Kiem tra dtoverlay=pwm-gpio,gpio=18 trong /boot/firmware/config.txt "
            "va reboot; khong dung pwm-2chan thay the."
        )
    return matches[0]


class KernelPWMAdapter:
    """The frequency/duty_cycle interface needed by adafruit_motor.servo."""

    frequency = FREQUENCY_HZ

    def __init__(self, hardware_pwm, chip):
        self._pwm = hardware_pwm(pwm_channel=0, hz=self.frequency, chip=chip)
        self._duty = 0
        self._running = False

    @property
    def duty_cycle(self):
        return self._duty

    @duty_cycle.setter
    def duty_cycle(self, value):
        if not isinstance(value, int) or not 0 <= value <= 0xFFFF:
            raise ValueError("Duty cycle phai la so nguyen 16-bit.")
        if value == 0:
            self.release()
            return
        if value != self._duty:
            duty_percent = value / 0xFFFF * 100
            if self._running:
                self._pwm.change_duty_cycle(duty_percent)
            else:
                self._pwm.start(duty_percent)
                self._running = True
            self._duty = value

    def release(self):
        self._pwm.stop()
        self._duty = 0
        self._running = False


class LiftExperiment:
    def __init__(self, start_angle=0, dry_run=True, hold=False):
        self.angle = number_in_range(start_angle, MIN_ANGLE, MAX_ANGLE, "Goc ban dau")
        self.dry_run = dry_run
        self.hold = hold
        self._adapter = None
        self._servo = None

    def _open(self):
        if self.dry_run or self._servo is not None:
            return
        # Lazy imports: --help, dry-run and invalid commands need no hardware libs.
        try:
            from adafruit_motor.servo import Servo
            from rpi_hardware_pwm import HardwarePWM
        except ImportError as error:
            raise RuntimeError(
                "Cai trong venv cua Pi: python -m pip install "
                "adafruit-circuitpython-motor rpi-hardware-pwm"
            ) from error
        chip = find_lift_chip()
        print(f"Mo pwm-gpio BCM 18: pwmchip{chip}, kenh 0, 50 Hz.")
        self._adapter = KernelPWMAdapter(HardwarePWM, chip)
        self._adapter.release()
        self._servo = Servo(
            self._adapter, actuation_range=90,
            min_pulse=DOWN_PULSE_US, max_pulse=UP_PULSE_US,
        )

    def _set_angle(self, angle):
        if not self.dry_run:
            self._servo.angle = angle

    def move(self, angle, seconds):
        angle = number_in_range(angle, MIN_ANGLE, MAX_ANGLE, "Goc (do)")
        seconds = number_in_range(seconds, 0.2, 60, "Thoi gian (giay)")
        if self.angle is None:
            raise RuntimeError("Mat moc vi tri sau loi/ngat; dat lai tay va khoi dong lai.")
        start = self.angle
        steps = math.ceil(seconds / UPDATE_SECONDS)
        pulse = DOWN_PULSE_US + angle / MAX_ANGLE * (UP_PULSE_US - DOWN_PULSE_US)
        print(f"Yeu cau {start:g} -> {angle:g} do / {seconds:g}s, "
              f"{steps} buoc; xung dich danh nghia {pulse:.1f} us.")
        try:
            self._open()
            self._set_angle(start)
            for step in range(1, steps + 1):
                if not self.dry_run:
                    time.sleep(seconds / steps)
                progress = step / steps
                # Quintic easing: zero speed and acceleration at both ends.
                eased = progress ** 3 * (10 - 15 * progress + 6 * progress ** 2)
                position = angle if step == steps else start + (angle - start) * eased
                self._set_angle(position)
            if not self.dry_run:
                time.sleep(SETTLE_SECONDS)
            if not self.hold:
                self.release()
            self.angle = angle
        except (Exception, KeyboardInterrupt):
            self.angle = None
            try:
                self.release()
            except Exception as error:
                print(f"Khong tat duoc PWM sau loi: {error}", file=sys.stderr)
            raise
        print("Da gui goc dich (khong do goc that). " +
              ("Giu PWM." if self.hold else "Nha PWM; vi tri tiep theo la gia dinh."))

    def release(self):
        if self._adapter is not None:
            self._adapter.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Phat PWM that tren BCM 18")
    mode.add_argument("--dry-run", action="store_true", help="Mo phong (mac dinh)")
    parser.add_argument("--start-angle", default=0, type=float, help="Goc hien tai gia dinh, 0..90")
    parser.add_argument("--seconds", default=2, type=float, help="Thoi gian moi lenh, 0.2..60")
    parser.add_argument("--hold", action="store_true", help="Giu PWM giua cac lenh")
    args = parser.parse_args(argv)
    try:
        number_in_range(args.seconds, 0.2, 60, "Thoi gian")
        lift = LiftExperiment(args.start_angle, dry_run=not args.run, hold=args.hold)
    except ValueError as error:
        parser.error(str(error))
    if args.run and not sys.stdin.isatty():
        parser.error("Che do --run can terminal truc tiep de dung bang Ctrl+C.")
    print("TEST BCM 18 | " + ("PWM THAT" if args.run else "MO PHONG - khong mo GPIO"))
    print(f"Goc ban dau gia dinh: {lift.angle:g} do. Dat tay dung moc truoc lenh dau.")
    print("Nhap: nang 60 | ha 20 | nang 90 3 | thoat. Lenh chay ngay.")
    result = 0
    try:
        while True:
            line = input("goc> ").strip()
            if line.lower() in ("thoat", "exit", "quit"):
                break
            if not line:
                continue
            try:
                angle, seconds = parse_command(line, args.seconds)
            except ValueError as error:
                print(f"Lenh khong hop le: {error}")
                continue
            lift.move(angle, seconds)
    except EOFError:
        pass
    except KeyboardInterrupt:
        print("\nDa ngat; khong tu dong ha tay.")
        result = 130
    except Exception as error:
        print(f"Loi: {error}", file=sys.stderr)
        result = 1
    finally:
        try:
            lift.release()
        except Exception as error:
            print(f"Khong tat duoc PWM: {error}", file=sys.stderr)
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
