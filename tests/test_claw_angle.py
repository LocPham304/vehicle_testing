#!/usr/bin/env python3
"""Standalone claw-angle experiment on BCM 12, Python 3.10+.

Inside vehicle_testing on the Pi, with its virtual environment:
    .venv/bin/python -m pip install adafruit-circuitpython-motor rpi-hardware-pwm
    .venv/bin/python tests/test_claw_angle.py --dry-run
    .venv/bin/python tests/test_claw_angle.py --inspect
    .venv/bin/python tests/test_claw_angle.py --run

This single file can also be copied elsewhere; no project imports are needed.
Commands execute immediately (no 'chay'). In hardware mode, run ONE movement,
then release PWM and exit while the reported full-open fault is investigated:
    mo_cang 60       absolute target 60 degrees over the default 2 seconds
    dong_cang 20 3  absolute target 20 degrees over 3 seconds
    dong_cang 0     closed; release PWM after settling
    thoat          release PWM and exit; Ctrl+C does the same

Both command names set an absolute target in [0, 90], not a relative amount.
Proposed test profile: logical 0 = closed (2400 us), 90 = open (1000 us).
These user-requested endpoints are UNCALIBRATED and not a verified MG90S spec.
These labels are not measured physical angles; calibrate against the mechanism.
Prepare the claw closed at logical 0 before starting; otherwise provide its
KNOWN logical position using --start-angle. Startup emits no position request.

PWM is always released after a movement. The reported full-open fault means
Neither the previous 500/1611 us nor the new 1000/2400 us are measured endpoints;
do not repeat hardware tests
until servo type, starting pulse and physical endpoints have been checked.
After release, the real position is unknown. Do not reuse the requested angle
as a measured starting position for another movement.

Stop main.py and any other servo program before testing. Keep the current
dtoverlay=pwm,pin=12,func=4 and audio configuration; no boot changes are made.
Discover the Pi 4 brcm,bcm2835-pwm provider, channel 0, 50 Hz. Reject pwm-gpio
providers (the lift on BCM 18) and ambiguous discovery before any PWM writes.
Do not run another PWM0 output on BCM 18. No I2C, motors or lift output is opened.
API: https://docs.circuitpython.org/projects/motor/en/latest/api.html
"""

import argparse
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path


MIN_ANGLE = 0.0
MAX_ANGLE = 90.0
BCM_PIN = 12
PWM_CHANNEL = 0
FREQUENCY_HZ = 50
# User-requested experimental profile; not measured on the attached mechanism.
# The first pulse at the assumed startup position 0 is now 2400 us.
CLOSE_PULSE_US = 2400
OPEN_PULSE_US = 1000
UPDATE_SECONDS = 0.02
SETTLE_SECONDS = 0.1


def number_in_range(value, low, high, label):
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} phai trong [{low:g}, {high:g}].")
    return number


def parse_command(line, default_seconds):
    parts = line.lower().split()
    if len(parts) not in (2, 3) or parts[0] not in ("mo_cang", "dong_cang"):
        raise ValueError("Cu phap: mo_cang <goc> [giay] hoac dong_cang <goc> [giay].")
    angle = number_in_range(parts[1], MIN_ANGLE, MAX_ANGLE, "Goc (do)")
    seconds = number_in_range(
        parts[2] if len(parts) == 3 else default_seconds, 0.2, 60, "Thoi gian (giay)"
    )
    return angle, seconds


def angle_to_pulse_us(angle):
    angle = number_in_range(angle, MIN_ANGLE, MAX_ANGLE, "Goc (do)")
    return CLOSE_PULSE_US + angle / MAX_ANGLE * (OPEN_PULSE_US - CLOSE_PULSE_US)


def find_claw_chip(root=Path("/sys/class/pwm")):
    """Read-only discovery of the existing Pi 4 hardware PWM provider."""
    matches = []
    for chip in root.glob("pwmchip*"):
        suffix = chip.name.removeprefix("pwmchip")
        if not suffix.isdecimal():
            continue
        try:
            compatible = (chip / "device/of_node/compatible").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        if b"brcm,bcm2835-pwm" not in compatible:
            continue
        if int((chip / "npwm").read_text(encoding="ascii")) <= PWM_CHANNEL:
            raise RuntimeError(f"Khong co kenh PWM0 tai {chip}.")
        matches.append(int(suffix))
    if len(matches) != 1:
        raise RuntimeError(
            f"Can dung 1 driver brcm,bcm2835-pwm cua cang, tim thay {len(matches)}. "
            "Kiem tra overlay pwm,pin=12,func=4 va so pwmchip; khong dung chip "
            "pwm-gpio cua nang/ha. Khong tu dong sua cau hinh boot."
        )
    return matches[0]


def inspect_claw(root=Path("/sys/class/pwm"),
                 boot_config=Path("/boot/firmware/config.txt")):
    """Read metadata/state and pin mux only; never open or enable PWM."""
    print("CLAW_DIAG_V1 | CHI DOC - KHONG PHAT XUNG")
    print(f"File: {Path(__file__).resolve()}")
    print(f"Anh xa THU NGHIEM, CHUA HIEU CHINH: khep 0 do = {CLOSE_PULSE_US:g} us, "
          f"mo 90 do = {OPEN_PULSE_US:g} us.")
    print("Sysfs la trang thai driver, KHONG phai phep do xung/goc that.")
    result = 0
    try:
        selected = find_claw_chip(root)
        print(f"Driver cang duoc nhan dien: pwmchip{selected}, PWM0.")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"CAN KIEM TRA DRIVER: {error}")
        result = 1
    for chip in sorted(root.glob("pwmchip*")):
        try:
            compatible = (chip / "device/of_node/compatible").read_bytes()
            label = compatible.replace(b"\0", b", ").decode("ascii", errors="replace").strip(", ")
            channels = (chip / "npwm").read_text(encoding="ascii").strip()
            print(f"{chip.name}: compatible={label}; npwm={channels}")
            channel = chip / "pwm0"
            if not channel.is_dir():
                print("  pwm0 chua export; khong export trong che do nay.")
                continue
            values = {}
            for name in ("enable", "period", "duty_cycle", "polarity"):
                path = channel / name
                if path.exists():
                    values[name] = path.read_text(encoding="ascii").strip()
                    print(f"  {name}={values[name]}")
            period = int(values.get("period", "0"))
            duty = int(values.get("duty_cycle", "0"))
            if period > 0:
                print(f"  Theo driver: {1_000_000_000 / period:g} Hz; "
                      f"duty_cycle={duty / 1000:g} us (chi co xung neu enable=1).")
        except (OSError, ValueError) as error:
            print(f"  Khong doc duoc {chip}: {error}")
            result = 1
    print("Boot config luu tren dia (co the khac cau hinh dang chay):")
    try:
        for number, line in enumerate(boot_config.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("#") and ("pwm" in stripped or "audio=" in stripped):
                print(f"  {number}: {stripped}")
    except OSError as error:
        print(f"  Khong doc duoc {boot_config}: {error}")
    pinctrl = shutil.which("pinctrl")
    if pinctrl is None:
        print("Khong co pinctrl; chua xac dinh duoc chuc nang GPIO12/GPIO18.")
    else:
        for pin in (12, 18):
            try:
                state = subprocess.run([pinctrl, "get", str(pin)], capture_output=True,
                                       text=True, timeout=3, check=False)
                print(f"pinctrl get {pin}: {(state.stdout or state.stderr).strip()}")
                if state.returncode:
                    result = 1
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f"Khong doc duoc GPIO{pin}: {error}")
                result = 1
    return result


class KernelPWMAdapter:
    """The 16-bit duty_cycle/frequency interface required by Adafruit Servo."""

    frequency = FREQUENCY_HZ

    def __init__(self, hardware_pwm, chip):
        self._pwm = hardware_pwm(pwm_channel=PWM_CHANNEL, hz=self.frequency, chip=chip)
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
        elif value != self._duty:
            duty = value / 0xFFFF * 100
            if self._running:
                self._pwm.change_duty_cycle(duty)
            else:
                self._pwm.start(duty)
                self._running = True
            self._duty = value

    def release(self):
        self._pwm.stop()
        self._duty = 0
        self._running = False


class ClawExperiment:
    def __init__(self, start_angle=0, dry_run=True):
        self.angle = number_in_range(start_angle, MIN_ANGLE, MAX_ANGLE, "Goc ban dau")
        self.dry_run = dry_run
        self._adapter = None
        self._servo = None

    def _open(self):
        if self.dry_run or self._servo is not None:
            return
        try:
            from adafruit_motor.servo import Servo
            from rpi_hardware_pwm import HardwarePWM
        except ImportError as error:
            raise RuntimeError(
                "Cai trong venv cua Pi: python -m pip install "
                "adafruit-circuitpython-motor rpi-hardware-pwm"
            ) from error
        chip = find_claw_chip()
        print(f"Mo PWM phan cung BCM 12: pwmchip{chip}, kenh 0, 50 Hz.")
        self._adapter = KernelPWMAdapter(HardwarePWM, chip)
        self._adapter.release()
        self._servo = Servo(
            self._adapter, actuation_range=90,
            min_pulse=OPEN_PULSE_US, max_pulse=CLOSE_PULSE_US,
        )

    def _set_angle(self, angle):
        if not self.dry_run:
            # Increasing logical angle OPENS the claw: pulse decreases.
            self._servo.angle = MAX_ANGLE - angle

    def move(self, angle, seconds):
        angle = number_in_range(angle, MIN_ANGLE, MAX_ANGLE, "Goc (do)")
        seconds = number_in_range(seconds, 0.2, 60, "Thoi gian (giay)")
        if self.angle is None:
            raise RuntimeError("Khong biet goc that sau nha PWM/loi/ngat; dung thu va kiem tra lai moc vi tri.")
        start = self.angle
        steps = math.ceil(seconds / UPDATE_SECONDS)
        print(f"Yeu cau {start:g} -> {angle:g} do / {seconds:g}s, "
              f"{steps} buoc; xung dich danh nghia {angle_to_pulse_us(angle):.1f} us.")
        try:
            self._open()
            print(f"Moc dau GIA DINH: {start:g} do -> {angle_to_pulse_us(start):.1f} us; "
                  "khong phai vi tri do duoc.")
            self._set_angle(start)
            for step in range(1, steps + 1):
                if not self.dry_run:
                    time.sleep(seconds / steps)
                progress = step / steps
                eased = progress ** 3 * (10 - 15 * progress + 6 * progress ** 2)
                position = angle if step == steps else start + (angle - start) * eased
                self._set_angle(position)
            if not self.dry_run:
                time.sleep(SETTLE_SECONDS)
            self.release()
            self.angle = angle if self.dry_run else None
        except (Exception, KeyboardInterrupt):
            self.angle = None
            try:
                self.release()
            except Exception as error:
                print(f"Khong tat duoc PWM sau loi: {error}", file=sys.stderr)
            raise
        print("Da gui goc dich va nha PWM; KHONG xac nhan goc that hoac da sua loi mo het.")

    def release(self):
        if self._adapter is not None:
            self._adapter.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Phat PWM that tren BCM 12")
    mode.add_argument("--dry-run", action="store_true", help="Mo phong (mac dinh)")
    mode.add_argument("--inspect", action="store_true",
                      help="Chi doc driver, trang thai PWM, pin mux; khong phat xung")
    parser.add_argument("--start-angle", default=0, type=float, help="Goc hien tai gia dinh, 0..90")
    parser.add_argument("--seconds", default=2, type=float, help="Thoi gian moi lenh, 0.2..60")
    parser.add_argument("--release-after-move", action="store_true",
                        help="Tuong thich lenh cu; hien luon nha PWM sau moi lenh")
    args = parser.parse_args(argv)
    if args.inspect:
        return inspect_claw()
    try:
        number_in_range(args.seconds, 0.2, 60, "Thoi gian")
        claw = ClawExperiment(args.start_angle, dry_run=not args.run)
    except ValueError as error:
        parser.error(str(error))
    if args.run and not sys.stdin.isatty():
        parser.error("Che do --run can terminal truc tiep de dung bang Ctrl+C.")
    print("TEST CANG BCM 12 | " + ("PWM THAT" if args.run else "MO PHONG - khong mo GPIO"))
    print(f"Goc ban dau gia dinh: {claw.angle:g} do. Chuan bi cang dung moc truoc lenh dau.")
    print("Nhap: mo_cang 60 | dong_cang 20 | dong_cang 0 3 | thoat. Lenh chay ngay.")
    if args.run:
        print("DANG CHAN DOAN LOI MO HET: chi thu mot chuyen dong, nha PWM va thoat.")
    result = 0
    try:
        while True:
            line = input("cang> ").strip()
            if line.lower() in ("thoat", "exit", "quit"):
                break
            if not line:
                continue
            try:
                angle, seconds = parse_command(line, args.seconds)
            except ValueError as error:
                print(f"Lenh khong hop le: {error}")
                continue
            claw.move(angle, seconds)
            if args.run:
                break
    except EOFError:
        pass
    except KeyboardInterrupt:
        print("\nDa ngat; khong tu dong dong/mo cang.")
        result = 130
    except Exception as error:
        print(f"Loi: {error}", file=sys.stderr)
        result = 1
    finally:
        try:
            claw.release()
        except Exception as error:
            print(f"Khong tat duoc PWM: {error}", file=sys.stderr)
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
