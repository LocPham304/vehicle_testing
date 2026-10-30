"""Arm position control (BCM 18) and gradual gripper open/close (BCM 12).

Requested angles are not measured positions. GPIO opens only on execution.
In hardware mode, BCM 18 (ALT5) and BCM 12 (ALT0) time-multiplex the same
BCM2711 hardware PWM0_0 channel so both servos move without software jitter.
"""

import importlib
import logging
import math
import time
from typing import Callable, Protocol

from vehicle_testing.hardware.pwm import (
    BCM2711PinMux,
    PWM0_PIN_ALT,
    find_gpio_pwm_chip,
    find_hardware_pwm_chip,
    validate_claw_pwm_chip,
)

from vehicle_testing.config import (
    SERVO_BCM_PIN, SERVO_PWM_FREQUENCY_HZ, SERVO_MIN_ANGLE,
    SERVO_MAX_ANGLE, SERVO_UP_ANGLE, SERVO_DOWN_ANGLE, SERVO_START_ANGLE,
    SERVO_CALIBRATED, SERVO_DOWN_PULSE_US, SERVO_UP_PULSE_US,
    SERVO_MOVE_SECONDS, SERVO_MIN_MOVE_SECONDS,
    SERVO_UPDATE_INTERVAL_SECONDS, SERVO_SETTLE_SECONDS, SERVO_HOLD_POSITION,
    CLAW_BCM_PIN, CLAW_MIN_ANGLE, CLAW_MAX_ANGLE, CLAW_OPEN_ANGLE, CLAW_CLOSE_ANGLE,
    CLAW_HOLD_POSITION, CLAW_MOVE_SECONDS,
    CLAW_START_ANGLE, CLAW_MIN_MOVE_SECONDS, CLAW_UPDATE_INTERVAL_SECONDS,
    CLAW_SETTLE_SECONDS,
    CLAW_PWM_CHIP, CLAW_PWM_CHANNEL,
)

logger = logging.getLogger(__name__)


def validate_hand_angle(angle: float) -> None:
    if not math.isfinite(angle) or not SERVO_MIN_ANGLE <= angle <= SERVO_MAX_ANGLE:
        raise ValueError(f"Goc tay phai trong [{SERVO_MIN_ANGLE:g}, {SERVO_MAX_ANGLE:g}] do.")


def validate_hand_seconds(seconds: float) -> None:
    if not math.isfinite(seconds) or seconds < SERVO_MIN_MOVE_SECONDS:
        raise ValueError(f"Thoi gian nang/ha phai huu han va it nhat {SERVO_MIN_MOVE_SECONDS:g} giay.")


def validate_hand_calibration() -> None:
    """Validate lift pulses, including the user's tested 450 us lower endpoint."""
    pulses = (SERVO_DOWN_PULSE_US, SERVO_UP_PULSE_US)
    if any(
            not isinstance(pulse, (int, float)) or not math.isfinite(pulse)
            or not 450 <= pulse <= 2500 for pulse in pulses):
        raise ValueError("Can cau hinh hai moc nang/ha huu han trong [450, 2500] us o config.py.")
    if SERVO_UP_PULSE_US == SERVO_DOWN_PULSE_US or SERVO_UP_ANGLE <= SERVO_DOWN_ANGLE:
        raise ValueError("Hai moc hieu chinh nang/ha phai khac nhau va dung thu tu goc.")


def hand_angle_to_pulse_us(angle: float) -> float:
    validate_hand_angle(angle)
    validate_hand_calibration()
    fraction = (angle - SERVO_DOWN_ANGLE) / (SERVO_UP_ANGLE - SERVO_DOWN_ANGLE)
    if not 0 <= fraction <= 1:
        raise ValueError("Goc tay nam ngoai hai moc da hieu chinh.")
    return SERVO_DOWN_PULSE_US + fraction * (SERVO_UP_PULSE_US - SERVO_DOWN_PULSE_US)


def validate_claw_seconds(seconds: float) -> None:
    if not math.isfinite(seconds) or seconds < CLAW_MIN_MOVE_SECONDS:
        raise ValueError(f"Thoi gian chuyen cang phai huu han va it nhat {CLAW_MIN_MOVE_SECONDS:g} giay.")


def validate_claw_angle(angle: float) -> None:
    if not math.isfinite(angle) or not CLAW_MIN_ANGLE <= angle <= CLAW_MAX_ANGLE:
        raise ValueError(f"Goc cau hinh cang phai trong [{CLAW_MIN_ANGLE:g}, {CLAW_MAX_ANGLE:g}] do.")


def claw_angle_to_pulse_us(angle: float) -> float:
    validate_claw_angle(angle)
    return 500 + angle / 180.0 * 2000


class ServoOutput(Protocol):
    def set_angle(self, angle: float) -> None: ...
    def release(self) -> None: ...
    def close(self) -> None: ...


class DryRunServoOutput:
    def __init__(self, pin: int = SERVO_BCM_PIN) -> None:
        self._pin = pin

    def set_angle(self, angle: float) -> None:
        logger.debug("MO PHONG GPIO BCM %d: goc %g do", self._pin, angle)

    def release(self) -> None:
        logger.debug("MO PHONG: tat PWM servo")

    def close(self) -> None:
        self.release()


class GPIOServoOutput:
    """Same PWM conversion as pi4-source/test/test_servo.py, with pin-only cleanup."""

    def __init__(self, pin: int = SERVO_BCM_PIN) -> None:
        if pin not in (SERVO_BCM_PIN, CLAW_BCM_PIN):
            raise ValueError("GPIO servo phai la chan nang/ha hoac cang trong config.py.")
        self._pin = pin
        self._gpio = importlib.import_module("RPi.GPIO")
        self._pwm = None
        self._closed = False
        configured = False
        try:
            self._gpio.setmode(self._gpio.BCM)
            configured = True
            self._gpio.setup(self._pin, self._gpio.OUT)
            self._pwm = self._gpio.PWM(self._pin, SERVO_PWM_FREQUENCY_HZ)
            self._pwm.start(0)  # No requested position until set_angle().
        except (Exception, KeyboardInterrupt):
            if configured:
                try:
                    self.close()
                except Exception:
                    logger.exception("Loi don GPIO sau khi khoi tao servo that bai")
            raise

    def set_angle(self, angle: float) -> None:
        if self._pin == CLAW_BCM_PIN:
            pulse_us = claw_angle_to_pulse_us(angle)
        else:
            pulse_us = hand_angle_to_pulse_us(angle)
        if self._closed:
            raise RuntimeError("Servo da dong.")
        self._pwm.ChangeDutyCycle(pulse_us / (1_000_000 / SERVO_PWM_FREQUENCY_HZ) * 100)

    def release(self) -> None:
        if not self._closed and self._pwm is not None:
            self._pwm.ChangeDutyCycle(0)

    def close(self) -> None:
        if self._closed:
            return
        try:
            try:
                self.release()
            finally:
                if self._pwm is not None:
                    self._pwm.stop()
        finally:
            self._closed = True
            self._gpio.cleanup(self._pin)


class KernelPWMLiftOutput:
    """Legacy BCM 18 kernel pwm-gpio output (software hrtimer PWM)."""

    def __init__(self, pin: int = SERVO_BCM_PIN) -> None:
        if pin != SERVO_BCM_PIN:
            raise ValueError("pwm-gpio chi dieu khien chan nang/ha trong config.py.")
        validate_hand_calibration()
        if not SERVO_CALIBRATED:
            logger.warning("Che do thu nang/ha: hai moc xung chua do tren xe (ha %g us, nang %g us).",
                           SERVO_DOWN_PULSE_US, SERVO_UP_PULSE_US)
        chip = find_gpio_pwm_chip(pin)
        try:
            hardware = importlib.import_module("rpi_hardware_pwm")
        except ImportError as error:
            raise RuntimeError("Thieu rpi-hardware-pwm: cai requirements.txt tren Raspberry Pi.") from error
        self._pwm = None
        self._closed = False
        self._running = False
        self._pulse_us: int | None = None
        try:
            self._pwm = hardware.HardwarePWM(pwm_channel=0,
                                             hz=SERVO_PWM_FREQUENCY_HZ, chip=chip)
            self.release()
        except (Exception, KeyboardInterrupt) as error:
            try:
                self.close()
            except Exception:
                logger.exception("Loi dung pwm-gpio sau khi khoi tao nang/ha that bai")
            if isinstance(error, Exception):
                raise RuntimeError(
                    f"Khong mo duoc pwm-gpio BCM {pin} tren pwmchip{chip}. "
                    f"Kiem tra overlay, reboot va quyen ghi sysfs. Chi tiet: {error}"
                ) from error
            raise

    def set_angle(self, angle: float) -> None:
        pulse_us = round(hand_angle_to_pulse_us(angle))
        if self._closed:
            raise RuntimeError("Dau ra nang/ha da dong.")
        if pulse_us != self._pulse_us:
            duty = pulse_us / (1_000_000 / SERVO_PWM_FREQUENCY_HZ) * 100
            if self._running:
                self._pwm.change_duty_cycle(duty)
            else:
                self._pwm.start(duty)
                self._running = True
            self._pulse_us = pulse_us

    def release(self) -> None:
        if not self._closed and self._pwm is not None:
            self._pwm.stop()
            self._running = False
            self._pulse_us = None

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release()
        finally:
            self._closed = True


class HardwarePWMClawOutput:
    """Kernel hardware PWM0 routed to BCM 12; independent of Python edge timing."""

    def __init__(self, pin: int = CLAW_BCM_PIN) -> None:
        if pin != CLAW_BCM_PIN:
            raise ValueError("PWM phan cung chi dieu khien GPIO cang trong config.py.")
        if CLAW_PWM_CHANNEL != 0:
            raise ValueError("BCM 12 phai dung kenh PWM0; kiem tra CLAW_PWM_CHANNEL.")
        validate_claw_pwm_chip(CLAW_PWM_CHIP)
        try:
            hardware = importlib.import_module("rpi_hardware_pwm")
        except ImportError as error:
            raise RuntimeError("Thieu rpi-hardware-pwm: cai requirements.txt tren Raspberry Pi.") from error
        self._pwm = None
        self._closed = False
        self._running = False
        self._pulse_us: int | None = None
        try:
            self._pwm = hardware.HardwarePWM(pwm_channel=CLAW_PWM_CHANNEL,
                                             hz=SERVO_PWM_FREQUENCY_HZ, chip=CLAW_PWM_CHIP)
            self.release()
        except (Exception, KeyboardInterrupt) as error:
            try:
                self.close()
            except Exception:
                logger.exception("Loi dung PWM phan cung sau khi khoi tao cang that bai")
            if isinstance(error, Exception):
                raise RuntimeError(
                    "Khong mo duoc PWM phan cung cang. Can dtoverlay=pwm,pin=12,func=4, "
                    f"reboot va quyen ghi /sys/class/pwm/pwmchip{CLAW_PWM_CHIP}. Chi tiet: {error}"
                ) from error
            raise

    def set_angle(self, angle: float) -> None:
        validate_claw_angle(angle)
        if self._closed:
            raise RuntimeError("Dau ra cang da dong.")
        # Preserve the existing electrical scale; only the timing backend changes.
        pulse_us = round(claw_angle_to_pulse_us(angle))
        if pulse_us != self._pulse_us:
            duty = pulse_us / (1_000_000 / SERVO_PWM_FREQUENCY_HZ) * 100
            if self._running:
                self._pwm.change_duty_cycle(duty)
            else:
                self._pwm.start(duty)
                self._running = True
            self._pulse_us = pulse_us

    def release(self) -> None:
        if not self._closed and self._pwm is not None:
            self._pwm.stop()
            self._running = False
            self._pulse_us = None

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release()
        finally:
            self._closed = True


class SharedHardwarePWM0:
    """Share BCM2711 hardware PWM0_0 sequentially between BCM 18 (lift) and BCM 12 (claw).

    Before starting or changing duty cycle for one servo, PWM0_0 is stopped (if
    active on the other pin) and GPFSEL1 routes PWM0_0 only to the requested pin
    while holding the other pin LOW (0 V).
    """

    def __init__(self, *, mux_factory: Callable[[], BCM2711PinMux] | None = None) -> None:
        self._mux_factory = mux_factory
        self._mux: BCM2711PinMux | None = None
        self._pwm = None
        self._active_pin: int | None = None
        self._running = False
        self._pulse_us: int | None = None
        self._closed = False

    def _validate_pins_and_channel(self) -> None:
        if (SERVO_BCM_PIN not in PWM0_PIN_ALT or CLAW_BCM_PIN not in PWM0_PIN_ALT
                or SERVO_BCM_PIN == CLAW_BCM_PIN):
            raise ValueError(
                "Chia se PWM0 phan cung can hai chan khac nhau thuoc BCM 12 (ALT0) va BCM 18 (ALT5)."
            )
        if CLAW_PWM_CHANNEL != 0:
            raise ValueError("PWM0_0 tren BCM 12/18 phai dung kenh 0; kiem tra CLAW_PWM_CHANNEL.")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Bo dieu phoi PWM0 phan cung da dong.")
        if self._pwm is not None and self._mux is not None:
            return
        self._validate_pins_and_channel()
        chip = find_hardware_pwm_chip(CLAW_PWM_CHIP)
        try:
            hardware = importlib.import_module("rpi_hardware_pwm")
        except ImportError as error:
            raise RuntimeError("Thieu rpi-hardware-pwm: cai requirements.txt tren Raspberry Pi.") from error
        mux = None
        pwm = None
        try:
            mux = (BCM2711PinMux if self._mux_factory is None else self._mux_factory)()
            mux.isolate_all()
            pwm = hardware.HardwarePWM(pwm_channel=CLAW_PWM_CHANNEL,
                                       hz=SERVO_PWM_FREQUENCY_HZ, chip=chip)
            pwm.stop()
        except (Exception, KeyboardInterrupt) as error:
            try:
                if pwm is not None:
                    pwm.stop()
            except Exception:
                logger.exception("Loi dung PWM0 sau khi khoi tao that bai")
            try:
                if mux is not None:
                    mux.close()
            except Exception:
                logger.exception("Loi dong bo chuyen mach chan PWM0 sau khi khoi tao that bai")
            if isinstance(error, RuntimeError):
                raise
            if isinstance(error, Exception):
                raise RuntimeError(
                    f"Khong mo duoc PWM0 phan cung (pwmchip{chip}) cho BCM {SERVO_BCM_PIN}/{CLAW_BCM_PIN}. "
                    f"Can dtparam=audio=off, dtoverlay=pwm,pin=12,func=4 va quyen ghi sysfs/gpiomem. Chi tiet: {error}"
                ) from error
            raise
        self._mux = mux
        self._pwm = pwm
        self._active_pin = None
        self._running = False
        self._pulse_us = None

    def write_pulse_us(self, pin: int, pulse_us: int) -> None:
        self._ensure_open()
        assert self._pwm is not None and self._mux is not None
        if self._active_pin != pin:
            if self._running:
                self._pwm.stop()
                self._running = False
            self._pulse_us = None
            self._mux.route_pwm0(pin)
            self._active_pin = pin
        if pulse_us != self._pulse_us:
            duty = pulse_us / (1_000_000 / SERVO_PWM_FREQUENCY_HZ) * 100
            if self._running:
                self._pwm.change_duty_cycle(duty)
            else:
                self._pwm.start(duty)
                self._running = True
            self._pulse_us = pulse_us

    def release_pin(self, pin: int) -> None:
        if self._closed or self._pwm is None:
            return
        if self._active_pin not in (None, pin):
            return
        if not self._running and self._active_pin is None:
            return
        try:
            if self._running:
                self._pwm.stop()
        finally:
            self._running = False
            self._pulse_us = None
            self._active_pin = None
            if self._mux is not None:
                self._mux.isolate_all()

    def lift_output(self) -> "HardwarePWMLiftOutput":
        return HardwarePWMLiftOutput(bus=self, owns_bus=False)

    def claw_output(self) -> "MuxedHardwarePWMClawOutput":
        return MuxedHardwarePWMClawOutput(bus=self, owns_bus=False)

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._pwm is not None:
                self._pwm.stop()
        finally:
            self._running = False
            self._pulse_us = None
            self._active_pin = None
            self._closed = True
            if self._mux is not None:
                self._mux.close()
                self._mux = None
            self._pwm = None


class HardwarePWMLiftOutput:
    """BCM 18 lift output backed by shared hardware PWM0_0 (ALT5) without wire changes."""

    def __init__(
        self,
        bus: SharedHardwarePWM0 | None = None,
        *,
        pin: int = SERVO_BCM_PIN,
        owns_bus: bool | None = None,
    ) -> None:
        if pin != SERVO_BCM_PIN:
            raise ValueError("Dau ra nang/ha chi dieu khien SERVO_BCM_PIN trong config.py.")
        validate_hand_calibration()
        if not SERVO_CALIBRATED:
            logger.warning("Che do thu nang/ha: hai moc xung chua do tren xe (ha %g us, nang %g us).",
                           SERVO_DOWN_PULSE_US, SERVO_UP_PULSE_US)
        self._owns_bus = (bus is None) if owns_bus is None else owns_bus
        self._bus = SharedHardwarePWM0() if bus is None else bus
        self._pin = pin
        self._closed = False
        try:
            self._bus._ensure_open()
        except BaseException:
            if self._owns_bus:
                self._bus.close()
            raise

    def set_angle(self, angle: float) -> None:
        pulse_us = round(hand_angle_to_pulse_us(angle))
        if self._closed:
            raise RuntimeError("Dau ra nang/ha da dong.")
        self._bus.write_pulse_us(self._pin, pulse_us)

    def release(self) -> None:
        if not self._closed:
            self._bus.release_pin(self._pin)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release()
        finally:
            self._closed = True
            if self._owns_bus:
                self._bus.close()


class MuxedHardwarePWMClawOutput:
    """BCM 12 claw output backed by shared hardware PWM0_0 (ALT0)."""

    def __init__(
        self,
        bus: SharedHardwarePWM0 | None = None,
        *,
        pin: int = CLAW_BCM_PIN,
        owns_bus: bool | None = None,
    ) -> None:
        if pin != CLAW_BCM_PIN:
            raise ValueError("Dau ra cang chi dieu khien CLAW_BCM_PIN trong config.py.")
        self._owns_bus = (bus is None) if owns_bus is None else owns_bus
        self._bus = SharedHardwarePWM0() if bus is None else bus
        self._pin = pin
        self._closed = False
        try:
            self._bus._ensure_open()
        except BaseException:
            if self._owns_bus:
                self._bus.close()
            raise

    def set_angle(self, angle: float) -> None:
        pulse_us = round(claw_angle_to_pulse_us(angle))
        if self._closed:
            raise RuntimeError("Dau ra cang da dong.")
        self._bus.write_pulse_us(self._pin, pulse_us)

    def release(self) -> None:
        if not self._closed:
            self._bus.release_pin(self._pin)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release()
        finally:
            self._closed = True
            if self._owns_bus:
                self._bus.close()


class HandController:
    """Timed fixed lift endpoints on BCM 18; position starts at the lowered assumption."""

    def __init__(self, output_factory: Callable[[], ServoOutput],
                 sleeper: Callable[[float], None] = time.sleep, *,
                 calibration_required: bool = True) -> None:
        for angle in (SERVO_START_ANGLE, SERVO_UP_ANGLE, SERVO_DOWN_ANGLE):
            validate_hand_angle(angle)
        validate_hand_seconds(SERVO_MOVE_SECONDS)
        if (not math.isfinite(SERVO_MIN_MOVE_SECONDS) or SERVO_MIN_MOVE_SECONDS <= 0
                or not math.isfinite(SERVO_UPDATE_INTERVAL_SECONDS) or SERVO_UPDATE_INTERVAL_SECONDS <= 0
                or not math.isfinite(SERVO_SETTLE_SECONDS) or SERVO_SETTLE_SECONDS <= 0):
            raise ValueError("Thoi gian cau hinh nang/ha phai duong huu han.")
        self._output_factory = output_factory
        self._output: ServoOutput | None = None
        self._angle: float | None = SERVO_START_ANGLE
        self._sleep = sleeper
        self._closed = False
        self._calibration_required = calibration_required
        logger.info("Can dat tay o vi tri ha %g do truoc khi khoi dong; day la vi tri gia dinh, khong do duoc.",
                    SERVO_START_ANGLE)

    def _move(self, angle: float, seconds: float, label: str) -> None:
        validate_hand_seconds(seconds)
        validate_hand_angle(angle)
        if self._closed:
            raise RuntimeError("Bo dieu khien tay da dong.")
        if self._calibration_required:
            validate_hand_calibration()
        if self._angle is None:
            raise RuntimeError(f"Khong biet vi tri tay sau loi/ngat. Can dat tay o vi tri ha {SERVO_START_ANGLE:g} do va khoi dong lai.")
        if angle == self._angle:
            logger.info("%s: goc yeu cau da o %g do, bo qua chuyen dong.", label, angle)
            return
        start = self._angle
        steps = math.ceil(seconds / SERVO_UPDATE_INTERVAL_SECONDS)
        logger.info("%s: chuyen goc yeu cau %g -> %g do trong %g giay (GPIO BCM %d).",
                    label, start, angle, seconds, SERVO_BCM_PIN)
        try:
            if self._output is None:
                self._output = self._output_factory()
            self._output.set_angle(start)
            for step in range(1, steps + 1):
                self._sleep(seconds / steps)
                progress = step / steps
                fraction = progress ** 3 * (10 - 15 * progress + 6 * progress ** 2)
                position = angle if step == steps else start + (angle - start) * fraction
                self._output.set_angle(position)
            self._sleep(SERVO_SETTLE_SECONDS)
            if not SERVO_HOLD_POSITION:
                self._output.release()
                logger.info("Da gui yeu cau tat PWM nang/ha; khong giu luc sau lenh.")
            else:
                logger.info("Giu PWM nang/ha tai goc yeu cau %g do giua cac luot.", angle)
        except (Exception, KeyboardInterrupt):
            self._angle = None
            if self._output is not None:
                try:
                    self._output.release()
                except Exception:
                    logger.exception("Khong tat duoc PWM servo sau loi")
            raise
        self._angle = angle

    def hand_up(self, seconds: float = SERVO_MOVE_SECONDS) -> None:
        self._move(SERVO_UP_ANGLE, seconds, "NANG")

    def hand_down(self, seconds: float = SERVO_MOVE_SECONDS) -> None:
        self._move(SERVO_DOWN_ANGLE, seconds, "HA")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._angle = None
        if self._output is not None:
            self._output.close()


class ClawController:
    """Interpolate from the assumed closed startup position; no physical feedback."""

    def __init__(self, output_factory: Callable[[], ServoOutput],
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        validate_claw_angle(CLAW_START_ANGLE)
        validate_claw_seconds(CLAW_MOVE_SECONDS)
        if (not math.isfinite(CLAW_MIN_MOVE_SECONDS) or CLAW_MIN_MOVE_SECONDS <= 0
                or not math.isfinite(CLAW_UPDATE_INTERVAL_SECONDS) or CLAW_UPDATE_INTERVAL_SECONDS <= 0
                or not math.isfinite(CLAW_SETTLE_SECONDS) or CLAW_SETTLE_SECONDS <= 0):
            raise ValueError("Thoi gian cau hinh cang phai duong huu han.")
        self._output_factory = output_factory
        self._output: ServoOutput | None = None
        self._sleep = sleeper
        self._hold_position = CLAW_HOLD_POSITION
        self._closed = False
        self._angle: float | None = CLAW_START_ANGLE
        logger.info("Can de cang khep %g do truoc khi khoi dong; day la vi tri gia dinh, khong do duoc.",
                    CLAW_START_ANGLE)

    def _move(self, angle: float, seconds: float, label: str) -> None:
        validate_claw_seconds(seconds)
        validate_claw_angle(angle)
        if self._closed:
            raise RuntimeError("Bo dieu khien cang da dong.")
        if self._angle is None:
            raise RuntimeError("Khong biet vi tri cang sau loi/ngat. Can de cang khep va khoi dong lai.")
        if angle == self._angle:
            logger.info("%s: goc yeu cau da o %g do, bo qua chuyen dong.", label, angle)
            return
        start = self._angle
        steps = math.ceil(seconds / CLAW_UPDATE_INTERVAL_SECONDS)
        logger.info("%s: chuyen goc yeu cau %g -> %g do trong %g giay (GPIO BCM %d).",
                    label, start, angle, seconds, CLAW_BCM_PIN)
        try:
            if self._output is None:
                self._output = self._output_factory()
            self._output.set_angle(start)
            for step in range(1, steps + 1):
                self._sleep(seconds / steps)
                progress = step / steps
                # Quintic easing: zero velocity and acceleration at both ends.
                fraction = progress ** 3 * (10 - 15 * progress + 6 * progress ** 2)
                position = angle if step == steps else start + (angle - start) * fraction
                self._output.set_angle(position)
            self._sleep(CLAW_SETTLE_SECONDS)
            if not self._hold_position:
                self._output.release()
                logger.info("Da gui yeu cau tat PWM cang; khong giu luc kep lien tuc.")
        except (Exception, KeyboardInterrupt):
            self._angle = None
            if self._output is not None:
                try:
                    self._output.release()
                except Exception:
                    logger.exception("Khong tat duoc PWM cang sau loi")
            raise
        self._angle = angle

    def open(self, seconds: float = CLAW_MOVE_SECONDS) -> None:
        self._move(CLAW_OPEN_ANGLE, seconds, "MO CANG")

    def grip(self, seconds: float = CLAW_MOVE_SECONDS) -> None:
        self._move(CLAW_CLOSE_ANGLE, seconds, "DONG CANG")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._angle = None
        if self._output is not None:
            self._output.close()
