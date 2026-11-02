"""Hardware-free double for Adafruit Servo's documented PWMOut contract.

The 16-bit duty quantization models the external library, not measured GPIO.
"""

from unittest.mock import Mock, patch


class ServoDouble:
    def __init__(self, pwm, *, actuation_range, min_pulse, max_pulse):
        self.pwm = pwm
        self.range = actuation_range
        self.minimum = int(min_pulse * pwm.frequency / 1_000_000 * 65535)
        maximum = max_pulse * pwm.frequency / 1_000_000 * 65535
        self.span = int(maximum - self.minimum)
        self._angle = None

    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, value):
        if not 0 <= value <= self.range:
            raise ValueError("Angle out of range")
        self.pwm.duty_cycle = self.minimum + int(value / self.range * self.span)
        self._angle = value


def mock_adafruit_servo(testcase):
    module = Mock()
    module.Servo.side_effect = ServoDouble
    replacement = patch.dict("sys.modules", {"adafruit_motor.servo": module})
    replacement.start()
    testcase.addCleanup(replacement.stop)
    return module
