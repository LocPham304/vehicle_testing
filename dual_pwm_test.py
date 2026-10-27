"""Standalone Pi 4 dual hardware PWM trial; no vehicle package is required.

BCM 12 = channel 0 (claw), BCM 13 = channel 1 (lift), both at 50 Hz.
Requires dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4 and correct wiring.
No position pulses are emitted at launch. Endpoints below are UNMEASURED.
"""

import argparse
import importlib
import math
import re
import subprocess
import sys
import time
from pathlib import Path

FREQUENCY_HZ = 50
LIFT_DOWN_US = 600.0  # Trial only: 3% duty, logical -10 degrees.
LIFT_UP_US = 1700.0   # Trial only: 8.5% duty, logical 80 degrees.
CLAW_OPEN_US = 500.0
CLAW_CLOSE_US = 1611.0
UPDATE_SECONDS = 0.02
SETTLE_SECONDS = 0.1
PWM_ROOT = Path("/sys/class/pwm")


def find_pwm_chip(requested=None, sysfs_root=PWM_ROOT):
    """Identify Pi 4 PWM0 at bus address 0x7e20c000, never a GPIO provider."""
    matches = []
    for chip in Path(sysfs_root).glob("pwmchip*"):
        suffix = chip.name.removeprefix("pwmchip")
        if not suffix.isdecimal() or (requested is not None and int(suffix) != requested):
            continue
        node = chip / "device/of_node"
        try:
            compatible = (node / "compatible").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError(f"Khong doc duoc {chip}: {error}") from error
        if b"brcm,bcm2835-pwm" not in compatible:
            continue
        try:
            reg = (node / "reg").read_bytes()
            if len(reg) != 8 or int.from_bytes(reg[:4], "big") != 0x7e20c000:
                continue
            if int((chip / "npwm").read_text(encoding="ascii").strip()) < 2:
                continue
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Metadata khong hop le tai {chip}: {error}") from error
        matches.append(int(suffix))
    if len(matches) != 1:
        raise RuntimeError(
            f"Can dung mot PWM phan cung Pi 4 co hai kenh, tim thay {len(matches)}. "
            "Kiem tra pwm-2chan va /sys/class/pwm; dung --chip N neu can chon ro."
        )
    return matches[0]


def read_pin(pin):
    return subprocess.run(["pinctrl", "get", str(pin)], check=True, capture_output=True,
                          text=True, timeout=5).stdout.strip()


def check_pins(pin_reader):
    for pin in (12, 13):
        state = pin_reader(pin)
        print(state)
        if not re.search(rf"^\s*{pin}:\s+a0\b", state, re.MULTILINE):
            raise RuntimeError(
                f"BCM {pin} chua o Alt0. Can overlay "
                "pwm-2chan,pin=12,func=4,pin2=13,func2=4 va reboot."
            )


def validate_pulses(down, up):
    if (not all(math.isfinite(value) and 500 <= value <= 2500 for value in (down, up))
            or down == up):
        raise ValueError("Hai moc xung phai khac nhau, huu han trong 500..2500 us.")


class DryPWM:
    def start(self, duty): pass
    def change_duty_cycle(self, duty): pass
    def stop(self): pass


class ServoTrial:
    def __init__(self, chip, *, pwm_factory, sleeper=time.sleep,
                 down_us=LIFT_DOWN_US, up_us=LIFT_UP_US, start="down"):
        validate_pulses(down_us, up_us)
        self.chip = chip
        self.factory = pwm_factory
        self.sleep = sleeper
        self.targets = {"nang": (1, up_us), "ha": (1, down_us),
                        "mo_cang": (0, CLAW_OPEN_US), "dong_cang": (0, CLAW_CLOSE_US)}
        self.positions = {0: CLAW_CLOSE_US, 1: down_us if start == "down" else up_us}
        self.outputs = {}
        self.last_pulses = {}
        self.running = set()
        self.closed = False

    def _write(self, channel, pulse, *, force=False):
        pulse = round(pulse)
        if not force and self.last_pulses.get(channel) == pulse:
            return
        duty = pulse / (1_000_000 / FREQUENCY_HZ) * 100
        if channel in self.running:
            self.outputs[channel].change_duty_cycle(duty)
        else:
            self.outputs[channel].start(duty)
            self.running.add(channel)
        self.last_pulses[channel] = pulse

    def move(self, command, seconds=4):
        if self.closed:
            raise RuntimeError("Phien thu da dong.")
        if command not in self.targets or not math.isfinite(seconds) or not 2 <= seconds <= 60:
            raise ValueError("Dung nang/ha/mo_cang/dong_cang [giay], thoi gian 2..60 giay.")
        channel, target = self.targets[command]
        start = self.positions[channel]
        if start == target:
            print(f"{command}: moc gia dinh da trung dich; khong gui them xung.")
            return
        print(f"{command}: CH{channel}, {start:g} -> {target:g} us trong {seconds:g} giay.", flush=True)
        steps = math.ceil(seconds / UPDATE_SECONDS)
        if channel not in self.outputs:
            self.outputs[channel] = self.factory(pwm_channel=channel, hz=FREQUENCY_HZ, chip=self.chip)
            self.outputs[channel].stop()
        began = time.monotonic()
        self._write(channel, start)
        for step in range(1, steps + 1):
            deadline = began + seconds * step / steps
            self.sleep(max(0.0, deadline - time.monotonic()))
            t = min(1.0, max(step / steps, (time.monotonic() - began) / seconds))
            fraction = t ** 3 * (10 - 15 * t + 6 * t ** 2)
            self._write(channel, target if t == 1 else start + (target - start) * fraction,
                        force=t == 1)
            if t == 1:
                break
        self.sleep(SETTLE_SECONDS)
        self.positions[channel] = target
        print("Da gui xong hanh trinh; PWM van duy tri cho den khi thoat/dung.")

    def close(self):
        if self.closed:
            return
        failures = []
        for channel, pwm in self.outputs.items():
            try:
                pwm.stop()
            except (Exception, KeyboardInterrupt) as error:
                failures.append(f"CH{channel}: {error or type(error).__name__}")
        self.closed = True
        if failures:
            raise RuntimeError("Khong tat duoc PWM: " + "; ".join(failures))


def main(argv=None, *, sysfs_root=PWM_ROOT, pin_reader=read_pin,
         pwm_factory=None, input_fn=input, sleeper=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Read chip/pin configuration only; no PWM writes")
    modes.add_argument("--dry-run", action="store_true", help="Simulate without GPIO, sysfs or hardware libraries")
    parser.add_argument("--chip", type=int, help="Hardware PWM chip index; default: discover the Pi 4 PWM0 provider")
    parser.add_argument("--down-us", type=float, default=LIFT_DOWN_US)
    parser.add_argument("--up-us", type=float, default=LIFT_UP_US)
    parser.add_argument("--start", choices=("down", "up"), default="down",
                        help="Assumed initial lift position; no automatic homing (default down)")
    args = parser.parse_args(argv)
    try:
        validate_pulses(args.down_us, args.up_us)
    except ValueError as error:
        parser.error(str(error))
    if args.chip is not None and args.chip < 0:
        parser.error("--chip phai la so khong am.")

    controller = None
    status = 0
    try:
        if args.dry_run:
            chip = args.chip if args.chip is not None else 0
            factory = lambda **kwargs: DryPWM()
            print("MO PHONG: khong doc GPIO/sysfs, khong mo phan cung.")
        else:
            chip = find_pwm_chip(args.chip, sysfs_root)
            print(f"PWM phan cung Pi 4: pwmchip{chip}, CH0 = BCM 12, CH1 = BCM 13.")
            check_pins(pin_reader)
            if args.check:
                print("Chi kiem tra chip/pin, khong export kenh hoac phat PWM; chua xac nhan day cam.")
                return 0
            if input_fn is input and not sys.stdin.isatty():
                raise RuntimeError("Hay nhap lenh truc tiep tren terminal khi thu that; khong pipe kich ban.")

            def factory(**kwargs):
                if pwm_factory is not None:
                    return pwm_factory(**kwargs)
                return importlib.import_module("rpi_hardware_pwm").HardwarePWM(**kwargs)

        controller = ServoTrial(chip, pwm_factory=factory, sleeper=sleeper,
                                down_us=args.down_us, up_us=args.up_us, start=args.start)
        print(f"MOC THU CHUA DO: ha -10 do = {args.down_us:g} us; nang 80 do = {args.up_us:g} us.")
        print(f"Tay duoc gia dinh dang o moc {args.start}; cang dang khep. Chua phat xung.")
        print("Lenh dau gui ngay xung moc ban dau; neu khong khop vi tri that, van co the bat nhanh.")
        print("Lenh chay NGAY: nang [giay], ha [giay], mo_cang [giay], dong_cang [giay].")
        print("Mac dinh 4 giay; khoang 2..60 giay. Khong can go chay.")
        print("thoat/dung/Ctrl+C: tat PWM ca hai kenh da dung; khong tu ha tay. Tay co the ha theo tai.")
        print("Thoat main.py va cac chuong trinh servo khac truoc khi thu that.")
        while True:
            parts = input_fn("pwm> ").strip().lower().split()
            if not parts:
                continue
            if parts in (["thoat"], ["dung"], ["q"]):
                break
            try:
                if len(parts) not in (1, 2):
                    raise ValueError("Lenh chi nhan ten va so giay tuy chon.")
                seconds = float(parts[1]) if len(parts) == 2 else 4
                if parts[0] not in controller.targets or not math.isfinite(seconds) or not 2 <= seconds <= 60:
                    raise ValueError("Dung nang/ha/mo_cang/dong_cang [giay], thoi gian 2..60 giay.")
            except ValueError as error:
                print(f"Lenh khong hop le: {error}")
                continue
            controller.move(parts[0], seconds)
    except EOFError:
        pass
    except KeyboardInterrupt:
        print("Da nhan Ctrl+C.")
        status = 130
    except Exception as error:
        print(f"Loi: {error}")
        status = 1
    finally:
        if controller is not None:
            try:
                controller.close()
            except (Exception, KeyboardInterrupt) as error:
                print(f"Loi khi dung PWM: {error}")
                status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
