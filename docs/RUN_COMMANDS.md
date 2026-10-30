# Lệnh chạy robot qua MQTT, USB, Wi-Fi và Bluetooth

Dành cho hệ thống đã cài thư viện, cấu hình USB gadget và ghép đôi Bluetooth.
Thông tin hiện tại: Pi `192.168.1.40`; broker bên BE `192.168.1.93:1883`;
UUID MQTT `robot-003`. Nếu Pi đổi IP, thay IP trong lệnh client Wi-Fi.

Các lệnh receiver dưới đây dùng **--run, điều khiển motor/LED thật khi nhận RUN**.
Muốn mô phỏng, thay `--run` bằng `--dry-run`. Upload chỉ kiểm tra/lưu kịch bản;
cần gửi RUN/Execute riêng. Chỉ mở một receiver điều khiển phần cứng mỗi lần.

## Chuẩn bị chung

Trên Pi, mỗi terminal receiver:

```bash
cd ~/vehicle_testing
source .venv/bin/activate
```

Trên laptop Windows, mở PowerShell ở thư mục source:

```powershell
cd C:\Project\SIGINX\raspberry-py\vehicle_testing
```

## 1. MQTT — nhận từ FE/BE

Giữ Pi có đường mạng đến broker `192.168.1.93`. Trên Pi:

```bash
python3 scratch_receiver.py --broker 192.168.1.93 --port 1883 --device-id robot-003 --run
```

Giữ terminal này mở. Trên FE chọn đúng robot, bấm Upload rồi Run; BE cần gửi:

| Thao tác | Topic | Payload |
| --- | --- | --- |
| Upload | `device/robot-003/code` | Source UTF-8 gốc |
| Run | `device/robot-003/execute` | `execute`, retain=false |
| Stop | `device/robot-003/stop` | `stop`, retain=false |

Không nhập `/execute` vào terminal receiver: receiver chờ MQTT message.

Nếu thử bằng tay, mở **terminal khác trên cùng Pi**, đứng trong `~/vehicle_testing`
và gửi file mẫu rồi lệnh Execute riêng:

```bash
mosquitto_pub -h 192.168.1.93 -p 1883 -q 1 -t 'device/robot-003/code' -f examples/scratch_sample.txt
mosquitto_pub -h 192.168.1.93 -p 1883 -q 1 -t 'device/robot-003/execute' -m 'execute'
```

Yêu cầu dừng:

```bash
mosquitto_pub -h 192.168.1.93 -p 1883 -q 1 -t 'device/robot-003/stop' -m 'stop'
```

Nếu FE/BE đã gửi đúng thì không cần terminal gửi tay. Broker đặt ở máy BE;
không cần chạy thêm Mosquitto trên Pi. Các lệnh thử tay cần `mosquitto-clients`.

## 2. USB Serial

Cắm cáp dữ liệu laptop → USB-C Pi; USB gadget trên Pi phải có `/dev/ttyGS0`.
Trên Pi:

```bash
python3 usb_receiver.py --run
```

Trên PowerShell laptop:

```powershell
python usb_client.py
```

Chọn số thứ tự COM USB của Pi. Nếu đã biết cổng, ví dụ COM3:

```powershell
python usb_client.py --port COM3
```

Nhập `upload`, rồi `run` tại dấu nhắc `usb>`.

## 3. Wi-Fi

### UDP broadcast từ FE/BE đang dùng

Trên Pi sau khi cập nhật source:

```bash
python3 wifi_udp_receiver.py --device-id robot-003 --run
```

Trên web chọn Wi-Fi, **Upload Code → Chạy Code**. Không mở `wifi_client.py`.
Muốn thử mô phỏng thì thay `--run` bằng `--dry-run`. Receiver nghe UDP 50000,
lọc UUID, tự nhận IP BE từ upload hợp lệ; không cần nhập IP. EXEC phải đến từ
BE vừa upload. Khi BE đổi IP, upload lại để tự nhận địa chỉ mới.
Mỗi upload cho phép một EXEC. Chạy lại cần upload lại.
Chưa có dò xe/ACK/STOP/heartbeat từ BE; chỉ hỗ trợ code trong một datagram.
Xem [chi tiết và giới hạn UDP](WIFI_UDP.md).

### HTTP trực tiếp bằng client thử nghiệm

Laptop có đường mạng tới Pi; cách đang thử là cùng mạng Wi-Fi. Không cần broker.
Trên Pi:

```bash
python3 wifi_receiver.py --run
```

Trên PowerShell laptop:

```powershell
python wifi_client.py --host 192.168.1.40
```

Nhập `upload`, rồi `run` tại dấu nhắc `wifi>`.
Địa chỉ này là **IP Pi**, khác địa chỉ broker `192.168.1.93`.

## 4. Bluetooth Classic SPP

Laptop đã ghép đôi và được trust trên Pi thì thường không cần ghép đôi lại.
Trong terminal Pi đã kích hoạt venv:

```bash
sudo rfkill unblock bluetooth
sudo systemctl start bluetooth
bluetoothctl power on
python3 bluetooth_receiver.py --run
```

Chờ thông báo đã đăng ký SPP. Trên PowerShell laptop:

```powershell
python bluetooth_client.py
```

Chọn số thứ tự **COM Outgoing Bluetooth của Pi**. Có thể xem hướng cổng trong
More Bluetooth settings → COM Ports. Không suy ra hướng từ số COM4/COM5.
Nếu đã xác định được cổng, ví dụ COM5:

```powershell
python bluetooth_client.py --port COM5
```

Nhập `upload`, rồi `run` tại dấu nhắc `bt>`.
Bluetooth truyền kịch bản không cần Wi-Fi/broker. Receiver hiện chưa tự chạy khi
bật Pi; nếu dùng SSH để mở receiver thì vẫn giữ terminal SSH đó mở.

## Lệnh trong console USB / Wi-Fi / Bluetooth

Nhập từng dòng và Enter, upload không tự chạy:

```text
status
upload
run
stop
exit
```

`upload` mặc định đọc `examples/scratch_sample.txt` **trên laptop**. File khác:

```text
upload "C:\thu muc\kich-ban.txt"
```

Giữ client mở để duy trì heartbeat. USB/Wi-Fi HTTP/Bluetooth mất heartbeat mặc định
5 giây sẽ yêu cầu dừng và xóa bản chờ; cần upload lại khi kết nối lại. MQTT
phụ thuộc kết nối Pi–broker, không dùng heartbeat của các client COM/HTTP này.

Sau khi Pi khởi động lại, bản chờ trong RAM mất; mọi phương thức đều cần upload
lại. Dùng Ctrl+C để đóng receiver và yêu cầu dọn lượt chạy hiện tại trước khi
chuyển phương thức. Kiểm tra log để phân biệt mô phỏng và phần cứng thật.

Hướng dẫn cấu hình lần đầu: [USB](USB.md), [Wi-Fi](WIFI.md),
[Bluetooth](BLUETOOTH.md).
