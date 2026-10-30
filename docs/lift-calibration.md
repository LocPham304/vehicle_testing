# Cấu hình thử nâng/hạ −10°/80° và hiệu chỉnh xung

Code hiện tại: `hardware/servos.py` và `hardware/pwm.py`; cấu hình vẫn sửa ở
`config.py`. Các tên file cũ trong phần lịch sử bên dưới mô tả những lần thử
trước khi sắp xếp thư mục.

Người dùng xác nhận nâng/hạ đến cuối hành trình trong khoảng 1 giây và phần
thời gian còn lại giật mạnh; tay đã chạm hoặc ép vào khung/điểm chặn cơ khí.
Lịch gửi góc trong phần mềm không cho biết vị trí thật. Tăng số giây không tránh
được việc các góc tiếp theo tiếp tục ép vào điểm chặn.

Người dùng yêu cầu giữ hai mốc hạ −10°/nâng 80° để tự thử. Sau khi xác nhận
xung tăng làm tay nâng, cấu hình được đổi sang hạ 650 µs/nâng 1400 µs.
Phản hồi mới: mốc nâng đã tới vị trí mong muốn, mốc hạ chỉ tới đường vàng,
chưa tới đường đỏ, không phải đi tới đích rồi bật lại sau khi tắt PWM.
Sau khi tự thử các thông số, người dùng chọn mốc hạ 450 µs là phù hợp và xác
nhận nâng 1400 µs tạm ổn. Cấu hình được cập nhật theo hai mốc này; chưa kết luận
đã xử lý hết rung nhẹ hoặc đã đo góc thật.

## Cấu hình đang dùng

- `SERVO_DOWN_PULSE_US=450.0`: mốc hạ người dùng đã thử và chọn; mốc cũ 650 µs hạ chưa đủ.
- `SERVO_UP_PULSE_US=1400.0`: mốc nâng đã được người dùng xác nhận tới vị trí mong muốn.
- `SERVO_CALIBRATED=False`: thông báo chưa đo xung, không chặn thử.

Trước khi khởi động, chuẩn bị tay ở mốc hạ −10° như người dùng đã xác nhận.
Không tự ép tay xuống hết điểm chặn cơ khí. Bộ điều khiển
không có phản hồi góc và lần phát xung đầu vẫn sẽ yêu cầu mốc khởi đầu này.

450/1400 µs là cấu hình hiện tại; các số 1500/500 µs ở phần lịch sử dưới đây
thuộc phép thử cũ đã bị loại bỏ. Không tự suy ra giá trị xung từ góc trên hình vẽ.
500–2500 µs là dải danh định được nêu cho DS-S006M, không phải hành trình an toàn
của cơ cấu lắp ráp. Mốc 450 µs là ngoại lệ theo thử nghiệm người dùng trên tay
hiện tại. Bộ kiểm tra riêng nâng/hạ cho phép 450–2500 µs và vẫn chặn dưới
450 µs; phần càng và các công cụ dò khác không đổi giới hạn vì thay đổi này.
Các số −10° và 80° là tên mốc của tay, không cung cấp đủ thông tin để tự suy ra xung.
Chương trình chưa có cảm biến góc, công tắc giới hạn hoặc đo dòng để tự nhận ra
tay đã chạm chặn. Nếu gặp điểm chặn, dùng Ctrl+C để dừng và hiệu chỉnh lại hai
mốc theo vị trí thực tế còn khoảng hở. Không cần đổi dây BCM 18/BCM 12.
Xung thiếu, không hữu hạn, bằng nhau hoặc ngoài dải điện vẫn bị từ chối trước
khi mở đầu ra; lỗi/ngắt giữa chuyển động vẫn làm mất mốc vị trí và cần khởi động lại.

## Kết quả thử thật và bước dò mốc

Người dùng đã thử `nang 4`: tay bật lên ngay khi `chay`, tới điểm chặn rồi giật;
Ctrl+C kết thúc phát PWM và tay vẫn ở trên cao. Trên Pi, đã đọc được:

```text
period: 20000000
duty_cycle: 0
polarity: normal
enable: 0
```

Đây là cấu hình 50 Hz và trạng thái đã tắt sau Ctrl+C, không phải phép đo độ
ổn định của xung lúc servo chạy. Source gửi ngay 1500 µs ở thời điểm đầu, trước
vòng chia bước. Nhãn hạ −10° đang gán cho xung này chưa khớp với một vị trí hạ
đã xác nhận, nên chưa thể coi lần chuyển đầu là chuyển chậm từ đúng vị trí thật.
Không dùng lại phép thử toàn hành trình 1500→500 µs để dò mốc.

`probe_lift_pwm.py` là công cụ dò riêng cho driver kernel BCM 18, không dùng
`RPi.GPIO`. Khởi động và Enter rỗng không mở PWM. Mỗi dấu `+`/`-` thay đổi
5/10/20 µs trong cửa sổ tối đa 200 µs; mỗi lần chỉ yêu cầu một đợt xung ngắn
(mặc định 40 ms, tối đa 100 ms), sau đó tắt. Không tự quét, không sửa config,
không chạy càng. Chế độ thật chỉ nhận lệnh trực tiếp ở terminal, không pipe kịch bản.

**Kết quả dò tiếp theo:** người dùng đã gửi hai lệnh `+`, lần lượt yêu cầu
1510 và 1520 µs trong 40 ms. Tay nâng thêm một chút nhưng giật rất mạnh.
Không tiếp tục quy trình tăng xung 1500→1600 µs từ vị trí trên cao. Hướng tăng
xung đã quan sát làm nâng thêm, không cung cấp một mốc hạ hoặc mốc khởi đầu an toàn.

Phép bật–tắt ngắn chỉ giới hạn thời gian yêu cầu phát; nó có thể góp phần tạo
cú giật và không phải cách điều khiển tốc độ chậm. Bước 10 µs là chênh lệch hai
yêu cầu, không phải sai lệch giữa góc yêu cầu và góc trục thật. Nếu xung tuyệt
đối không khớp vị trí, servo vẫn có thể tạo lực lớn. Đã rút hướng dẫn thử tăng
xung tại điểm chặn; không thay bằng một cặp xung phỏng đoán khác.

Chưa phân biệt được phần giật đến từ tải/điểm chặn, nguồn servo, hoặc độ ổn định
của xung thật. Cần kiểm tra tín hiệu BCM 18 và nguồn khi có tải bằng thiết bị
đo hoặc người có kinh nghiệm phần cứng, trước khi chọn mốc và cách phát tiếp.
Không có phép đọc sysfs hay unit test nào thay thế phép đo này. Giữ CLI
−10°/80° theo yêu cầu, nhưng chưa xác nhận hai xung ứng với hai vị trí thực tế.

Để chỉ xem cách công cụ tạo yêu cầu mà không phát PWM:

```sh
.venv/bin/python probe_lift_pwm.py --start-us 1500 --min-us 1500 --max-us 1600 --dry-run
```

Ngắt PWM không giữ lực đỡ tay; việc tay hiện chưa tụt không chứng minh giữ được
với tải khác. Các số µs là tín hiệu yêu cầu, không phải số độ hoặc kết quả đo trục.

Theo yêu cầu nhả lực sau lệnh, mặc định `SERVO_HOLD_POSITION=False`: kết thúc
hành trình và chờ 0,1 giây rồi tắt PWM. Cơ cấu có thể hạ theo tải khi mất lực giữ;
thay đổi này không sửa được việc đi quá hành trình. Nếu dịch chuyển tay bằng tay,
chuẩn bị lại mốc hạ và khởi động lại trước khi chạy tiếp vì không có phản hồi góc.

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

Sau khi tìm được hai xung không ép vào chặn và cập nhật config, khi tay ở mốc hạ,
chạy `sudo .venv/bin/python main.py` và thử riêng
`nang 4`, `chay`; quan sát trước khi thử `ha 4`, `chay`.
Sau khi đo lại hai xung theo cơ cấu, có thể thay `SERVO_DOWN_PULSE_US`,
`SERVO_UP_PULSE_US` và đặt `SERVO_CALIBRATED=True` để ghi nhận đã hiệu chỉnh.
Không sao chép xung mẫu từ unit test như một kết quả đo trên xe.
Chương trình chuyển yêu cầu theo bước tối đa 20 ms, nhẹ ở hai đầu, không
khởi động lại PWM giữa các bước. Mặc định tắt PWM sau hành trình và chờ cuối;
chỉ giữ lực khi bật lại `SERVO_HOLD_POSITION=True`.

## Nguồn kỹ thuật

- [Linux: driver pwm-gpio dùng high-resolution timer](https://cdn.kernel.org/doc/html/latest/driver-api/gpio/drivers-on-gpio.html)
- [Raspberry Pi Linux 6.12: overlay pwm-gpio và tham số gpio](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/overlays/pwm-gpio-overlay.dts)
- [DS-S006M: dải xung và giới hạn của servo](https://www.dspowerservo.com/ds-s006m-metal-gear-9g-servo-micro-servo-product/)
- [Adafruit: hiệu chỉnh xung và tránh giới hạn cơ khí](https://learn.adafruit.com/16-channel-pwm-servo-driver/using-the-adafruit-library)
- [Pololu: xung điều khiển vị trí, chiều quay và giới hạn cần hiệu chỉnh theo servo](https://www.pololu.com/blog/17/servo-control-interface-in-detail)
