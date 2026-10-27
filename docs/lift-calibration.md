# Cấu hình thử nâng/hạ −10°/80° và hiệu chỉnh xung

Người dùng xác nhận nâng/hạ đến cuối hành trình trong khoảng 1 giây và phần
thời gian còn lại giật mạnh; tay đã chạm hoặc ép vào khung/điểm chặn cơ khí.
Lịch gửi góc trong phần mềm không cho biết vị trí thật. Tăng số giây không tránh
được việc các góc tiếp theo tiếp tục ép vào điểm chặn.

Người dùng yêu cầu giữ hai mốc hạ −10°/nâng 80° để tự thử. Bản hiện tại cho phép
chạy thật với xung thử 1500 µs ở mốc −10° và 500 µs ở mốc 80°, giữ chiều nâng
bằng cách giảm xung như code cũ. Hai giá trị này chưa được đo trên cơ cấu;
đổi sang kernel pwm-gpio không chứng minh đã tránh được điểm chặn.

## Cấu hình đang dùng

- `SERVO_DOWN_PULSE_US=1500.0`: xung thử cho mốc hạ −10°.
- `SERVO_UP_PULSE_US=500.0`: xung thử cho mốc nâng 80°.
- `SERVO_CALIBRATED=False`: thông báo chưa đo xung, không chặn thử.

Trước khi khởi động, chuẩn bị tay ở mốc hạ −10° như người dùng đã xác nhận.
Không tự ép tay xuống hết điểm chặn cơ khí. Bộ điều khiển
không có phản hồi góc và lần phát xung đầu vẫn sẽ yêu cầu mốc khởi đầu này.

1500/500 µs là cấu hình giả định cho lần thử được người dùng yêu cầu.
500–2500 µs là dải điện của servo DS-S006M, không phải hành trình an toàn của cơ cấu lắp ráp.
Các số −10° và 80° là tên mốc của tay, không cung cấp đủ thông tin để tự suy ra xung.
Chương trình chưa có cảm biến góc, công tắc giới hạn hoặc đo dòng để tự nhận ra
tay đã chạm chặn. Nếu gặp điểm chặn, dùng Ctrl+C để dừng và hiệu chỉnh lại hai
mốc theo vị trí thực tế còn khoảng hở. Không cần đổi dây BCM 18/BCM 12.
Xung thiếu, không hữu hạn, bằng nhau hoặc ngoài dải điện vẫn bị từ chối trước
khi mở đầu ra; lỗi/ngắt giữa chuyển động vẫn làm mất mốc vị trí và cần khởi động lại.

`SERVO_HOLD_POSITION=True` đang giữ lực đỡ tay. Không đổi thành False để che rung:
ngắt xung có thể làm tay hạ theo tải và không sửa được việc đi quá hành trình.

## Phương án phát xung mà không đổi dây

Pi đã báo có overlay `pwm-gpio` và module tại
`/lib/modules/6.12.47+rpt-rpi-v8/kernel/drivers/pwm/pwm-gpio.ko.xz`.
Driver này dùng bộ định thời phân giải cao của kernel để tạo PWM bằng GPIO.
`main.py` đã dùng `KernelPWMLiftOutput` trên driver này, giữ BCM 18 độc lập với
PWM phần cứng BCM 12. Đây vẫn là PWM phần mềm, không phải kênh PWM phần cứng thứ
hai. Chưa xác nhận độ rung trên xe thật; thay nguồn xung không thay thế việc
hiệu chỉnh giới hạn cơ khí.

Thoát các chương trình servo, mở `/boot/firmware/config.txt`. Dưới `[all]`, giữ
cấu hình càng và thêm overlay riêng cho nâng/hạ:

```ini
dtparam=audio=off
dtoverlay=pwm,pin=12,func=4
dtoverlay=pwm-gpio,gpio=18
```

Khởi động lại rồi từ `~/vehicle_testing` chạy:

```sh
.venv/bin/python check_lift_pwm.py
```

Lệnh chỉ đọc `compatible`, `gpios`, `npwm` trong sysfs/device tree và kiểm tra
cấu hình; không export, enable hay phát PWM. Kết quả báo BCM 18 thuộc
`pwmchipN`, channel 0 và trạng thái hiệu chỉnh. Số N có thể thay đổi sau reboot;
phần mềm tự nhận diện đúng GPIO và driver. Nếu không có hoặc có nhiều provider
khớp, lệnh báo lỗi, không chọn đại một chip.

Càng giữ `CLAW_PWM_CHIP` được cấu hình riêng. Nếu chip đổi số, công cụ báo
driver phần cứng để kiểm tra và cập nhật cấu hình; đầu ra càng chặn chip không
đúng loại trước khi xuất xung. Không dùng cùng một chip cho hai servo.
BCM 18 có thể hiển thị chức năng GPIO output trong `pinctrl`, vì đây là driver
GPIO thay vì chức năng Alt PWM0.

Không chạy `probe_servo.py --pin 18`/`RPi.GPIO` trên BCM 18 khi overlay đã nạp,
kể cả sau khi thoát `main.py`. Không có phương án tự quay về đầu ra cũ khi lỗi.
Thư viện `rpi-hardware-pwm` có sẵn trong requirements dùng được qua sysfs của
provider này; không cần thêm daemon hoặc chuyển dây.

Khi tay ở mốc hạ, chạy `sudo .venv/bin/python main.py` và thử riêng
`nang 4`, `chay`; quan sát trước khi thử `ha 4`, `chay`.
Sau khi đo lại hai xung theo cơ cấu, có thể thay `SERVO_DOWN_PULSE_US`,
`SERVO_UP_PULSE_US` và đặt `SERVO_CALIBRATED=True` để ghi nhận đã hiệu chỉnh.
Không sao chép xung mẫu từ unit test như một kết quả đo trên xe.
Chương trình chuyển yêu cầu theo bước tối đa 20 ms, nhẹ ở hai đầu, không
khởi động lại PWM giữa các bước. Vẫn giữ lực nâng sau lệnh theo cấu hình cũ.

## Nguồn kỹ thuật

- [Linux: driver pwm-gpio dùng high-resolution timer](https://cdn.kernel.org/doc/html/latest/driver-api/gpio/drivers-on-gpio.html)
- [Raspberry Pi Linux 6.12: overlay pwm-gpio và tham số gpio](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/overlays/pwm-gpio-overlay.dts)
- [DS-S006M: dải xung và giới hạn của servo](https://www.dspowerservo.com/ds-s006m-metal-gear-9g-servo-micro-servo-product/)
- [Adafruit: hiệu chỉnh xung và tránh giới hạn cơ khí](https://learn.adafruit.com/16-channel-pwm-servo-driver/using-the-adafruit-library)
