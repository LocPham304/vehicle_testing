"""Hardware configuration copied from pi4-source/test-banh-xe.py.

Check the channel mapping and forward direction on the actual robot.
"""

from dataclasses import dataclass


I2C_ADDRESS = 0x40
PWM_FREQUENCY_HZ = 1000
DEFAULT_SPEED = 0.5  # PWM fraction used whenever a movement omits its speed.
DIRECTION_CHANGE_DELAY_SECONDS = 0.5

# Open-loop turning: these are initial estimates from the old firmware,
# NOT measured angles on this vehicle. Calibrate each side on the actual floor.
# Keep this PWM fixed while calibrating; changing it invalidates both factors.
TURN_SPEED = 0.5
TURN_LEFT_SECONDS_PER_DEGREE = 0.0089
TURN_RIGHT_SECONDS_PER_DEGREE = 0.0089

# Confirmed by the user's probe: BCM 18 lifts the arm; BCM 12 opens the claw.
# These GPIO outputs are independent of the motor PCA9685 frequency.
SERVO_BCM_PIN = 18
CLAW_BCM_PIN = 12
SERVO_PWM_FREQUENCY_HZ = 50
SERVO_MIN_ANGLE = 0.0
SERVO_MAX_ANGLE = 80.0
# Wait between commands; this is not a measurement of the arm's travel time.
SERVO_MOVE_WAIT_SECONDS = 1.0
# Claw endpoints requested by the user: decreasing angle opens the gripper.
CLAW_MIN_ANGLE = 0.0
CLAW_MAX_ANGLE = 90.0
CLAW_OPEN_ANGLE = 0.0
CLAW_CLOSE_ANGLE = 90.0
# User will prepare the claw fully closed before starting the program.
CLAW_START_ANGLE = CLAW_CLOSE_ANGLE
# Nominal time to interpolate the requested angle between endpoints.
CLAW_MOVE_SECONDS = 2.0
# Reject shorter requests, which would increase the commanded travel speed.
CLAW_MIN_MOVE_SECONDS = 2.0
CLAW_UPDATE_INTERVAL_SECONDS = 0.02
# Allow the final request to be emitted for several PWM frames before release.
CLAW_SETTLE_SECONDS = 0.1
# Match the old door controller's pulse-then-release behavior for the claw.
# False stops PWM after each move, so active gripping force is not maintained.
CLAW_HOLD_POSITION = False


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
