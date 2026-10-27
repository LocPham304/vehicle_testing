# Tay chạm điểm chặn: cần hiệu chỉnh hành trình trước khi thử tiếp

Người dùng xác nhận nâng/hạ đến cuối hành trình trong khoảng 1 giây và phần
thời gian còn lại giật mạnh; tay đã chạm hoặc ép vào khung/điểm chặn cơ khí.
Lịch gửi góc trong phần mềm không cho biết vị trí thật. Tăng số giây không tránh
được việc các góc tiếp theo tiếp tục ép vào điểm chặn.

Ánh xạ thử cũ dùng 1500 µs ở mốc −10° và 500 µs ở mốc 80° chưa được hiệu chỉnh
trên cơ cấu. Đã bỏ giả định này khỏi mặc định và khóa riêng nâng/hạ thật trước
khi mở GPIO. Phần càng BCM 12, bánh xe và chế độ mô phỏng vẫn dùng được.

## Dữ liệu cần có để mở lại nâng/hạ

- `SERVO_DOWN_PULSE_US`: xung ứng với vị trí thấp cho phép, còn khoảng hở với điểm chặn.
- `SERVO_UP_PULSE_US`: xung ứng với vị trí cao cho phép, còn khoảng hở với điểm chặn.
- `SERVO_CALIBRATED=True`: chỉ bật sau khi hai vị trí được kiểm tra thực tế.

Vị trí tay trước khi khởi động phải trùng mốc hạ đã hiệu chỉnh ứng với
`SERVO_DOWN_PULSE_US`, không phải ép tay xuống hết điểm chặn cơ khí. Bộ điều khiển
không có phản hồi góc và lần phát xung đầu vẫn sẽ yêu cầu mốc khởi đầu này.

Không tự lấy 500/1500 µs hay một cặp số mới để thử toàn hành trình. 500–2500 µs
là dải điện của servo DS-S006M, không phải hành trình an toàn của cơ cấu lắp ráp.
Các số −10° và 80° là tên mốc của tay, không cung cấp đủ thông tin để tự suy ra xung.
Chương trình chưa có cảm biến góc, công tắc giới hạn hoặc đo dòng để tự nhận ra
tay đã chạm chặn. Cần người có kinh nghiệm cơ cấu/servo hỗ trợ hiệu chỉnh; không
cần yêu cầu người dùng tự tháo dây khi chưa biết cổng và chiều cắm.

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

Sau khi người có kinh nghiệm xác nhận được hai xung an toàn, điền
`SERVO_DOWN_PULSE_US`, `SERVO_UP_PULSE_US` và bật `SERVO_CALIBRATED=True`.
Không sao chép xung mẫu từ unit test: đó là dữ liệu giả, không đo trên xe.
Khi tay ở đúng mốc hạ đã hiệu chỉnh, mới chạy `sudo .venv/bin/python main.py`
và thử riêng `nang 4`, `chay`; quan sát trước khi thử `ha 4`, `chay`.
Chương trình chuyển yêu cầu theo bước tối đa 20 ms, nhẹ ở hai đầu, không
khởi động lại PWM giữa các bước. Vẫn giữ lực nâng sau lệnh theo cấu hình cũ.

## Nguồn kỹ thuật

- [Linux: driver pwm-gpio dùng high-resolution timer](https://cdn.kernel.org/doc/html/latest/driver-api/gpio/drivers-on-gpio.html)
- [Raspberry Pi Linux 6.12: overlay pwm-gpio và tham số gpio](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/overlays/pwm-gpio-overlay.dts)
- [DS-S006M: dải xung và giới hạn của servo](https://www.dspowerservo.com/ds-s006m-metal-gear-9g-servo-micro-servo-product/)
- [Adafruit: hiệu chỉnh xung và tránh giới hạn cơ khí](https://learn.adafruit.com/16-channel-pwm-servo-driver/using-the-adafruit-library)
