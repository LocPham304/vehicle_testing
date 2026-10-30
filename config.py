"""Cấu hình phần cứng, sao chép từ pi4-source/test-banh-xe.py.

Cần kiểm tra lại mapping kênh và hướng tiến trên xe thật.
"""

from dataclasses import dataclass


I2C_ADDRESS = 0x40  # Địa chỉ I2C của mạch PCA9685
PWM_FREQUENCY_HZ = 1000  # Tần số PWM của động cơ
DEFAULT_SPEED = 0.5  # Tốc độ mặc định (0-1) khi lệnh không nêu tốc độ
DIRECTION_CHANGE_DELAY_SECONDS = 0.75  # Thời gian chờ khi đổi chiều quay

# Cảm biến siêu âm (số chân BCM).
# GPIO8/GPIO11 không được bị SPI0 hay thiết bị khác chiếm.
ULTRASONIC_TRIG_PIN = 8
ULTRASONIC_ECHO_PIN = 11
ULTRASONIC_TIMEOUT_SECONDS = 0.03  # Thời gian chờ tối đa mỗi lần đo
ULTRASONIC_READ_INTERVAL_SECONDS = 0.2  # Khoảng cách giữa các lần đo

# LED 7 đoạn (số chân BCM)
SEVEN_SEGMENT_CLK_PIN = 16
SEVEN_SEGMENT_DIO_PIN = 6
SEVEN_SEGMENT_BRIGHTNESS = 2  # Độ sáng

# Hệ số bù tốc độ từng bánh (để xe đi thẳng). 1.0 = không bù.
# Áp dụng cho mọi chuyển động, cả hai chiều quay.
# PWM thực tế = PWM yêu cầu * gain. Mỗi gain phải trong khoảng (0, 1].
WHEEL_GAIN = {"FR": 1.00, "FL": 1.00, "RL": 1.00, "RR": 1.00}

# Quay xe vòng hở (không có cảm biến góc): giá trị dưới đây chỉ là ước lượng
# từ firmware cũ, chưa đo trên xe này. Cần hiệu chỉnh từng bên trên sàn thật.
# Giữ nguyên TURN_SPEED khi hiệu chỉnh, nếu đổi thì phải hiệu chỉnh lại.
TURN_SPEED = 0.5
TURN_LEFT_SECONDS_PER_DEGREE = 0.0075  # Số giây cho mỗi độ khi quay trái
TURN_RIGHT_SECONDS_PER_DEGREE = 0.0075  # Số giây cho mỗi độ khi quay phải

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
# User-tested endpoints: DOWN=450 us fits the desired lower position;
# keep UP=1400 us, which the user reports is provisionally suitable.
# The 450 us lower limit is specific to this lift, not a general servo default.
SERVO_CALIBRATED = False
SERVO_DOWN_PULSE_US = 450.0   # User-tested lower endpoint (2.25% duty).
SERVO_UP_PULSE_US = 1400.0    # Logical 80 -> Raised position (~7% duty, avoids upper stop).
SERVO_MOVE_SECONDS = 2.0
SERVO_MIN_MOVE_SECONDS = 2.0
SERVO_UPDATE_INTERVAL_SECONDS = 0.02
SERVO_SETTLE_SECONDS = 0.1
# Release the lift after a move so it does not resist manual repositioning.
# PWM off removes active support; the arm may lower under load.
SERVO_HOLD_POSITION = False
# User-confirmed direction: increasing angle opens the gripper (0 -> 100).
CLAW_MIN_ANGLE = 0.0
CLAW_MAX_ANGLE = 100.0
CLAW_OPEN_ANGLE = 100.0
CLAW_CLOSE_ANGLE = 0.0
# User will prepare the claw closed at 0 degrees before starting the program.
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
    pwm: int  # Kênh PWM (tốc độ)
    in1: int  # Kênh hướng 1
    in2: int  # Kênh hướng 2
    inverted: bool = False  # True nếu bánh quay ngược chiều tiến

# Số kênh của PCA9685, không phải chân GPIO của Raspberry Pi.
MOTORS = {
    "FR": MotorPins(pwm=0, in1=2, in2=1),     # Trước phải / M1
    "FL": MotorPins(pwm=6, in1=4, in2=5),     # Trước trái / M2
    "RL": MotorPins(pwm=15, in1=14, in2=13),  # Sau trái / M3
    "RR": MotorPins(pwm=9, in1=10, in2=11),   # Sau phải / M4
}
