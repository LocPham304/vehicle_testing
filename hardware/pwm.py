"""Read-only identification of Raspberry Pi PWM providers from device tree."""

from pathlib import Path

PWM_SYSFS_ROOT = Path("/sys/class/pwm")


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
