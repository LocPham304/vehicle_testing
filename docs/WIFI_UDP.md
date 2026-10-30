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
python3 wifi_udp_receiver.py --device-id robot-003 --sender-ip 192.168.1.93 --dry-run
```

Trên giao diện chọn phương thức Wi-Fi, nhấn **Upload Code**, rồi **Chạy Code**.
Không cần mở client Python trên laptop. Log upload hợp lệ phải có
`status: uploaded`; EXEC có `status: accepted`; worker in `executing`, các block
và `done`. Với `--dry-run` chỉ mô phỏng, xe không di chuyển.

Chạy motor/LED thật: Ctrl+C receiver mô phỏng, rồi mở lại:

```bash
python3 wifi_udp_receiver.py --device-id robot-003 --sender-ip 192.168.1.93 --run
```

Upload lại từ web, rồi Chạy Code. Mặc định không có cờ là preview, EXEC chỉ in
kịch bản. `--sender-ip` tùy chọn, lọc theo IPv4 nguồn BE (không lọc cổng nguồn).
Khi BE đổi IP, cập nhật cờ này. Lọc IP không phải xác thực người dùng.

Upload chỉ kiểm tra/lưu RAM, không tự chạy. Mỗi upload hợp lệ cho phép EXEC
**một lần**; muốn chạy tiếp cần Upload Code lại. EXEC trước upload hoặc lặp lại
bị từ chối. Upload không hợp lệ làm mất bản chờ cũ. Khi đang chạy, upload mới
bị từ chối; không thay kịch bản giữa chừng. Ctrl+C hủy worker, dừng motor theo
cơ chế runner hiện có và đóng socket. Khởi động lại receiver phải upload lại.

## Giới hạn của giao thức hiện tại

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

```powershell
$env:RUN_WIFI_UDP_INTEGRATION='1'
python -B -m unittest vehicle_testing.tests.test_wifi_udp -v
```

Chạy từ thư mục cha của `vehicle_testing`. Kiểm thử socket dùng UDP loopback
và dry-run, không thay thế việc kiểm tra GPIO/motor/FE/BE thực tế trên Pi.
