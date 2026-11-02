# Wi-Fi qua WebSocket `/stem`

Receiver mới: `connections/wifi/websocket_receiver.py`.
Lệnh chạy: `wifi_websocket_receiver.py`. Luồng này thay đường UDP trong lần thử
FE hiện tại; adapter UDP cũ được giữ để đối chiếu, không được mở bởi listener này.

## Vị trí các thành phần

```text
FE trên laptop ---- WebSocket ----> server 192.168.1.93:5000/stem
                                       |
                                       | chuyển tiếp tin nhắn FE
                                       v
Pi chạy wifi_websocket_receiver.py (cũng là WebSocket client)
```

`ws.send(payload)` của FE gửi tới server. Server phải relay/broadcast tới kết
nối Pi; hai client cùng URL chưa tự chuyển tin cho nhau. Bản listener không sửa
server/FE và không tự đặt gói đăng ký robot khi chưa có hợp đồng phía server.
Đây là WebSocket thường; chưa có bằng chứng endpoint dùng Socket.IO hay STOMP.

## Chạy thử trên Pi

```bash
cd ~/vehicle_testing
source .venv/bin/activate
python -m pip install -r requirements-wifi.txt
python wifi_websocket_receiver.py --device-id robot-003 --dry-run
```

Đổi địa chỉ nếu cần:

```bash
python wifi_websocket_receiver.py --device-id robot-003 --url ws://192.168.1.93:5000/stem
```

Listener tự kết nối lại sau 2 giây khi socket đóng/lỗi; không gửi lại lệnh.
`--once` chỉ thử một lần. Ctrl+C đóng socket và dọn worker đang chạy.
Mất kết nối yêu cầu dừng và xóa bản chờ; cần upload lại sau khi nối lại.

Các chế độ giống receiver khác:

- Không có cờ: chỉ parse/preview, EXEC không mở phần cứng.
- `--dry-run`: EXEC chạy qua runner mô phỏng, không mở GPIO/I²C.
- `--run`: EXEC điều khiển motor/LED thật theo tập lệnh runner hiện hỗ trợ.

Sau khi kiểm tra mô phỏng và dừng receiver khác, chạy thật:

```bash
python wifi_websocket_receiver.py --device-id robot-003 --run
```

## Hợp đồng đã có từ FE

FE gửi JSON text, ví dụ JavaScript:

```javascript
const payload = JSON.stringify({
  type: "UPLOAD",
  uuid: "robot-003",
  code: 'report_block("block-1")\nrobot.sendCmd("move_forward:5")\n'
});
ws.send(payload); // sau khi socket đã mở
```

Một WebSocket message chứa một JSON object, không cần thêm dấu xuống dòng ngoài
JSON như giao thức USB. `code` giữ nguyên chuỗi Scratch, không bị eval/exec.
Listener lọc UUID khớp hoàn toàn, parse bằng `runtime/parser.py`, rồi in preview.
Upload không tự chạy. Upload sai code xóa preview cũ của cùng xe.

Payload khi bấm Chạy đã được xác nhận từ ảnh console FE:

```json
{"type":"EXEC","uuid":"robot-003","code":""}
```

Chỉ `EXEC` đúng UUID, `code` rỗng và có upload hợp lệ mới chuyển sang runner.
Mỗi upload cho phép một EXEC; chạy lại cần upload lại. Upload mới trong khi đang
chạy bị từ chối; worker dùng snapshot của lần upload đã nhận. Parser chỉ hỗ trợ
tiến/lùi, quay trái/phải và LED ma trận hiện có, không thực thi Python tùy ý.

Giới hạn JSON text 512 KiB; parser giữ giới hạn source 64 KiB/1000 sự kiện.
Log raw tối đa 4096 ký tự đầu mỗi message; ký tự điều khiển được escape.
Raw log có thể gồm tin của xe khác nếu server broadcast; chỉ preview đúng UUID.

## Xác minh FE có gửi tới Pi

1. Chờ `WS CONNECTED` trên Pi.
2. Bấm Upload trên FE. Pi phải in `WS RX` và `WS UPLOAD UUID=robot-003`.
3. Bấm Chạy trên FE. Pi phải in `WS RX` có `type:"EXEC"`, rồi `WS EXEC`.
4. Với `--dry-run`/`--run`, log có các sự kiện `executing`, block và `done`/`stopped`/`error`.

`Da gui payload JSON (44 byte)`/`Code executed successfully` ở FE mới xác nhận
thao tác gửi phía FE. Số byte không xác định được các field hay type của gói.
Phải thấy message ở Pi mới xác nhận được server đã relay xuống Pi.

Nếu chỉ có CONNECTED mà không có RX, kiểm tra server có forward tin FE cho các
client khác, có cần đăng ký UUID/role hoặc room trước khi nhận không. Chưa có
source server `/stem` trong checkout đang kiểm tra nên chưa xác minh các bước này.

Nếu có WS RX nhưng không có preview, kiểm tra `uuid`, `type` chính xác là
`UPLOAD` và `code` có thuộc tập lệnh parser hỗ trợ không.

## Phần chưa có hợp đồng phía server/FE

- JSON khi bấm Dừng; hiện type khác UPLOAD/EXEC chỉ được ghi log.
- Hợp đồng đăng ký/định tuyến UUID nếu server yêu cầu.
- Hợp đồng ACK/trạng thái/block gửi ngược lại FE.

Không suy đoán các type khác từ tên log hoặc độ dài payload. Trạng thái/block
chỉ ghi log tại Pi, chưa gửi ACK tự đặt tới server. Các phương thức
MQTT/USB/Bluetooth và HTTP cũ giữ nguyên. Server thật và phần cứng cần được thử
tại mạng của người dùng; kiểm thử mô phỏng không chứng minh server đã relay.

Thư viện: [websocket-client WebSocketApp](https://websocket-client.readthedocs.io/en/latest/app.html).
