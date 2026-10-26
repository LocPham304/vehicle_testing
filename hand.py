"""Arm position control (BCM 18) and gradual gripper open/close (BCM 12).

Requested angles are not measured positions. GPIO opens only on execution.
"""

import importlib
import logging
import math
import time
from typing import Callable, Protocol

from vehicle_testing.config import (
    SERVO_BCM_PIN, SERVO_PWM_FREQUENCY_HZ, SERVO_MIN_ANGLE,
    SERVO_MAX_ANGLE, SERVO_MOVE_WAIT_SECONDS,
    CLAW_BCM_PIN, CLAW_MIN_ANGLE, CLAW_MAX_ANGLE, CLAW_OPEN_ANGLE, CLAW_CLOSE_ANGLE,
    CLAW_HOLD_POSITION, CLAW_MOVE_SECONDS,
    CLAW_START_ANGLE, CLAW_MIN_MOVE_SECONDS, CLAW_UPDATE_INTERVAL_SECONDS,
    CLAW_SETTLE_SECONDS,
)

logger = logging.getLogger(__name__)


def validate_hand_angle(angle: float) -> None:
    if not math.isfinite(angle) or not SERVO_MIN_ANGLE <= angle <= SERVO_MAX_ANGLE:
        raise ValueError(f"Goc tay phai trong [{SERVO_MIN_ANGLE:g}, {SERVO_MAX_ANGLE:g}] do.")


def validate_hand_step(angle: float) -> None:
    if not math.isfinite(angle) or angle <= 0:
        raise ValueError("So do nang/ha phai la so duong huu han.")


def validate_claw_seconds(seconds: float) -> None:
    if not math.isfinite(seconds) or seconds < CLAW_MIN_MOVE_SECONDS:
        raise ValueError(f"Thoi gian chuyen cang phai huu han va it nhat {CLAW_MIN_MOVE_SECONDS:g} giay.")


def validate_claw_angle(angle: float) -> None:
    if not math.isfinite(angle) or not CLAW_MIN_ANGLE <= angle <= CLAW_MAX_ANGLE:
        raise ValueError(f"Goc cau hinh cang phai trong [{CLAW_MIN_ANGLE:g}, {CLAW_MAX_ANGLE:g}] do.")


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
            validate_claw_angle(angle)
        else:
            validate_hand_angle(angle)
        if self._closed:
            raise RuntimeError("Servo da dong.")
        # Keep the original 0..180 electrical scale with per-device angle limits.
        self._pwm.ChangeDutyCycle(2.5 + angle / 180.0 * 10.0)

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


class ServoController:
    def __init__(self, output_factory: Callable[[], ServoOutput],
                 sleeper: Callable[[float], None] = time.sleep, *,
                 pin: int = SERVO_BCM_PIN, label: str = "SERVO",
                 reference_command: str = "tay_goc",
                 hold_position: bool = True,
                 settle_seconds: float = SERVO_MOVE_WAIT_SECONDS) -> None:
        if not math.isfinite(settle_seconds) or settle_seconds <= 0:
            raise ValueError("Thoi gian cho servo phai duong huu han.")
        self._output_factory = output_factory
        self._output: ServoOutput | None = None
        self._angle: float | None = None
        self._sleep = sleeper
        self._closed = False
        self._pin = pin
        self._label = label
        self._reference_command = reference_command
        self._hold_position = hold_position
        self._settle_seconds = settle_seconds

    def set_angle(self, angle: float) -> None:
        validate_hand_angle(angle)
        if self._closed:
            raise RuntimeError("Bo dieu khien tay da dong.")
        if angle == self._angle and self._hold_position:
            return
        logger.info("%s goc yeu cau %g do (GPIO BCM %d)", self._label, angle, self._pin)
        try:
            if self._output is None:
                self._output = self._output_factory()
            self._output.set_angle(angle)
            self._sleep(self._settle_seconds)
            if not self._hold_position:
                self._output.release()
                logger.info("%s da gui yeu cau tat PWM sau lenh; khong giu luc lien tuc.", self._label)
        except (Exception, KeyboardInterrupt):
            self._angle = None
            if self._output is not None:
                try:
                    self._output.release()
                except Exception:
                    logger.exception("Khong tat duoc PWM servo sau loi")
            raise
        self._angle = angle

    def _step(self, angle: float, sign: int) -> None:
        validate_hand_step(angle)
        if self._closed:
            raise RuntimeError("Bo dieu khien tay da dong.")
        if self._angle is None:
            raise ValueError(f"Chay {self._reference_command} <0..80> truoc de dat goc tham chieu.")
        target = self._angle + sign * angle
        limited = max(SERVO_MIN_ANGLE, min(SERVO_MAX_ANGLE, target))
        if limited != target:
            logger.info("Gioi han goc tay: %g -> %g do", target, limited)
        if limited == self._angle:
            return
        self.set_angle(limited)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._angle = None
        if self._output is not None:
            self._output.close()


class HandController(ServoController):
    def hand_up(self, angle: float) -> None:
        """Match run_steps(-angle): decrease the requested servo angle."""
        self._step(angle, -1)

    def hand_down(self, angle: float) -> None:
        """Match run_steps(angle): increase the requested servo angle."""
        self._step(angle, 1)


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
