"""Hardware configuration copied from pi4-source/test-banh-xe.py.

Check the channel mapping and forward direction on the actual robot.
"""

from dataclasses import dataclass


I2C_ADDRESS = 0x40
PWM_FREQUENCY_HZ = 1000
DEFAULT_SPEED = 0.5  # PWM fraction used whenever a movement omits its speed.
DIRECTION_CHANGE_DELAY_SECONDS = 0.003


@dataclass(frozen=True)
class MotorPins:
    pwm: int
    in1: int
    in2: int
    inverted: bool = False


# Set inverted=True only for a wheel that rotates against physical forward.
# These are PCA9685 channel numbers, not Raspberry Pi GPIO pin numbers.
MOTORS = {
    "FR": MotorPins(pwm=0, in1=2, in2=1),     # Front right / M1
    "FL": MotorPins(pwm=6, in1=4, in2=5),     # Front left / M2
    "RL": MotorPins(pwm=15, in1=14, in2=13),  # Rear left / M3
    "RR": MotorPins(pwm=9, in1=10, in2=11),   # Rear right / M4
}
