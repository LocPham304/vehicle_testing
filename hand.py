"""Relative arm movement using a positional servo on Raspberry Pi BCM 19.

Angles track requested positions only. GPIO opens on the first absolute command.
"""

import importlib
import logging
import math
import time
from typing import Callable, Protocol

from vehicle_testing.config import (
    SERVO_BCM_PIN, SERVO_PWM_FREQUENCY_HZ, SERVO_MIN_ANGLE,
    SERVO_MAX_ANGLE, SERVO_MOVE_WAIT_SECONDS,
)

logger = logging.getLogger(__name__)


def validate_hand_angle(angle: float) -> None:
    if not math.isfinite(angle) or not SERVO_MIN_ANGLE <= angle <= SERVO_MAX_ANGLE:
        raise ValueError(f"Goc tay phai trong [{SERVO_MIN_ANGLE:g}, {SERVO_MAX_ANGLE:g}] do.")


def validate_hand_step(angle: float) -> None:
    if not math.isfinite(angle) or angle <= 0:
        raise ValueError("So do nang/ha phai la so duong huu han.")


class ServoOutput(Protocol):
    def set_angle(self, angle: float) -> None: ...
    def release(self) -> None: ...
    def close(self) -> None: ...


class DryRunServoOutput:
    def set_angle(self, angle: float) -> None:
        logger.debug("MO PHONG GPIO BCM %d: goc %g do", SERVO_BCM_PIN, angle)

    def release(self) -> None:
        logger.debug("MO PHONG: tat PWM servo")

    def close(self) -> None:
        self.release()


class GPIOServoOutput:
    """Same PWM conversion as pi4-source/test/test_servo.py, with pin-only cleanup."""

    def __init__(self) -> None:
        self._gpio = importlib.import_module("RPi.GPIO")
        self._pwm = None
        self._closed = False
        configured = False
        try:
            self._gpio.setmode(self._gpio.BCM)
            configured = True
            self._gpio.setup(SERVO_BCM_PIN, self._gpio.OUT)
            self._pwm = self._gpio.PWM(SERVO_BCM_PIN, SERVO_PWM_FREQUENCY_HZ)
            self._pwm.start(0)  # No requested position until set_angle().
        except (Exception, KeyboardInterrupt):
            if configured:
                try:
                    self.close()
                except Exception:
                    logger.exception("Loi don GPIO sau khi khoi tao servo that bai")
            raise

    def set_angle(self, angle: float) -> None:
        validate_hand_angle(angle)
        if self._closed:
            raise RuntimeError("Servo da dong.")
        # Keep the original 0..180 electrical scale, even with a 0..80 arm limit.
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
            self._gpio.cleanup(SERVO_BCM_PIN)


class HandController:
    def __init__(self, output_factory: Callable[[], ServoOutput],
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self._output_factory = output_factory
        self._output: ServoOutput | None = None
        self._angle: float | None = None
        self._sleep = sleeper
        self._closed = False

    def set_angle(self, angle: float) -> None:
        validate_hand_angle(angle)
        if self._closed:
            raise RuntimeError("Bo dieu khien tay da dong.")
        if angle == self._angle:
            return
        logger.info("SERVO goc yeu cau %g do (GPIO BCM %d)", angle, SERVO_BCM_PIN)
        try:
            if self._output is None:
                self._output = self._output_factory()
            self._output.set_angle(angle)
            self._sleep(SERVO_MOVE_WAIT_SECONDS)
        except (Exception, KeyboardInterrupt):
            self._angle = None
            if self._output is not None:
                try:
                    self._output.release()
                except Exception:
                    logger.exception("Khong tat duoc PWM servo sau loi")
            raise
        self._angle = angle

    def hand_up(self, angle: float) -> None:
        """Match run_steps(-angle): decrease the requested servo angle."""
        self._step(angle, -1)

    def hand_down(self, angle: float) -> None:
        """Match run_steps(angle): increase the requested servo angle."""
        self._step(angle, 1)

    def _step(self, angle: float, sign: int) -> None:
        validate_hand_step(angle)
        if self._closed:
            raise RuntimeError("Bo dieu khien tay da dong.")
        if self._angle is None:
            raise ValueError("Chay tay_goc <0..80> truoc de dat goc tham chieu cho nang/ha.")
        target = self._angle + sign * angle
        limited = max(SERVO_MIN_ANGLE, min(SERVO_MAX_ANGLE, target))
        if limited != target:
            logger.info("Gioi han goc tay: %g -> %g do", target, limited)
        self.set_angle(limited)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._angle = None
        if self._output is not None:
            self._output.close()
