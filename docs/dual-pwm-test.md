# File thử riêng: hai kênh PWM phần cứng trên Pi 4

`dual_pwm_test.py` chạy độc lập, có thể chỉ chép một file này sang Pi. Nó dùng
thư viện `rpi-hardware-pwm` đã cài, không nhập cấu hình hay controller xe, không
đụng PCA9685 điều khiển bánh. Chương trình chính vẫn dùng cấu hình BCM 18 cũ.

| Cơ cấu | Chân tín hiệu | Kênh phần cứng | Mốc xung trong file thử |
| --- | --- | --- | --- |
| Càng | BCM 12 | 0 | Mở 500 µs, đóng 1611 µs |
| Nâng/hạ | BCM 13 | 1 | Hạ −10°: 600 µs; nâng 80°: 1700 µs |

600/1700 µs là giá trị thử từ mẫu người dùng gửi (duty 3%/8,5% ở 50 Hz), chưa
được đo tương ứng với góc tay thực tế. Hardware PWM không tự tránh điểm chặn,
không xác nhận đủ lực, nguồn ổn định hoặc góc khởi đầu đúng. Chưa có thử nghiệm
vật lý xác nhận file mới hết giật.

## Thử luồng trước, giữ nguyên dây và overlay hiện tại

Từ thư mục `~/vehicle_testing` trên Pi:

```sh
.venv/bin/python dual_pwm_test.py --dry-run
```

Trên Windows từ gốc repo:

```powershell
python vehicle_testing/dual_pwm_test.py --dry-run
```

Nhập `nang 4`, `ha 4`, `thoat`, mỗi lệnh một dòng. Lệnh chạy ngay, không gõ
`chay`. Dry-run giữ thời gian chờ nhưng không đọc sysfs/GPIO hoặc nhập thư viện
phần cứng. Không tự phát xung khi khởi động hoặc khi gõ dòng rỗng.

## Điều kiện để thử thật

1. Khi tắt nguồn cơ cấu, chuyển tín hiệu nâng/hạ từ BCM 18 sang đúng cổng servo
   tương ứng BCM 13 trên bo mở rộng. Xác định cổng theo tài liệu bo; không đoán
   theo giắc nằm cạnh nhau. Giữ đúng dây nguồn/GND.
2. Trong `/boot/firmware/config.txt`, bỏ/comment cả hai overlay cũ
   `pwm,pin=12,func=4` và `pwm-gpio,gpio=18`. Dưới `[all]`, giữ UART nếu đang dùng:

   ```ini
   enable_uart=1
   dtparam=audio=off
   dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
   ```

3. Reboot Pi rồi kiểm tra, chưa chạy servo:

   ```sh
   .venv/bin/python dual_pwm_test.py --check
   ```

`--check` chỉ đọc metadata và gọi `pinctrl get 12` / `pinctrl get 13`. File tìm
driver Broadcom PWM0 của Pi 4 (địa chỉ bus device-tree 0x7e20c000), có ít nhất
hai kênh, và yêu cầu cả hai chân ở Alt0. Không export kênh hoặc tạo đối tượng
HardwarePWM. Chương trình không kiểm tra được dây cắm thực tế. Chip có thể đổi
số sau reboot; không mặc định chip 0. Nếu cần chọn rõ, dùng `--chip N`; chip
được chỉ định vẫn phải đúng driver và có đủ hai kênh.

## Phiên thử thật

Sau khi bước kiểm tra đạt và dây đã đúng, thoát `main.py` / các chương trình
servo khác. Chuẩn bị tay ở mốc hạ và càng khép theo vị trí khởi đầu giả định:

```sh
sudo .venv/bin/python dual_pwm_test.py --start down
```

Nhập `nang 4` để gửi yêu cầu nâng trong 4 giây, sau đó quan sát. Nhập `ha 4` để
hạ sau khi đã kiểm tra phản ứng. Có thể dùng `mo_cang 4` / `dong_cang 4` để thử
kênh 0 riêng. Thời gian mặc định 4 giây; nhận 2–60 giây, sau đó thêm 0,1 giây
cho xung cuối. Có thể chọn trạng thái ban đầu `--start up` khi tay ở mốc nâng;
đây chỉ là khai báo trạng thái, không tự di chuyển hoặc đọc được góc.

Lịch chuyển dựa trên đồng hồ đơn điệu và thời gian đã trôi qua, tránh cộng dồn
thời gian ghi sysfs vào từng lần ngủ 20 ms. Việc mở đầu ra, thời gian ghi và
lịch chạy Linux vẫn có thể làm tổng thời gian khác thời gian danh định;
chương trình không phải bộ điều khiển thời gian thực cứng.

Mỗi kênh chỉ được mở khi có lệnh chuyển động đầu tiên. Lệnh đầu phát ngay xung
mốc khởi đầu giả định; nếu xung này không khớp vị trí thật, tay vẫn có thể bật
nhanh. Quét theo đường cong nhẹ hai đầu, chỉ đổi duty trong lúc chuyển, không
bật/tắt PWM ở từng bước. PWM tiếp tục được giữ sau lệnh, tới khi kết thúc phiên.

`thoat`, `dung`, EOF, Ctrl+C hoặc lỗi đều kết thúc phiên và thử tắt mọi kênh
đã mở, kể cả khi một lần tắt lỗi. Không tự chạy tay về vị trí thấp lúc thoát.
Ngắt PWM không giữ lực đỡ tay; nếu chạm chặn/giật mạnh, Ctrl+C kết thúc thử.

Tham số `--down-us` / `--up-us` cho phép thay hai mốc khi đã có dữ liệu thực tế;
file không ghi vào `config.py`. Cả hai phải hữu hạn, khác nhau và trong
500–2500 µs. Khoảng điện này không xác nhận hành trình cơ khí an toàn.

## Nguồn và kiểm tra

- [Raspberry Pi: overlay hai kênh và tham số pin2/func2](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/overlays/pwm-2chan-overlay.dts)
- [Device tree: địa chỉ PWM0 của Pi 4](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/arch/arm/boot/dts/broadcom/bcm283x.dtsi)
- [rpi-hardware-pwm: API](https://github.com/Pioreactor/rpi_hardware_pwm)

Unit tests dùng filesystem giả và PWM giả, gồm nhận diện chip, chế độ chân,
không phát khi mở phiên, thời gian chuyển, hai kênh độc lập, ngắt và dừng khi lỗi.
