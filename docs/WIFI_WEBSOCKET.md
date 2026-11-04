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
# Chỉ thiết lập một lần trên mỗi Pi:
python wifi_websocket_receiver.py --setup
# Những lần sau chỉ cần:
python wifi_websocket_receiver.py --dry-run
```

`--setup` hỏi UUID và tên robot đã đăng ký trên FE, ví dụ `robot-003` và
`🚗 Robot Gamma`, rồi lưu và thoát. Không mở server/GPIO trong bước thiết lập.
Mỗi xe có một Pi riêng nên phải gán UUID riêng đúng với bản ghi trên FE.

Cấu hình lưu tại `device_identity.json` ở thư mục gốc `vehicle_testing`, không
phụ thuộc thư mục hiện tại khi chạy script. Ví dụ nội dung:

```json
{"uuid":"robot-003","name":"🚗 Robot Gamma"}
```

File riêng của từng Pi đã được Git bỏ qua; không sao chép cùng một cấu hình
định danh cho tất cả xe. Có thể tham khảo `device_identity.example.json`.
Muốn đổi xe được gán, dừng receiver rồi chạy lại `--setup` để ghi cấu hình mới.
`--identity-file /duong/dan/xe.json` chọn file riêng; dùng cùng cờ này khi setup
và khi khởi động receiver. Thiếu/hỏng cấu hình sẽ báo lỗi trước khi mở server.

Không tự lấy UUID từ gói FE hoặc phần tử đầu tiên của `/api/devices`. API đó
trả danh sách, cần xác thực; luồng hiện tại chưa có ánh xạ phần cứng Pi → UUID robot;
receiver đọc cấu hình đã lưu nên không cần truy cập API mỗi lần khởi động.

`--dry-run` mô phỏng thực thi sau khi nhận EXEC, không mở GPIO/I²C.
Chạy `python wifi_websocket_receiver.py` không kèm cờ là chế độ preview.
Log khởi động phải có `WS SERVER LISTENING: 0.0.0.0:50000/stem`.
Log `WS IDENTITY` ghi UUID/tên và đường dẫn cấu hình đang sử dụng.
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

Nếu Identify có trường `uuid`, chỉ Pi có UUID khớp mới trả lời; UUID khác sẽ
bị bỏ qua và ghi `WS IGNORE UUID`. Identify không có UUID vẫn được mọi Pi trả
lời để Helper khám phá danh sách xe.

UUID/tên được đọc từ cấu hình riêng của Pi. Các cờ `--device-id`, `--name` cũ
vẫn dùng được để ghi đè cho một lần chạy, không tự ghi lại file. Khi truyền
`--device-id` mà không truyền tên, tên là `Robot <UUID>`, không lấy tên của xe
khác trong cấu hình. Nhiều kết nối dò xe có thể nhận identity cùng lúc; chúng
không giành quyền điều khiển hoặc xóa kịch bản khi đóng.
Helper lấy IP từ kết nối đang hỏi, không suy ra IP từ UUID; cùng UUID có thể đổi
IP sau khi DHCP cấp lại. Helper tổng hợp mỗi kết quả thành hàng UUID/IP/tên.
Đã có kiểm thử TCP probe rồi WebSocket identify qua loopback; discovery qua LAN
và UI FE thực tế cần kiểm tra tại mạng người dùng.

## Upload và EXEC từ FE

### Chạy trực tiếp, không cần bấm Upload

Nút Chạy Code có thể gửi luôn code hiện tại trong `payload` của `action:"exec"`:

```javascript
ws.send(JSON.stringify({
  action: "exec", uuid: "robot-003",
  payload: 'report_block("block-1")\nrobot.sendCmd("move_forward:5")\n'
}));
```

Pi kiểm tra toàn bộ code bằng parser/validator hiện có, lưu chương trình và
thực thi trong cùng yêu cầu. Không dùng `eval`/`exec` để chạy Python tùy ý.
`--dry-run` mô phỏng, `--run` chạy phần cứng, mặc định chỉ preview.
Code mới sai thì không chạy lại chương trình cũ; đang thực thi thì từ chối
chương trình mới. Vẫn kiểm tra đúng UUID và chỉ cho phép một worker chạy tại một thời điểm.

FE phải gửi code thật, không gửi `payload:""` nếu chưa Upload. Chuỗi rỗng vẫn
có nghĩa chạy bản đã Upload; Pi không tự đọc được các block đang nằm trên FE.
Kết nối mới có thể gửi EXEC kèm code ngay từ message đầu tiên. FE có thể đóng
socket sau yêu cầu; worker tại Pi tiếp tục chạy độc lập tới khi xong, lỗi, nhận STOP
hoặc server bị dừng. Mất kết nối mạng không còn tự dừng xe.

### Luồng hai bước Upload rồi EXEC

FE hiện gửi một JSON object trong mỗi WebSocket message, dùng `action` và
`payload` (code Python ở dạng chuỗi):

```javascript
ws.send(JSON.stringify({
  action: "upload", uuid: "robot-003",
  payload: 'report_block("block-1")\nrobot.sendCmd("move_forward:5")\n'
}));
// Chỉ gửi EXEC sau khi Pi xác nhận upload thành công.
// Có thể dùng ws này hoặc đóng nó rồi mở một WebSocket mới để gửi EXEC.
ws.send(JSON.stringify({action: "exec", uuid: "robot-003", payload: ""}));
```

Receiver vẫn nhận dạng `type`/`code` cũ để tương thích:

```javascript
ws.send(JSON.stringify({
  type: "UPLOAD", uuid: "robot-003",
  code: 'report_block("block-1")\nrobot.sendCmd("move_forward:5")\n'
}));
ws.send(JSON.stringify({type: "EXEC", uuid: "robot-003", code: ""}));
```

Với luồng hai bước, UPLOAD và EXEC có thể khác kết nối nhưng phải đúng UUID. Upload chỉ kiểm tra/lưu chờ, không
tự chạy; mỗi Upload hợp lệ cho phép một EXEC. Parser không eval/exec Python tùy
ý, hiện hỗ trợ tiến/lùi, quay và LED. Chưa có bộ đọc XML Blockly trực tiếp.

Receiver chuyển `action:"exec"` hoặc `type:"EXEC"` thành lệnh nội bộ `action:"exec"` gửi tới
`RobotSession`. Session vẫn nhận tên `run` cũ để tương thích các transport khác.

Server trả kết quả JSON trên kết nối đã gửi, ví dụ:

```json
{"ok":true,"status":"uploaded","commands":1,"markers":1}
```

FE nên chờ phản hồi `ok:true, status:"uploaded"` trước khi báo Upload thành công;
`WebSocket.send()` chỉ xác nhận phía client đã gửi/xếp dữ liệu để gửi, không
chứng minh Pi đã kiểm tra và lưu chương trình.

EXEC trả `status:"preview"` ở chế độ mặc định, hoặc `status:"accepted"` khi đã
bật runner. `accepted` chưa có nghĩa xe đã chạy xong. Các block/trạng thái hoàn
tất hiện ghi ở Pi, chưa tự đẩy về FE. Đã hỗ trợ yêu cầu STOP/STATUS như bên dưới.

### Vòng đời chương trình và STOP

Mỗi kết nối chỉ mang yêu cầu/phản hồi; chương trình thuộc tiến trình Pi, không
thuộc một socket. Đóng socket, lỗi gửi ACK hoặc một kết nối Identify mới không
xóa bản chờ và không hủy worker. Cách này tương thích với FE mở–gửi–đóng mỗi lần.
Code chỉ lưu trong RAM, không ghi file và mất khi restart script/Pi.

Không còn quyền điều khiển gắn với một kết nối: khi rảnh, Upload hợp lệ mới nhất
đúng UUID thay bản chờ trước đó. Upload hoặc EXEC kèm code mới không hợp lệ sẽ
xóa bản chờ cũ để tránh chạy nhầm. Khi worker đang chạy, Upload/EXEC mới bị từ chối,
không xếp hàng hoặc làm gián đoạn chương trình hiện tại. Mỗi Upload cho phép một
EXEC; chạy lại cần Upload mới hoặc EXEC kèm code.

Có thể gửi từ một WebSocket mới, vẫn phải đúng UUID:

```json
{"action":"stop","uuid":"robot-003"}
{"action":"status","uuid":"robot-003"}
```

STOP yêu cầu worker dừng, xóa bản chờ và trả `status:"stopping"` nếu worker còn chạy,
hoặc `status:"idle"` nếu đang rảnh. STOP là yêu cầu hủy hợp tác; log `stopped` xuất hiện
khi worker đã xử lý yêu cầu, không coi ACK `stopping` là đã dừng xong.
STATUS trả `status:"executing"`/`"idle"`, `uploaded` (còn bản chờ EXEC hay không),
và `mode:"preview"`/`"dry-run"`/`"hardware"`. Dạng cũ `type:"STOP"`/`type:"STATUS"`
cũng được nhận. Identify vẫn không cần UUID; các lệnh điều khiển luôn phải khớp UUID.
Ctrl+C dừng server, yêu cầu hủy worker và chờ dọn tài nguyên.

`WS RX RAW` chỉ in 200 ký tự đầu và có nhãn `log rut gon` nếu message dài hơn;
đây là giới hạn hiển thị log, không cắt dữ liệu đưa vào parser. Upload thành
công sẽ log đầy đủ danh sách block/lệnh, tổng số block marker, số lệnh và số
byte code. Block Bắt đầu có thể chỉ tạo marker nên 7 marker có thể tương ứng
6 lệnh điều khiển, không phải mất một block.

## Mô phỏng và chạy thật sau khi test kết nối

```bash
python wifi_websocket_receiver.py --dry-run
```

`--dry-run` đi qua runner mô phỏng khi nhận EXEC, không mở phần cứng. Chỉ khi
muốn điều khiển motor/LED thật mới dùng `--run`, dừng các receiver khác trước.
Tùy chỉnh bind bằng `--host`, `--port`; mặc định `0.0.0.0`, `50000`.

Giới hạn WebSocket message 512 KiB, source 64 KiB/1000 sự kiện theo parser.
Các adapter MQTT/USB/Bluetooth/HTTP/UDP không bị thay đổi bởi server này.

Thư viện: [websockets 15 server](https://websockets.readthedocs.io/en/15.0.1/reference/sync/server.html).
