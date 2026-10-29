# Thử điều khiển robot qua USB-C

Code triển khai nằm trong `connections/usb/`; `usb_receiver.py` và
`usb_client.py` ở ngoài cùng giữ nguyên các lệnh chạy trong hướng dẫn này.
Logic bản chờ/worker nằm trong `runtime/session.py`, console nhập lệnh trong
`runtime/console.py`.

## Cách nối và giới hạn đã xác nhận

Laptop Windows -> cáp USB có truyền dữ liệu -> cổng USB-C của Raspberry Pi 4.
Đây là cổng ngoài cùng bên trái trong ảnh người dùng gửi, cạnh hai micro-HDMI;
hai micro-HDMI và giắc âm thanh không dùng truyền lệnh USB. Các cổng USB-A
chữ nhật của Pi là cổng host, không dùng cáp USB-A--USB-A nối thẳng hai máy.

Pi được cấu hình thành USB CDC ACM (serial gadget). Windows thấy cổng COM,
chẳng hạn COM5; Pi thấy `/dev/ttyGS0`. Không cần IP, Wi-Fi, MQTT hay backend.
Mã chạy nằm trong `vehicle_testing`, chưa thay đổi `stem_firmware`.

Người dùng xác nhận USB-C trống khi xe chạy pin. Điều đó cho thấy Pi đang được
cấp nguồn theo đường khác; chưa có sơ đồ xác nhận cơ chế chống cấp ngược 5 V
của bo mở rộng. Xác nhận bo nguồn cho phép nối USB từ laptop khi xe dùng pin
trước khi cắm; không tự ghép nguồn, cắt dây USB hoặc đấu pin trực tiếp vào GPIO.
Giữ nguồn motor từ hệ thống nguồn robot, không dựa vào laptop cấp nguồn motor.

## 1. Cấu hình một lần trên Pi

Phần này làm qua SSH trước; chương trình USB chưa tự sửa cấu hình boot.
Các lệnh dưới dành cho Pi 4 dùng Raspberry Pi kernel, như log Pi trước đó.

Kiểm tra module và file boot trước:

```sh
modinfo dwc2
modinfo g_serial
ls /boot/firmware/config.txt
ls /sys/class/udc
```

Nếu thiếu module hoặc khác đường dẫn boot, dừng ở đây và kiểm tra OS/kernel;
không dùng cấu hình của Pi Zero/USB Ethernet thay thế một cách tùy ý.

Mở config, giữ nguyên các cấu hình GPIO/PWM/I2C hiện có:

```sh
sudo nano /boot/firmware/config.txt
```

Trong phần `[all]`, thêm (nếu đã có overlay `dwc2`, chỉnh dòng đó thay vì thêm trùng):

```ini
[all]
dtoverlay=dwc2,dr_mode=peripheral
```

Để module serial gadget tự nạp khi boot:

```sh
sudo nano /etc/modules-load.d/vehicle-usb.conf
```

Nội dung:

```text
dwc2
g_serial
```

Không bật đồng thời `g_ether`, g_mass_storage hoặc một gadget ConfigFS khác đang
chiếm cùng USB controller. Công cụ `rpi-usb-gadget` dành cho Ethernet/RNDIS,
không thay thế cho cấu hình COM serial này.

Cho tài khoản chạy robot quyền mở serial, rồi reboot:

```sh
sudo usermod -aG dialout "$USER"
sudo reboot
```

Sau khi Pi lên lại:

```sh
ls /sys/class/udc
ls -l /dev/ttyGS0
```

Nếu `serial-getty@ttyGS0.service` đang chạy, dừng dịch vụ đó để cổng không bị
dùng làm màn hình đăng nhập:

```sh
systemctl is-active serial-getty@ttyGS0.service
# Chỉ khi đang active:
sudo systemctl disable --now serial-getty@ttyGS0.service
```

## 2. Chạy bộ nhận trên Pi

Trong thư mục `vehicle_testing`, kích hoạt môi trường Python đang dùng:

```sh
python3 -m pip install -r requirements-usb.txt
python3 usb_receiver.py --dry-run
```

Chế độ này thực thi kịch bản qua đầu ra mô phỏng, không mở motor/LED và không
chờ thời gian chuyển động/cuộn chữ. Sau khi xác nhận đường USB, dừng bằng Ctrl+C
và bật phần cứng thật:

```sh
python3 usb_receiver.py --run
```

Không có hai cờ trên thì RUN chỉ in preview. Chương trình mặc định mở
`/dev/ttyGS0`, baud 115200; có thể đổi bằng `--port` và `--baud`. Với USB gadget,
baud là cấu hình cổng, không phải tốc độ USB vật lý. Không chạy đồng thời MQTT
receiver `--run`, runner riêng hoặc ứng dụng khác điều khiển cùng phần cứng.

## 3. Chạy bộ gửi trên laptop Windows

Cắm cáp dữ liệu vào cổng USB-C của Pi sau khi đã xác nhận nguồn phù hợp.
Trong Device Manager > Ports (COM & LPT), kiểm tra có USB Serial Device/COM.
Cáp chỉ sạc không tạo cổng COM; số COM do Windows gán, không cố định là COM5.

Trong PowerShell Windows thật, không phải cửa sổ SSH:

```powershell
cd C:\Project\SIGINX\raspberry-py\vehicle_testing
python -m pip install -r requirements-usb.txt
python usb_client.py
```

Chọn số tương ứng với cổng COM của Pi trong danh sách. Có thể chỉ định trực tiếp:

```powershell
python usb_client.py --port COM5
```

Lệnh sử dụng:

```text
usb> upload
usb> status
usb> run
usb> stop
usb> exit
```

- `upload`: đọc file `examples/scratch_sample.txt` trên laptop, gửi và chờ Pi
  xác nhận. **Không tự RUN.** File mặc định theo vị trí script, không theo cwd.
- `upload C:\duong-dan\kich-ban.txt`: chọn file UTF-8 khác, đường dẫn có dấu
  cách cũng được. Nguồn tối đa 64 KiB, cùng tập lệnh parser hiện tại.
- `status`: xem `uploaded`, trạng thái và chế độ của Pi. Chế độ `runner` nghĩa
  là chạy runner; xem log khởi động trên Pi để phân biệt mô phỏng/phần cứng.
- `run`: chạy chính kịch bản vừa upload; không lấy file có sẵn trên Pi.
- `stop`: yêu cầu ngắt kịch bản đang chạy; có thể tiếp tục upload/run sau đó.
- `exit`/Ctrl+C: gửi yêu cầu stop rồi đóng cổng.

Hai thao tác upload và run là hai lần nhập riêng. Pi trả các sự kiện block và
trạng thái `executing`, `done`, `stopped`, `error` về cùng cổng USB. Motor/LED
được giải phóng sau mỗi lượt. Chạy chương trình USB trên Pi vẫn phải khởi động
một lần; bước này chưa cài dịch vụ tự chạy cùng Pi hoặc tích hợp Web Serial.

Giữ `usb_client.py` mở trong lúc sử dụng: nó tự gửi ping mỗi giây. Khi rút dây,
đóng ứng dụng hoặc không nhận tin hợp lệ trong 5 giây, Pi yêu cầu dừng và xóa
kịch bản chờ. Khi kết nối lại phải upload lại. Đây là dừng phần mềm có độ trễ;
lỗi I2C/GPIO hoặc nguồn vẫn có thể ngăn việc gửi lệnh dừng.

## Giao thức cho FE hoặc công cụ khác tích hợp sau

Mỗi gói là một dòng UTF-8 JSON, kết thúc bằng byte LF. Dấu xuống dòng trong
source nằm trong trường `code` và phải được JSON escape, không gửi raw source.

```json
{"id":"request-1","action":"upload","code":"report_block(\"a\")\nrobot.sendCmd(\"move_forward:2\")"}
{"id":"request-2","action":"run"}
{"id":"request-3","action":"stop"}
{"id":"request-4","action":"status"}
{"id":"request-5","action":"ping"}
```

Phản hồi có cùng `id`, `ok`, `status` hoặc `error`. Sự kiện tự phát có trường
`event`, không có `id`. Không coi ACK `accepted` là hoàn thành; chờ sự kiện
`done`. Khung tối đa 512 KiB; giới hạn source vẫn 64 KiB UTF-8 và 1000 sự kiện.
64 ID gần nhất của upload/run/stop được nhớ để gói trùng không chạy lặp; cùng ID
mà khác nội dung bị từ chối. Muốn chạy lại có chủ ý, gửi ID mới. Pi chỉ chạy một
kịch bản; RUN khi đang bận bị từ chối, không xếp hàng.

## Kiểm tra phần mềm

Từ thư mục cha `raspberry-py`:

```sh
python -B -m unittest vehicle_testing.tests.test_usb vehicle_testing.tests.test_usb_client -v
```

Kiểm thử phần mềm không xác nhận cáp, driver COM, nguồn, module gadget hay motor
trên xe thật. Các phần này phải được xác nhận trên Pi/Windows của người dùng.

Nguồn cấu hình phần cứng:
- [Raspberry Pi: Using OTG mode on Raspberry Pi SBCs](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-009276-WP/Using-OTG-mode-on-Raspberry-Pi-SBCs)
- [Linux: Gadget Serial](https://docs.kernel.org/usb/gadget_serial.html)
- [Microsoft: USB serial driver](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-driver-installation-based-on-compatible-ids)
