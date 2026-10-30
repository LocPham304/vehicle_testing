# PWM phần cứng cho càng BCM 12 trên Pi 4 / Debian 13 Trixie

Phần điều khiển servo hiện nằm trong `hardware/servos.py`, nhận diện driver
trong `hardware/pwm.py`. `config.py`, `main.py` và `check_lift_pwm.py` vẫn dùng
tại thư mục gốc như các lệnh dưới đây.

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

Nâng/hạ BCM 18 hiện dùng overlay riêng `dtoverlay=pwm-gpio,gpio=18` và bộ định
thời kernel, giữ nguyên dây. Đây là driver khác, không lấy PWM0 của càng.
Xem [thiết lập và hiệu chỉnh nâng/hạ](lift-calibration.md). Sau khi thêm overlay,
chạy `check_lift_pwm.py` để kiểm tra số chip; đầu ra càng kiểm tra loại driver
trước khi mở `CLAW_PWM_CHIP`, tránh chọn nhầm chip GPIO khi kernel đổi số.

Nếu file không tồn tại hoặc cấu hình boot của máy ở đường dẫn khác, xác định
file đang được dùng trước khi chỉnh. Sau khi lưu, khởi động lại Pi:

```sh
sudo reboot
```

## Thư viện và quyền truy cập

Trên Debian 13, pip có thể báo `externally-managed-environment` khi dùng Python
hệ thống. Trong thư mục `vehicle_testing`, tạo và kích hoạt môi trường ảo trước:

```sh
sudo apt install python3-venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -s -m pip install --no-user -r requirements.txt
python -m pip show rpi-hardware-pwm
```

`--system-site-packages` cho phép dùng lại các gói GPIO đã cài qua apt, trong khi
pip ghi các gói mới vào `.venv`. Nếu môi trường `.venv` đã được tạo cho dự án,
chỉ cần kích hoạt và cài requirements. Mỗi terminal mới cần chạy lại
`source .venv/bin/activate`. Không cài bằng pip vào Python hệ thống.

`-s` bỏ qua thư viện riêng trong `/home/pi/.local` khi pip kiểm tra các gói đã
cài. Nhờ vậy, các gói cần thiết được cài vào `.venv` thay vì pip báo đã có ở thư
mục riêng của `pi`, nơi Python chạy bằng `sudo` không tìm thấy. `--no-user` giữ
đích cài trong môi trường ảo. Các gói hệ thống qua apt vẫn được dùng lại.

Nếu đã gặp `Requirement already satisfied ... /home/pi/.local/...` rồi chạy
bằng sudo lại báo thiếu `board`, sửa ngay trong thư mục `vehicle_testing`:

```sh
.venv/bin/python -s -m pip install --no-user adafruit-blinka adafruit-circuitpython-pca9685
sudo .venv/bin/python -c "import board; import busio; from adafruit_pca9685 import PCA9685; print(board.__file__); print('Import OK')"
```

Chỉ tiếp tục chạy phần cứng khi bước kiểm tra import đã thành công.

Thư viện `rpi-hardware-pwm` dùng sysfs của kernel; không cần pigpio/pigpiod.
Sau khi cấu hình boot ở trên đã được áp dụng, kiểm tra và chạy:

```sh
ls -l /sys/class/pwm/
python main.py
```

Nếu thiếu quyền ghi sysfs, thử đúng trình thông dịch Python hiện tại với sudo:

```sh
sudo "$(command -v python)" main.py
```

Sau khi nạp cả overlay càng và nâng/hạ, kết quả thực tế trên Pi đã xác nhận
`pwmchip0` là `pwm-gpio` BCM 18, `pwmchip1` là bộ PWM phần cứng cho càng.
Cấu hình hiện tại là `CLAW_PWM_CHIP=1`, `CLAW_PWM_CHANNEL=0`; số chip 1 không
thay đổi việc BCM 12 vẫn dùng kênh PWM0. Chạy lại `check_lift_pwm.py` nếu số chip
thay đổi; chỉ đổi `CLAW_PWM_CHIP` sau khi xác định đúng driver phần cứng.
Không chọn chip khác chỉ để bỏ qua thông báo lỗi. Phần mềm không tự quay về PWM cũ khi lỗi cấu hình.

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

## Log chẩn đoán càng tự đóng hoặc giật

`main.py --verbose` ghi các góc và độ rộng xung đã gửi qua thư viện PWM. Đây là
giá trị phần mềm yêu cầu, không phải góc đo hoặc tín hiệu đo trên chân GPIO.
Các dòng INFO phân biệt ba thời điểm: đã gửi góc đích, bắt đầu ngắt PWM cuối
lượt, và bị lỗi/ngắt trước khi dọn đầu ra. Góc, dải xung và chế độ nhả lực không
thay đổi khi bật log; việc ghi log có thể làm tăng thời gian thực hiện.

Có thể kiểm tra luồng log mà không chuyển động phần cứng:

```sh
python3 main.py --dry-run --verbose
```

Nếu càng đã đóng sập hoặc giật mạnh, không lặp lại hành trình để lấy log trên
cơ cấu đang chịu tải. Trước hết kiểm tra ánh xạ PWM, chương trình khác đang chạy
và giới hạn cơ khí. Log không chứng minh phần cứng an toàn hoặc đã sửa hết lỗi.

## Nguồn kỹ thuật

- [Raspberry Pi: overlay PWM và ánh xạ chân](https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README)
- [rpi-hardware-pwm: cài đặt và API](https://github.com/Pioreactor/rpi_hardware_pwm)
- [GPIO Zero: giới hạn pigpio trên Debian mới](https://gpiozero.readthedocs.io/en/stable/remote_gpio.html)
