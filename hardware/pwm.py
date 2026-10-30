"""Identification of Raspberry Pi PWM providers and BCM2711 PWM0 pin multiplexing."""

import mmap
import os
from collections.abc import Sequence
from pathlib import Path

PWM_SYSFS_ROOT = Path("/sys/class/pwm")
GPIOMEM_PATH = Path("/dev/gpiomem")
DT_COMPATIBLE_PATHS = (
    Path("/proc/device-tree/compatible"),
    Path("/sys/firmware/devicetree/base/compatible"),
)
SUPPORTED_BCM_SOCS = (
    b"brcm,bcm2711",
    b"brcm,bcm2837",
    b"brcm,bcm2836",
    b"brcm,bcm2835",
)

# BCM2835..BCM2711 GPIO peripheral registers exposed at /dev/gpiomem offset 0.
GPFSEL1_WORD = 0x04 // 4  # Controls GPIO 10..19 (3 bits per pin)
GPCLR0_WORD = 0x28 // 4   # Clears GPIO 0..31 output latches (write 1 to clear)
FSEL_OUTPUT = 0b001
FSEL_ALT0 = 0b100         # GPIO 12 -> PWM0_0
FSEL_ALT5 = 0b010         # GPIO 18 -> PWM0_0
PWM0_PIN_ALT = {12: FSEL_ALT0, 18: FSEL_ALT5}


def _compatible(chip: Path) -> list[bytes]:
    try:
        return (chip / "device/of_node/compatible").read_bytes().split(b"\0")
    except FileNotFoundError:
        return []
    except OSError as error:
        raise RuntimeError(f"Khong doc duoc driver cua {chip}: {error}") from error


def find_gpio_pwm_chip(pin: int, sysfs_root: Path = PWM_SYSFS_ROOT) -> int:
    """Find exactly one single-channel pwm-gpio provider wired to this BCM pin.

    The Pi 4 overlay encodes gpios as three big-endian cells: controller
    phandle, GPIO offset, flags. No channels are exported or modified here.
    """
    matches = []
    for chip in Path(sysfs_root).glob("pwmchip*"):
        suffix = chip.name.removeprefix("pwmchip")
        if not suffix.isdecimal() or b"pwm-gpio" not in _compatible(chip):
            continue
        try:
            gpios = (chip / "device/of_node/gpios").read_bytes()
            if len(gpios) != 12:
                raise ValueError("gpios phai gom 3 device-tree cells tren Pi 4")
            if int.from_bytes(gpios[4:8], "big") != pin:
                continue
            if int((chip / "npwm").read_text(encoding="ascii").strip()) != 1:
                raise ValueError("pwm-gpio phai co dung 1 kenh")
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Metadata PWM khong hop le tai {chip}: {error}") from error
        matches.append(int(suffix))
    if len(matches) != 1:
        raise RuntimeError(
            f"Can dung 1 driver pwm-gpio cho BCM {pin}, tim thay {len(matches)}. "
            f"Them dtoverlay=pwm-gpio,gpio={pin} vao /boot/firmware/config.txt va reboot."
        )
    return matches[0]


def validate_claw_pwm_chip(chip: int, sysfs_root: Path = PWM_SYSFS_ROOT) -> None:
    """Reject a renumbered GPIO provider before the working claw opens PWM0."""
    path = Path(sysfs_root) / f"pwmchip{chip}"
    if b"brcm,bcm2835-pwm" not in _compatible(path):
        raise RuntimeError(
            f"pwmchip{chip} khong phai PWM phan cung BCM cua cang. "
            "Chay check_lift_pwm.py va dat CLAW_PWM_CHIP dung driver brcm,bcm2835-pwm; "
            "khong dung chip pwm-gpio cua BCM 18."
        )


def find_hardware_pwm_chip(
    preferred_chip: int | None = None,
    sysfs_root: Path = PWM_SYSFS_ROOT,
) -> int:
    """Locate the BCM hardware PWM controller regardless of pwmchip numbering."""
    root = Path(sysfs_root)
    if preferred_chip is not None:
        if b"brcm,bcm2835-pwm" in _compatible(root / f"pwmchip{preferred_chip}"):
            return preferred_chip
    matches = sorted(
        int(chip.name.removeprefix("pwmchip"))
        for chip in root.glob("pwmchip*")
        if chip.name.removeprefix("pwmchip").isdecimal()
        and b"brcm,bcm2835-pwm" in _compatible(chip)
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"Can dung 1 driver PWM phan cung brcm,bcm2835-pwm, tim thay {len(matches)}. "
            "Them dtparam=audio=off va dtoverlay=pwm,pin=12,func=4 vao "
            "/boot/firmware/config.txt va reboot."
        )
    return matches[0]


def _validate_bcm_soc(compatible_paths: Sequence[Path] = DT_COMPATIBLE_PATHS) -> None:
    for path in compatible_paths:
        try:
            entries = Path(path).read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError(f"Khong doc duoc thong tin SoC tai {path}: {error}") from error
        if b"brcm,bcm2712" in entries:
            raise RuntimeError("Chia se PWM0 qua /dev/gpiomem khong ho tro Raspberry Pi 5 (RP1).")
        if any(soc in entries for soc in SUPPORTED_BCM_SOCS):
            return
        raise RuntimeError("SoC khong phai BCM2835..BCM2711; khong the chuyen mach GPFSEL1.")
    raise RuntimeError("Khong xac dinh duoc SoC Raspberry Pi tu device-tree.")


def _pin_shift(pin: int) -> int:
    if pin not in PWM0_PIN_ALT:
        raise ValueError(f"Chi ho tro chuyen mach PWM0 tren GPIO {sorted(PWM0_PIN_ALT)}, nhan {pin}.")
    return (pin - 10) * 3


class BCM2711PinMux:
    """Route hardware PWM0_0 exclusively to GPIO 12 (ALT0) or GPIO 18 (ALT5).

    The inactive servo pin is cleared via GPCLR0 and driven as a LOW output in
    the same 32-bit GPFSEL1 write so pulses never leak to the other servo.
    """

    def __init__(
        self,
        reg_buffer: bytearray | mmap.mmap | None = None,
        *,
        gpiomem_path: Path = GPIOMEM_PATH,
        dt_compatible_paths: Sequence[Path] = DT_COMPATIBLE_PATHS,
    ) -> None:
        self._owned_mmap: mmap.mmap | None = None
        self._words: memoryview | None = None
        self._closed = False
        if reg_buffer is None:
            _validate_bcm_soc(dt_compatible_paths)
            flags = os.O_RDWR | getattr(os, "O_SYNC", 0)
            try:
                fd = os.open(gpiomem_path, flags)
            except OSError as error:
                raise RuntimeError(
                    f"Khong mo duoc {gpiomem_path} de chuyen mach PWM0 BCM 12/18. "
                    f"Can quyen nhom gpio hoac sudo. Chi tiet: {error}"
                ) from error
            try:
                self._owned_mmap = mmap.mmap(fd, 4096, access=mmap.ACCESS_WRITE, offset=0)
            finally:
                os.close(fd)
            target = self._owned_mmap
        else:
            target = reg_buffer
        words = memoryview(target).cast("I")
        if words.itemsize != 4 or len(words) <= GPCLR0_WORD:
            words.release()
            if self._owned_mmap is not None:
                self._owned_mmap.close()
            raise RuntimeError("Bo nho thanh ghi GPIO khong du kich thuoc 32-bit word.")
        self._words = words

    def route_pwm0(self, active_pin: int) -> None:
        if self._closed or self._words is None:
            raise RuntimeError("Bo chuyen mach chan PWM0 da dong.")
        active_shift = _pin_shift(active_pin)
        inactive_pin = 18 if active_pin == 12 else 12
        inactive_shift = _pin_shift(inactive_pin)

        # Clear output latches before switching the inactive pin to GPIO output.
        self._words[GPCLR0_WORD] = (1 << 12) | (1 << 18)
        clear_mask = ~((0b111 << active_shift) | (0b111 << inactive_shift)) & 0xFFFFFFFF
        set_bits = (PWM0_PIN_ALT[active_pin] << active_shift) | (FSEL_OUTPUT << inactive_shift)
        self._words[GPFSEL1_WORD] = (self._words[GPFSEL1_WORD] & clear_mask) | set_bits

    def isolate_all(self) -> None:
        if self._closed or self._words is None:
            return
        shift_12 = _pin_shift(12)
        shift_18 = _pin_shift(18)
        self._words[GPCLR0_WORD] = (1 << 12) | (1 << 18)
        clear_mask = ~((0b111 << shift_12) | (0b111 << shift_18)) & 0xFFFFFFFF
        set_bits = (FSEL_OUTPUT << shift_12) | (FSEL_OUTPUT << shift_18)
        self._words[GPFSEL1_WORD] = (self._words[GPFSEL1_WORD] & clear_mask) | set_bits

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.isolate_all()
        finally:
            self._closed = True
            if self._words is not None:
                self._words.release()
                self._words = None
            if self._owned_mmap is not None:
                self._owned_mmap.close()
                self._owned_mmap = None
