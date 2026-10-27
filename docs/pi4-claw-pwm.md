# PWM phần cứng cho càng BCM 12 trên Pi 4 / Debian 13 Trixie

Mở yêu cầu 0°, đóng yêu cầu 100°. Trước khi khởi động chương trình, chuẩn bị
càng khép hoàn toàn như vị trí khởi đầu đã thống nhất. Chương trình không đo góc
thật hoặc tự đưa về gốc. Bản sửa phát PWM bằng bộ PWM của kernel, giữ các bước
chuyển góc nhẹ ở hai đầu; cần thử trên xe để xác nhận rung đã giảm.

## Cấu hình Pi một lần

Thoát các chương trình điều khiển servo. Mở file cấu hình boot hiện có:

```sh
sudo nano /boot/firmware/config.txt
```

Giữ nội dung khác của file. Trong phần `[all]`, thêm hoặc điều chỉnh hai dòng:

```ini
dtparam=audio=off
dtoverlay=pwm,pin=12,func=4
```

BCM 12 xuất PWM0, chức năng Alt0 (`func=4`). Không để một overlay PWM khác xuất
cùng kênh ra BCM 18 vì BCM 18 đang nâng/hạ. Audio analog dùng chung bộ PWM nên
bị tắt; cấu hình này không thay đổi PCA9685 điều khiển bánh xe.

Nếu file không tồn tại hoặc cấu hình boot của máy ở đường dẫn khác, xác định
file đang được dùng trước khi chỉnh. Sau khi lưu, khởi động lại Pi:

```sh
sudo reboot
```

## Thư viện và quyền truy cập

Chạy trong thư mục `vehicle_testing`, với môi trường Python hiện đang chạy được
`main.py`:

```sh
python -m pip install -r requirements.txt
ls -l /sys/class/pwm/
python main.py
```

Thư viện `rpi-hardware-pwm` dùng sysfs của kernel; không cần pigpio/pigpiod.
Nếu Python hệ thống bị chặn bởi môi trường được quản lý, dùng môi trường ảo của
dự án theo phần cài đặt trong README; không bỏ qua cơ chế quản lý gói của hệ thống.
Nếu thiếu quyền ghi sysfs, thử đúng trình thông dịch Python hiện tại với sudo:

```sh
sudo "$(command -v python)" main.py
```

Mặc định `CLAW_PWM_CHIP=0`, `CLAW_PWM_CHANNEL=0` trong `config.py` cho Pi 4.
Nếu không có `pwmchip0`, kiểm tra overlay đã nạp và các chip ở `/sys/class/pwm/`;
chỉ đổi `CLAW_PWM_CHIP` sau khi xác định chip của bộ PWM này. Không chọn chip
khác chỉ để bỏ qua thông báo lỗi. Phần mềm không tự quay về PWM cũ khi lỗi cấu hình.

## Thử sau khi cập nhật

Với càng đang khép ở vị trí ban đầu, nhập:

```text
mo_cang 4
chay
```

Quan sát xong mới thử đóng riêng:

```text
dong_cang 4
chay
```

Các lệnh gửi dần góc yêu cầu trong 4 giây, chờ thêm 0,1 giây ở góc cuối rồi ngắt
PWM. Không chạy probe hoặc chương trình GPIO khác đồng thời. Nếu càng chạm cứng,
giật mạnh hoặc không đi theo các góc trung gian, dừng thử: giới hạn cơ khí, nguồn
và phản ứng servo vẫn cần kiểm tra. Mốc 100° là góc yêu cầu theo quan sát người dùng,
chưa phải góc đo hoặc bảo đảm an toàn cơ khí.

## Nguồn kỹ thuật

- [Raspberry Pi: overlay PWM và ánh xạ chân](https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README)
- [rpi-hardware-pwm: cài đặt và API](https://github.com/Pioreactor/rpi_hardware_pwm)
- [GPIO Zero: giới hạn pigpio trên Debian mới](https://gpiozero.readthedocs.io/en/stable/remote_gpio.html)
