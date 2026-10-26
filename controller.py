"""Motor control independent of terminal input and command parsing."""

import logging
import math
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from .config import (
    DEFAULT_SPEED,
    DIRECTION_CHANGE_DELAY_SECONDS,
    I2C_ADDRESS,
    MOTORS,
    PWM_FREQUENCY_HZ,
    TURN_LEFT_SECONDS_PER_DEGREE,
    TURN_RIGHT_SECONDS_PER_DEGREE,
    TURN_SPEED,
    MotorPins,
)


logger = logging.getLogger(__name__)


class ChannelOutput(Protocol):
    """Boundary implemented by the hardware and simulation outputs."""

    def set_duty(self, channel: int, duty: int) -> None: ...

    def close(self) -> None: ...


class PCA9685Output:
    """Own the I2C connection and Adafruit PCA9685 instance."""

    def __init__(self) -> None:
        # Simulation and imports on a PC must not require hardware libraries.
        try:
            import board
            import busio
            from adafruit_pca9685 import PCA9685
        except ImportError as error:
            raise RuntimeError(
                "Thieu thu vien phan cung. Cai requirements.txt tren Raspberry Pi "
                "hoac chay voi --dry-run tren may tinh."
            ) from error

        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._pca = None
        try:
            self._pca = PCA9685(self._i2c, address=I2C_ADDRESS)
            self._pca.frequency = PWM_FREQUENCY_HZ
        except BaseException:
            try:
                self.close()
            except Exception:
                logger.exception("Khong the giai phong I2C sau loi khoi tao.")
            raise

    def set_duty(self, channel: int, duty: int) -> None:
        self._pca.channels[channel].duty_cycle = duty

    def close(self) -> None:
        try:
            if self._pca is not None:
                self._pca.deinit()
        finally:
            self._i2c.deinit()


class DryRunOutput:
    """Log output requests without opening I2C or controlling any device."""

    def set_duty(self, channel: int, duty: int) -> None:
        logger.debug("[MO PHONG] CH%02d duty=%d", channel, duty)

    def close(self) -> None:
        logger.debug("[MO PHONG] Dong ket noi.")


def validate_duration(seconds: float) -> None:
    """Accept any positive finite number of seconds without an application cap."""
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Thoi gian phai la so huu han lon hon 0, don vi giay.")


def validate_motion(direction: str, seconds: float, speed: float) -> None:
    """Reject invalid commands instead of silently turning speed=5 into 100%."""
    if direction not in ("forward", "backward"):
        raise ValueError("Chieu chay phai la forward hoac backward.")
    validate_duration(seconds)
    validate_speed(speed)


def validate_speed(speed: float) -> None:
    if not math.isfinite(speed) or not 0 < speed <= 1:
        raise ValueError("PWM phai nam trong khoang (0, 1], vi du 0.5 = 50%.")


def validate_turn(direction: str, angle: float) -> None:
    if direction not in ("left", "right"):
        raise ValueError("Chieu quay phai la left hoac right.")
    if not math.isfinite(angle) or angle <= 0:
        raise ValueError("Goc quay phai la so huu han lon hon 0, don vi do.")


def validate_strafe(direction: str, seconds: float, speed: float) -> None:
    if direction not in ("left", "right"):
        raise ValueError("Chieu chay ngang phai la left hoac right.")
    validate_duration(seconds)
    validate_speed(speed)


class MotorController:
    """Drive all configured wheels for a duration, then request a stop."""

    def __init__(
        self,
        output: ChannelOutput,
        motors: Mapping[str, MotorPins] = MOTORS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._motors = dict(motors)
        channels = [
            channel for pins in self._motors.values()
            for channel in (pins.pwm, pins.in1, pins.in2)
        ]
        if not channels or any(type(ch) is not int or not 0 <= ch <= 15 for ch in channels):
            raise ValueError("Cau hinh motor phai co cac kenh nguyen tu 0 den 15.")
        if len(channels) != len(set(channels)):
            raise ValueError("Cac motor khong duoc dung trung kenh PWM/IN1/IN2.")
        self._output = output
        self._sleep = sleeper
        self._closed = False

    def _set_channel(self, channel: int, value: float) -> None:
        self._output.set_duty(channel, int(value * 65535))

    def stop(self) -> None:
        """Try every motor channel even if one I2C write fails."""
        if self._closed:
            return
        # Disable every PWM before clearing direction inputs.
        channels = [pins.pwm for pins in self._motors.values()]
        channels += [ch for pins in self._motors.values() for ch in (pins.in1, pins.in2)]
        first_error = None
        for channel in channels:
            try:
                self._set_channel(channel, 0)
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def pause(self, seconds: float) -> None:
        """Keep motor outputs off during a timed pause, then allow continuation."""
        validate_duration(seconds)
        if self._closed:
            raise RuntimeError("Bo dieu khien da dong.")
        try:
            self.stop()
            logger.info("NGUNG trong %g giay", seconds)
            self._sleep(seconds)
        finally:
            self.stop()

    def move(self, direction: str, seconds: float, speed: float = DEFAULT_SPEED) -> None:
        validate_motion(direction, seconds, speed)
        directions = {name: direction == "forward" for name in self._motors}
        self._drive_for(directions, seconds, speed, "TIEN" if direction == "forward" else "LUI")

    def strafe(self, direction: str, seconds: float, speed: float = DEFAULT_SPEED) -> None:
        """Slide left/right relative to the chassis, without commanding rotation."""
        validate_strafe(direction, seconds, speed)
        if set(self._motors) != {"FR", "FL", "RL", "RR"}:
            raise ValueError("Chay ngang Mecanum can du bon banh FR, FL, RL, RR.")
        # Physical directions for the documented X roller arrangement.
        directions = {
            "FR": direction == "left", "FL": direction == "right",
            "RL": direction == "left", "RR": direction == "right",
        }
        label = "NGANG TRAI" if direction == "left" else "NGANG PHAI"
        self._drive_for(directions, seconds, speed, label)

    def move_forward_left(self, seconds: float, speed: float = DEFAULT_SPEED) -> None:
        """Translate at 3*pi/4: FR/RL forward, FL/RR unpowered."""
        self._move_diagonal(("FR", "RL"), True, seconds, speed, "TREN TRAI")

    def move_forward_right(self, seconds: float, speed: float = DEFAULT_SPEED) -> None:
        """Translate at pi/4: FL/RR forward, FR/RL unpowered."""
        self._move_diagonal(("FL", "RR"), True, seconds, speed, "TREN PHAI")

    def move_backward_left(self, seconds: float, speed: float = DEFAULT_SPEED) -> None:
        """Translate at -3*pi/4: FL/RR backward, FR/RL unpowered."""
        self._move_diagonal(("FL", "RR"), False, seconds, speed, "DUOI TRAI")

    def move_backward_right(self, seconds: float, speed: float = DEFAULT_SPEED) -> None:
        """Translate at -pi/4: FR/RL backward, FL/RR unpowered."""
        self._move_diagonal(("FR", "RL"), False, seconds, speed, "DUOI PHAI")

    def _move_diagonal(
        self, active_wheels: tuple[str, str], forward: bool,
        seconds: float, speed: float, label: str,
    ) -> None:
        validate_duration(seconds)
        validate_speed(speed)
        if set(self._motors) != {"FR", "FL", "RL", "RR"}:
            raise ValueError("Chay cheo Mecanum can du bon banh FR, FL, RL, RR.")
        # At diagonal angles one pair has sin(angle +/- pi/4)=+/-1, the other 0.
        directions = {name: forward if name in active_wheels else None for name in self._motors}
        self._drive_for(directions, seconds, speed, label)

    def turn_left(self, angle: float) -> None:
        """Estimate a counterclockwise chassis turn, viewed from above."""
        self.turn("left", angle)

    def turn_right(self, angle: float) -> None:
        """Estimate a clockwise chassis turn, viewed from above."""
        self.turn("right", angle)

    def turn(self, direction: str, angle: float) -> None:
        """Rotate in place using time calibration, without measuring heading."""
        validate_turn(direction, angle)
        if set(self._motors) != {"FR", "FL", "RL", "RR"}:
            raise ValueError("Quay Mecanum can du bon banh FR, FL, RL, RR.")
        factor = TURN_LEFT_SECONDS_PER_DEGREE if direction == "left" else TURN_RIGHT_SECONDS_PER_DEGREE
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("He so giay/do phai la so huu han lon hon 0.")
        seconds = angle * factor
        validate_duration(seconds)
        validate_speed(TURN_SPEED)
        # Physical forward/backward; apply electrical inversion only in _drive_for.
        right_side_forward = direction == "left"
        directions = {
            "FR": right_side_forward, "RR": right_side_forward,
            "FL": not right_side_forward, "RL": not right_side_forward,
        }
        label = "QUAY TRAI" if direction == "left" else "QUAY PHAI"
        self._drive_for(directions, seconds, TURN_SPEED, f"{label} {angle:g} do (uoc luong)")

    def _drive_for(
        self, directions: Mapping[str, bool | None], seconds: float, speed: float, label: str,
    ) -> None:
        """Use physical directions; None keeps a wheel's PWM and inputs at zero."""
        if self._closed:
            raise RuntimeError("Bo dieu khien da dong.")

        try:
            self.stop()
            self._sleep(DIRECTION_CHANGE_DELAY_SECONDS)

            # Set the whole group's direction before enabling any PWM.
            for name, pins in self._motors.items():
                if directions[name] is None:
                    in1 = in2 = 0.0
                else:
                    forward = directions[name] != pins.inverted
                    in1, in2 = (1.0, 0.0) if forward else (0.0, 1.0)
                self._set_channel(pins.in1, in1)
                self._set_channel(pins.in2, in2)
                logger.debug("%s: IN1=%d IN2=%d", name, int(in1), int(in2))

            self._sleep(DIRECTION_CHANGE_DELAY_SECONDS)
            for name, pins in self._motors.items():
                self._set_channel(pins.pwm, speed if directions[name] is not None else 0.0)

            logger.info("%s trong %g giay, PWM %.0f%%", label, seconds, speed * 100)
            self._sleep(seconds)
        finally:
            # Also covers partial startup and Ctrl+C during the timed wait.
            self.stop()
        logger.info("Da gui lenh dung ca 4 motor.")

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.stop()
        finally:
            self._closed = True
            self._output.close()
