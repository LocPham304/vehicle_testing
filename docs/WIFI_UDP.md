# Nhận kịch bản từ FE/BE bằng Wi-Fi UDP broadcast

Receiver: `connections/wifi/udp_receiver.py`; lệnh chạy: `wifi_udp_receiver.py`.
Đây là adapter cho định dạng bắt được trên Pi ngày 30/10/2026, khác công cụ
[HTTP trực tiếp](WIFI.md). Không dùng `wifi_client.py` cho quy trình web này.
Không cần thêm thư viện Python ngoài môi trường phần cứng đang dùng.

## Định dạng BE đang gửi

Một datagram upload có dạng byte UTF-8:

```text
robot-003\nreport_block("block-id")\nrobot.sendCmd("move_forward:1")\n
```

`\n` ở trên là byte xuống dòng thật. Tách tại **xuống dòng đầu tiên**; dòng đầu
là UUID, toàn bộ phần sau là kịch bản. Không có `MAGIC|` trong gói thực tế.
Nhấn Chạy Code gửi chính xác `b'robot-003\nEXEC'` (14 byte).
Không chấp nhận EXEC có thêm khoảng trắng/xuống dòng hoặc chữ thường.

BE mẫu phát từ `192.168.1.93` tới `192.168.1.255:50000`. Pi bind
`0.0.0.0:50000`, không bind vào địa chỉ broadcast. Pi và máy chạy BE cần có
đường truyền broadcast trong cùng LAN. Không cần Internet/MQTT.
Mỗi xe cấu hình `--device-id` riêng; gói cho UUID khác bị bỏ qua trước khi parse.

## Chạy trên Pi

Cập nhật source mới lên Pi trước; file này không tự xuất hiện trên Pi chỉ vì
đã sửa trên laptop. Dừng receiver MQTT/USB/HTTP/Bluetooth điều khiển phần cứng
trước khi chuyển sang UDP; hiện chưa có khóa điều khiển chung giữa tiến trình.
Đóng chương trình Python bắt gói thử đang chiếm UDP 50000 nếu còn mở.

```bash
cd ~/vehicle_testing
source .venv/bin/activate
python3 wifi_udp_receiver.py --device-id robot-003 --dry-run
```

Trên giao diện chọn phương thức Wi-Fi, nhấn **Upload Code**, rồi **Chạy Code**.
Không cần mở client Python trên laptop. Log upload hợp lệ phải có
`status: uploaded`; EXEC có `status: accepted`; worker in `executing`, các block
và `done`. Với `--dry-run` chỉ mô phỏng, xe không di chuyển.

Chạy motor/LED thật: Ctrl+C receiver mô phỏng, rồi mở lại:

```bash
python3 wifi_udp_receiver.py --device-id robot-003 --run
```

Upload lại từ web, rồi Chạy Code. Mặc định không có cờ là preview, EXEC chỉ in
kịch bản.

### Tự nhận địa chỉ BE, không nhập IP thủ công

Mặc định receiver nghe `0.0.0.0:50000`, nên không cần biết trước IPv4 của Pi
hay BE. Gói upload đúng UUID, parse/kiểm tra hợp lệ sẽ ghi nhận IP BE gửi gói;
log hiện `UDP tu dong nhan BE ...`. EXEC chỉ được nhận từ IP vừa upload, cổng
nguồn được phép thay đổi. Upload không tự chạy.

EXEC khác IP BE đã upload bị bỏ qua và có log WARNING chứa UUID, IP gửi và
IP mong đợi. Khi đã biết IP uploader, kiểm tra IP trước trạng thái cho phép
chạy; log kết quả ở Pi, không gửi ACK/trạng thái qua mạng. Chưa upload hợp lệ
thì chưa có IP tin cậy; EXEC chỉ được ghi nhận là cần upload trước.

Khi đổi mạng hoặc DHCP đổi địa chỉ BE, đưa Pi và BE vào cùng mạng có broadcast,
rồi Upload Code lại: receiver tự ghi nhận IP mới, không phải sửa lệnh hay
khởi động lại. IP cũ không được EXEC bản mới. Gói sai UUID không thay đổi BE
đang giữ bản chờ. Không học IP từ EXEC hoặc upload không hợp lệ. Đây là tự nhận
nguồn từ dữ liệu đến, chưa phải giao thức dò/ACK trước upload trên giao diện.

Nếu muốn cố định BE thì vẫn có tùy chọn `--sender-ip <IPv4>`, lọc nguồn trước
khi xử lý mọi gói. Chỉ khi dùng tùy chọn này mới cần cập nhật cờ nếu IP BE đổi.
Lọc IP không phải xác thực người dùng. Phía BE vẫn cần gửi tới địa chỉ broadcast
phù hợp mạng hiện tại; firmware không thể sửa địa chỉ đích trong BE bên ngoài.

Upload chỉ kiểm tra/lưu RAM, không tự chạy. Mỗi upload hợp lệ cho phép EXEC
**một lần**; muốn chạy tiếp cần Upload Code lại. EXEC trước upload hoặc lặp lại
bị từ chối. Upload không hợp lệ làm mất bản chờ cũ. Khi đang chạy, upload mới
bị từ chối; không thay kịch bản giữa chừng. Ctrl+C hủy worker, dừng motor theo
cơ chế runner hiện có và đóng socket. Khởi động lại receiver phải upload lại.

## Giới hạn của giao thức hiện tại

- Tự nhận IP không xác thực BE/học sinh hay cấp quyền điều khiển độc quyền.
  Khi xe rảnh, bất kỳ máy LAN biết UUID và gửi kịch bản hợp lệ đều có thể thay
  bản chờ; **upload hợp lệ gần nhất** xác định IP được EXEC bản đó. Nếu IP khác,
  EXEC từ BE cũ bị bỏ qua, không chạy bản thay thế. `--sender-ip` chỉ lọc IPv4
  nguồn; IP có thể bị giả mạo nên cờ này không thay thế xác thực/phân quyền.
- Chỉ hỗ trợ **toàn bộ kịch bản trong một datagram**. BE đang có `split(body)`
  nhưng chưa gửi mã bản tin, số thứ tự/tổng số mảnh. Receiver không ghép mảnh.
  Một mảnh tình cờ là kịch bản hợp lệ không thể phân biệt với bản hoàn chỉnh;
  chưa dùng cho kịch bản bị BE chia thành nhiều datagram. UDP/IP cũng không
  bảo đảm giao hàng; gói lớn dễ phụ thuộc phân mảnh IP.
- Chưa có mã request hay ràng buộc EXEC với phiên bản code. Cơ chế một EXEC
  mỗi upload chỉ chặn EXEC lặp khi chưa upload mới, không bảo đảm exactly-once
  cho cặp upload/EXEC bị phát lại hay EXEC cũ đến sau upload mới.
- Chưa có hợp đồng gói dò/ACK/trạng thái/STOP/heartbeat từ BE. Adapter hiện
  ghi kết quả tại Pi, **không tự gửi phản hồi định dạng mới**. Nút Kiểm tra trên
  web chưa được tích hợp với adapter này; nhận upload không đồng nghĩa hoàn
  thành quy trình dò/ghép xe cho lớp học.
- Không tự dừng khi mất Wi-Fi vì BE chưa gửi heartbeat. Kịch bản đã nhận có
  thể tiếp tục chạy; Ctrl+C tại Pi yêu cầu dừng. Nếu cần nút dừng từ web và
  mất mạng phải dừng, cần thống nhất các gói này với BE.

Các lệnh, đơn vị và phần cứng dùng parser/runner chung: tiến/lùi theo giây,
quay theo độ ước lượng, LED text theo font đang có; không chạy Python tùy ý.

## Kiểm chứng trên máy phát triển

### Unit test, không cần Pi hoặc mạng thật

Chạy từ **thư mục cha** của `vehicle_testing`; dùng Python đã có sẵn, không cần
cài thư viện test. Không bật receiver phần cứng để chạy unit test.

Trên Pi:

```bash
cd ~/vehicle_testing/..
python3 -B -m unittest vehicle_testing.tests.test_wifi_udp.UdpControlTests vehicle_testing.tests.test_wifi_udp_transport -v
```

Trên PowerShell, từ thư mục `raspberry-py` chứa `vehicle_testing`:

```powershell
python -B -m unittest vehicle_testing.tests.test_wifi_udp.UdpControlTests vehicle_testing.tests.test_wifi_udp_transport -v
```

- `tests/test_wifi_udp.py`: payload bắt được từ BE, upload không tự chạy,
  UUID, IP tự nhận/cố định, EXEC trùng/sai nguồn, UTF-8 và hủy chạy.
- `tests/test_wifi_udp_transport.py`: socket giả, timeout/gói lỗi rồi khôi phục,
  tiếp tục nhận khi worker đang chạy, cấu hình mặc định `0.0.0.0:50000`, lỗi
  cổng/config, worker lỗi/đóng/khởi động lại và mô phỏng 30 xe nhận broadcast
  nhưng chỉ UUID được chọn chạy.

Unit test không mở socket mạng thật, không chạm GPIO/motor, không cần BE.
Ca 30 xe là mô phỏng bộ lọc UUID, không phải đo tải Wi-Fi lớp học. Ca bind mọi
IP kiểm tra cấu hình receiver, không thay địa chỉ DHCP thật của Pi. Log WARNING
trong các ca gửi sai IP là kết quả được kiểm tra, không phải test thất bại.

### Tích hợp UDP loopback tùy chọn

```powershell
$env:RUN_WIFI_UDP_INTEGRATION='1'
python -B -m unittest vehicle_testing.tests.test_wifi_udp -v
```

Chạy từ thư mục cha của `vehicle_testing`. Kiểm thử socket dùng UDP loopback
và dry-run, không thay thế việc kiểm tra GPIO/motor/FE/BE thực tế trên Pi.
