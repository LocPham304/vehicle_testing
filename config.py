"""Hardware configuration copied from pi4-source/test-banh-xe.py.

Check the channel mapping and forward direction on the actual robot.
"""

from dataclasses import dataclass


I2C_ADDRESS = 0x40
PWM_FREQUENCY_HZ = 1000
DEFAULT_SPEED = 0.5  # PWM fraction used whenever a movement omits its speed.
DIRECTION_CHANGE_DELAY_SECONDS = 0.003

# Open-loop turning: these are initial estimates from the old firmware,
# NOT measured angles on this vehicle. Calibrate each side on the actual floor.
# Keep this PWM fixed while calibrating; changing it invalidates both factors.
TURN_SPEED = 0.5
TURN_LEFT_SECONDS_PER_DEGREE = 0.0089
TURN_RIGHT_SECONDS_PER_DEGREE = 0.0089

# Sideways PWM trim only. Neutral defaults; these are NOT measured corrections.
# Actual wheel PWM = command PWM * gain. Use a finite number in (0, 1].
# Reduce a stronger wheel rather than exceeding the requested command PWM.
# Tune left/right independently on the floor at a fixed command PWM.
STRAFE_LEFT_GAINS = {"FR": 1.0, "FL": 1.0, "RL": 1.0, "RR": 1.0}
STRAFE_RIGHT_GAINS = {"FR": 1.0, "FL": 1.0, "RL": 1.0, "RR": 1.0}


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
