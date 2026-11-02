# Pi WebSocket server cho Windows Local Helper tìm xe

Triển khai: `connections/wifi/websocket_receiver.py`.
Lệnh chạy: `wifi_websocket_receiver.py`.

```text
Pi khởi động -> mở server 0.0.0.0:50000
Người dùng bấm Tìm Robot -> FE yêu cầu Windows Local Helper discovery
Helper dò IP trong subnet LAN có mở TCP 50000 (chưa biết UUID)
Helper mở WebSocket ws://<IP_PI>:50000/stem -> gửi action=identify
Pi trả action=identify_response, uuid, deviceName
Helper ghép UUID + IP + tên -> trả danh sách về FE
```

Pi là server, Windows Local Helper là client cho bước discovery. Không có bước
Pi kết nối tới IP máy FE hay server trung gian relay. TCP 50000 là cổng WebSocket,
khác giao thức UDP cũ dù cùng số cổng. Helper và UI FE nằm ngoài phần mềm Pi này.
Phiên bản client cũ (`--url`, `--once`, `--reconnect-seconds`)
đã được thay bằng server; các cờ đó không còn dùng.

## Test kết nối trước

Cập nhật source và dependency mới `websockets` trong venv Pi:

```bash
cd ~/vehicle_testing
source .venv/bin/activate
python -m pip install -r requirements-wifi.txt
python wifi_websocket_receiver.py --device-id robot-003 --name "Robot Gamma"
```

Không có `--run`: đây là chế độ preview, không mở GPIO/I²C hoặc làm xe chạy.
Log khởi động phải có `WS SERVER LISTENING: 0.0.0.0:50000/stem`.
Xem IP LAN thực tế của Pi trong terminal khác:

```bash
hostname -I
```

Ví dụ Pi có IP `192.168.1.40`, Helper kết nối `ws://192.168.1.40:50000/stem`.
`0.0.0.0` là địa chỉ bind trên Pi, không phải địa chỉ đích trên FE. Không dùng IP
máy chạy FE nếu máy đó không phải Pi. FE gọi Helper quét LAN rồi hiển thị danh
sách nhận lại; mở server trên Pi không tự cài hoặc sửa Helper trên Windows.

Có thể test trong Console trình duyệt FE, thay IP bằng IP Pi:

```javascript
const probe = new WebSocket("ws://192.168.1.40:50000/stem");
probe.onmessage = event => console.log("Pi:", JSON.parse(event.data));
probe.onerror = event => console.error("Pi connection error:", event);
probe.onopen = () => probe.send(JSON.stringify({action: "identify"}));
// Sau khi quan sát kết quả: probe.close();
```

Pi cho phép WebSocket trên `/stem` và `/` (phục vụ discovery), gồm cả query
string. Đường dẫn khác trả HTTP 404 trong handshake. Server dùng IPv4, cùng
LAN có đường truyền tới Pi và cổng TCP 50000 phải truy cập được. Nếu không kết
nối được, kiểm tra IP Pi, firewall/cô lập client Wi-Fi và cổng đang bị chiếm.

## Identify

Yêu cầu đã chốt từ Helper:

```json
{"action":"identify"}
```

Identify không cần biết UUID trước. Các cách gửi text `identify` hoặc JSON
`{"type":"identify"}`/`{"type":"IDENTIFY"}` vẫn được nhận để tương thích bản thử.
Tất cả đều trả đúng schema đã chốt:

```json
{"action":"identify_response","uuid":"robot-003","deviceName":"Robot Gamma"}
```

Tên tùy chỉnh bằng `--name`; mặc định `Robot <UUID>`. UUID lấy từ `--device-id`,
ổn định giữa các lần chạy nếu giữ nguyên cờ. Nhiều kết nối dò xe có thể nhận
identity cùng lúc; chúng không giành quyền điều khiển hoặc xóa kịch bản khi đóng.
Helper lấy IP từ kết nối đang hỏi, không suy ra IP từ UUID; cùng UUID có thể đổi
IP sau khi DHCP cấp lại. Helper tổng hợp mỗi kết quả thành hàng UUID/IP/tên.
Đã có kiểm thử TCP probe rồi WebSocket identify qua loopback; discovery qua LAN
và UI FE thực tế cần kiểm tra tại mạng người dùng.

## Giữ luồng UPLOAD/EXEC đã xác nhận

FE gửi một JSON object trong mỗi WebSocket message:

```javascript
ws.send(JSON.stringify({
  type: "UPLOAD", uuid: "robot-003",
  code: 'report_block("block-1")\nrobot.sendCmd("move_forward:5")\n'
}));
ws.send(JSON.stringify({type: "EXEC", uuid: "robot-003", code: ""}));
```

UPLOAD và EXEC phải cùng kết nối, đúng UUID. Upload chỉ kiểm tra/lưu chờ, không
tự chạy; mỗi Upload hợp lệ cho phép một EXEC. Parser không eval/exec Python tùy
ý, hiện hỗ trợ tiến/lùi, quay và LED. Chưa có bộ đọc XML Blockly trực tiếp.

Server trả kết quả JSON trên kết nối đã gửi, ví dụ:

```json
{"ok":true,"status":"uploaded","commands":1,"markers":1}
```

EXEC trả `status:"preview"` ở chế độ mặc định, hoặc `status:"accepted"` khi đã
bật runner. `accepted` chưa có nghĩa xe đã chạy xong. Các block/trạng thái hoàn
tất hiện ghi ở Pi; chưa thống nhất protocol sự kiện hoàn tất/Dừng với FE.

Một kết nối Upload giữ quyền điều khiển tới khi nó ngắt; kết nối khác vẫn có
thể Identify nhưng không thay code/chạy xe. Ngắt kết nối điều khiển xóa bản chờ
và hủy worker. Kết nối mới cần Upload lại. Ctrl+C dừng server và dọn worker.

## Mô phỏng và chạy thật sau khi test kết nối

```bash
python wifi_websocket_receiver.py --device-id robot-003 --name "Robot Gamma" --dry-run
```

`--dry-run` đi qua runner mô phỏng khi nhận EXEC, không mở phần cứng. Chỉ khi
muốn điều khiển motor/LED thật mới dùng `--run`, dừng các receiver khác trước.
Tùy chỉnh bind bằng `--host`, `--port`; mặc định `0.0.0.0`, `50000`.

Giới hạn WebSocket message 512 KiB, source 64 KiB/1000 sự kiện theo parser.
Các adapter MQTT/USB/Bluetooth/HTTP/UDP không bị thay đổi bởi server này.

Thư viện: [websockets 15 server](https://websockets.readthedocs.io/en/15.0.1/reference/sync/server.html).
