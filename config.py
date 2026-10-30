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

# Cả BCM 18 (ALT5) và BCM 12 (ALT0) dùng chung kênh PWM0 phần cứng, tự chuyển mạch chân.
SERVO_BCM_PIN = 18  # Servo nâng tay
CLAW_BCM_PIN = 12  # Servo kẹp
SERVO_PWM_FREQUENCY_HZ = 50  # Tần số PWM chuẩn của servo
SERVO_MIN_ANGLE = -10.0
SERVO_MAX_ANGLE = 80.0
SERVO_UP_ANGLE = 80.0  # Góc khi nâng tay
SERVO_DOWN_ANGLE = -10.0  # Góc khi hạ tay
# Người dùng đặt tay ở vị trí hạ trước khi chạy.
SERVO_START_ANGLE = SERVO_DOWN_ANGLE
# Đã đo: xung càng lớn thì tay càng nâng cao.
SERVO_CALIBRATED = False  # Chưa hiệu chỉnh xong
SERVO_DOWN_PULSE_US = 450.0  # Xung vị trí hạ (duty 2.25%)
SERVO_UP_PULSE_US = 1400.0  # Xung vị trí nâng (duty ~7%, tránh chạm giới hạn trên)
SERVO_MOVE_SECONDS = 2.0  # Thời gian di chuyển giữa hai đầu
SERVO_MIN_MOVE_SECONDS = 2.0  # Thời gian tối thiểu, tránh di chuyển quá nhanh
SERVO_UPDATE_INTERVAL_SECONDS = 0.02  # Chu kỳ cập nhật góc
SERVO_SETTLE_SECONDS = 0.1  # Chờ ổn định trước khi nhả
# Nhả servo sau khi di chuyển để có thể chỉnh tay bằng tay.
# Tắt PWM = không giữ lực, tay có thể tụt xuống nếu có tải.
SERVO_HOLD_POSITION = False

# Kẹp: góc giảm thì kẹp mở.
CLAW_MIN_ANGLE = 0.0
CLAW_MAX_ANGLE = 100.0
CLAW_OPEN_ANGLE = 0.0  # Góc khi mở
# 90 độ vẫn còn hở, cần khoảng 100 độ để kẹp kín.
CLAW_CLOSE_ANGLE = 100.0  # Góc khi đóng
# Người dùng đặt kẹp ở trạng thái đóng trước khi chạy chương trình.
CLAW_START_ANGLE = CLAW_CLOSE_ANGLE
# Khi bật cả hai overlay: pwmchip0 = GPIO 18; pwmchip1 = BCM hardware PWM.
# BCM 12 vẫn dùng channel 0. Nếu số thứ tự đổi, kiểm tra lại bằng check_lift_pwm.py.
CLAW_PWM_CHIP = 1
CLAW_PWM_CHANNEL = 0
CLAW_MOVE_SECONDS = 2.0  # Thời gian nội suy góc giữa hai đầu
CLAW_MIN_MOVE_SECONDS = 2.0  # Từ chối thời gian ngắn hơn (kẹp sẽ chạy nhanh hơn)
CLAW_UPDATE_INTERVAL_SECONDS = 0.02  # Chu kỳ cập nhật góc
CLAW_SETTLE_SECONDS = 0.1  # Phát thêm vài chu kỳ PWM cuối trước khi nhả
# Giống bộ điều khiển cửa cũ: phát xung rồi nhả.
# False = tắt PWM sau mỗi lần di chuyển, không giữ lực kẹp chủ động.
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
