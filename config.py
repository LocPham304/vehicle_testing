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
# Kernel pwm-gpio provider is discovered from device tree, not a fixed chip index.
# Requires dtoverlay=pwm-gpio,gpio=18; never route hardware PWM0 to this pin.
CLAW_BCM_PIN = 12
SERVO_PWM_FREQUENCY_HZ = 50
SERVO_MIN_ANGLE = -10.0
SERVO_MAX_ANGLE = 80.0
SERVO_UP_ANGLE = 80.0
SERVO_DOWN_ANGLE = -10.0
# User will prepare the arm at the lowered position before starting.
SERVO_START_ANGLE = SERVO_DOWN_ANGLE
# Measured physical direction: increasing pulse raises the arm.
# Safe initial test endpoints avoiding stops: DOWN at 650 us, UP at 1400 us.
SERVO_CALIBRATED = False
SERVO_DOWN_PULSE_US = 650.0   # Logical -10 -> Lowered resting position (~3.25% duty).
SERVO_UP_PULSE_US = 1400.0    # Logical 80 -> Raised position (~7% duty, avoids upper stop).
SERVO_MOVE_SECONDS = 2.0
SERVO_MIN_MOVE_SECONDS = 2.0
SERVO_UPDATE_INTERVAL_SECONDS = 0.02
SERVO_SETTLE_SECONDS = 0.1
# Release the lift after a move so it does not resist manual repositioning.
# PWM off removes active support; the arm may lower under load.
SERVO_HOLD_POSITION = False
# Claw endpoints requested by the user: decreasing angle opens the gripper.
CLAW_MIN_ANGLE = 0.0
CLAW_MAX_ANGLE = 100.0
CLAW_OPEN_ANGLE = 0.0
# User reports that 90 degrees leaves a gap; closing needs about 100 degrees.
CLAW_CLOSE_ANGLE = 100.0
# User will prepare the claw fully closed before starting the program.
CLAW_START_ANGLE = CLAW_CLOSE_ANGLE
# Pi check with both overlays: pwmchip0 = GPIO 18; pwmchip1 = BCM hardware PWM.
# BCM 12 still uses channel 0. Recheck with check_lift_pwm.py if numbering changes.
CLAW_PWM_CHIP = 1
CLAW_PWM_CHANNEL = 0
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
