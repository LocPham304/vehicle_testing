# Điều khiển qua Wi-Fi bằng HTTP trực tiếp

Code triển khai: `connections/wifi/receiver.py` và `connections/wifi/client.py`.
Các file `wifi_receiver.py` và `wifi_client.py` ở ngoài cùng vẫn dùng để chạy
các lệnh trong hướng dẫn này.

Chế độ này đặt trong `vehicle_testing`. Laptop gửi HTTP thẳng đến Pi ở cổng
`8765`, không đi qua MQTT broker. Pi vẫn dùng parser và runner hiện có để chạy
motor/LED. Không cần cài thêm thư viện Python cho HTTP.

```text
Laptop: wifi_client.py → Wi-Fi/router → Pi: wifi_receiver.py
                                       → parser → session → runner → motor/LED
```

Laptop và Pi cần có đường mạng đến nhau; cách thử hiện tại là cùng mạng Wi-Fi.
Không cần Internet. Nếu Pi đã tắt Wi-Fi trong lần thử trước, cần bật lại bằng
console còn truy cập được trước khi SSH. Chưa cấu hình Pi phát hotspot.

## 1. Mở receiver trên Pi

Dừng receiver USB/MQTT đang điều khiển phần cứng bằng Ctrl+C trước khi chuyển
chế độ. Mỗi tiến trình có phiên điều khiển riêng, chưa có khóa GPIO liên tiến
trình; chỉ chạy **một receiver điều khiển phần cứng** tại một thời điểm.

Trong terminal của Pi:

```sh
cd ~/vehicle_testing
source .venv/bin/activate
python3 wifi_receiver.py --dry-run
```

Giữ terminal này mở. Đây là runner mô phỏng, không phát tín hiệu motor/GPIO.
Nếu chỉ chạy `python3 wifi_receiver.py`, receiver ở chế độ `preview`: nhận và
kiểm tra code, RUN chỉ in lại kịch bản, không thực hiện runner.

Dùng terminal khác trên Pi để xem IP nếu cần:

```sh
hostname -I
```

Ví dụ Pi có IP `192.168.1.40`. IP có thể thay đổi khi kết nối lại mạng.
Mặc định receiver nghe trên `0.0.0.0:8765`; `0.0.0.0` là địa chỉ lắng nghe,
không phải địa chỉ nhập trên laptop.

## 2. Mở client trên laptop Windows

Trong PowerShell, tại thư mục `vehicle_testing` trên laptop:

```powershell
python wifi_client.py --host 192.168.1.40
```

Thay IP bằng IP hiện tại của Pi. Có thể chỉ chạy `python wifi_client.py`, rồi
nhập IP khi được hỏi. Không cần cáp USB hoặc chọn COM.

Sau khi kết nối, nhập từng lệnh và Enter:

```text
wifi> upload
wifi> status
wifi> run
wifi> stop
wifi> exit
```

| Lệnh | Kết quả |
| --- | --- |
| `upload` | Gửi `examples/scratch_sample.txt` trên laptop, kiểm tra và lưu vào RAM của Pi; **không tự chạy** |
| `upload "C:\duong dan\script.txt"` | Gửi file khác trên laptop; tối đa 64 KiB UTF-8 |
| `run` | Chạy đúng bản đã upload gần nhất hợp lệ |
| `stop` | Yêu cầu hủy lần chạy hiện tại; vẫn giữ bản chờ để có thể RUN lại |
| `status` | Xem `idle`/`executing`, `uploaded`, và chế độ `preview`/`dry-run`/`hardware` |
| `exit` | Yêu cầu dừng, xóa bản chờ và nhường phiên điều khiển |

Chạy xong có sự kiện `status: done`; các marker `report_block` trả về dưới dạng
`event: block, block_id: ...`. `accepted` chỉ xác nhận đã nhận RUN, chưa có nghĩa
là đã chạy xong. Trong mô phỏng, chuyển động không chờ đủ số giây thực tế.

Client tự ping khoảng mỗi giây và lấy sự kiện theo cursor, không cần nhập tay.
Giữ client mở trong lúc chạy. Chỉ một client giữ quyền điều khiển receiver tại
một thời điểm; client thứ hai nhận lỗi `409`.

## 3. Chạy phần cứng thật

Sau khi thử mô phỏng ổn, thoát client và Ctrl+C receiver trên Pi, rồi đổi thành:

```sh
python3 wifi_receiver.py --run
```

Mở lại client trên laptop, `upload` rồi `run`. Lần đầu nên thử kịch bản ngắn
khi kê bánh. Tiến/lùi tính bằng **giây**, quay tính bằng góc ước lượng theo
`config.py`; LED dùng cùng font và quy tắc bỏ dấu như runner hiện tại.

## 4. Mất kết nối và kết nối lại

Sau khoảng **5 giây không có yêu cầu điều khiển hợp lệ/ping**, watchdog độc lập
trên Pi yêu cầu hủy runner, xóa kịch bản chờ và vô hiệu token. Đọc `GET /status`
hoặc `/events` không gia hạn phiên. Khi `exit`, client gửi yêu cầu ngắt ngay;
nếu mạng đã mất thì Pi xử lý theo timeout.

Sau khi nối lại mạng, thoát client cũ và mở lại, rồi **upload lại** trước RUN.
Không tự chạy lại và không tự gửi lại RUN khi một lần gửi bị timeout.
Request trùng ID và cùng nội dung được trả lại ACK cũ trong bộ nhớ 64 request
gần nhất của phiên; dùng ID mới cho một lần RUN mới chủ động.

Lệnh dừng là yêu cầu phần mềm; không xác nhận bánh đã đứng yên khi I²C/phần
cứng gặp lỗi. Receiver chạy trong terminal, chưa cài dịch vụ tự khởi động.

## 5. Thử tính độc lập với MQTT

Giữ Wi-Fi laptop/Pi bật. Nếu Mosquitto đang chạy trên Pi, có thể tạm dừng broker:

```sh
sudo systemctl stop mosquitto
```

Vẫn dùng `wifi_client.py` để `upload` và `run`: luồng HTTP hoạt động độc lập với
broker. Sau đó nếu cần thử MQTT lại, bật broker:

```sh
sudo systemctl start mosquitto
```

Tắt Wi-Fi của Pi khi không có đường mạng thay thế sẽ ngắt cả HTTP lẫn MQTT
từ laptop. Hai chế độ khác giao thức ứng dụng; cùng dùng mạng IP hiện có.

## 6. API dành cho FE/BE sau này

Base URL ví dụ `http://192.168.1.40:8765`. Body POST dùng
`Content-Type: application/json`. Các lệnh điều khiển cần header
`X-Session-Token: TOKEN` nhận từ `/connect`.

| Method | Endpoint | Body hoặc ý nghĩa |
| --- | --- | --- |
| POST | `/connect` | `{"client_id":"laptop-01"}` → `token`, `cursor`, `mode`, `link_timeout` |
| POST | `/upload` | `{"id":"upload-01","code":"robot.sendCmd(\"move_forward:2\")"}` |
| POST | `/run` | `{"id":"run-01"}` → `accepted` hoặc `preview` |
| POST | `/stop` | `{"id":"stop-01"}` |
| POST | `/ping` | `{"id":"ping-01"}`; gọi khoảng mỗi giây để duy trì phiên |
| GET | `/status` | Công khai trạng thái hiện tại, không trả token |
| GET | `/events?after=0` | Token bắt buộc; trả `events`, `cursor`, `truncated` |
| POST | `/disconnect` | `{}`; dừng/xóa bản chờ và giải phóng phiên |

Dùng `cursor` từ connect cho lần lấy events đầu tiên, rồi dùng `cursor` của
phản hồi trước cho lần kế tiếp. Ví dụ một sự kiện:

```json
{"event":"block","block_id":"scratch-block-id","sequence":12}
```

Events giữ tối đa 256 mục và 256 KiB; `truncated: true` báo đã bỏ bớt events cũ.
Kết quả hoàn tất cũng là event, không lưu lâu dài. Không xem buffer này là nhật
ký đầy đủ. Mỗi body HTTP tối đa 512 KiB; code sau giải mã tối đa 64 KiB.
Kịch bản được parse thành lệnh cho runner, không thực thi Python tùy ý.

HTTP `400` báo yêu cầu/code không hợp lệ hoặc chưa thể RUN; `403` token thiếu/
hết hạn; `409` đã có controller; `413` body quá lớn; `415` sai Content-Type.
Upload mới không hợp lệ sẽ xóa bản chờ cũ để tránh chạy nhầm. Upload trong lúc
đang chạy chỉ thay bản chờ; lần chạy hiện tại dùng snapshot đã nhận lúc RUN.

Đây là HTTP thử nghiệm trong LAN tin cậy, chưa có TLS/xác thực tài khoản.
Token dùng để quản lý phiên điều khiển, không thay thế đăng nhập. Chưa mở CORS
cho web khác origin. Khi tích hợp FE, cần cấu hình origin cụ thể/proxy và quyền
truy cập mạng; có thể để BE gọi HTTP rồi chuyển trạng thái về FE. Bên giữ token
cũng phải duy trì ping. FE/BE hiện tại chưa được sửa trong bước này.

Nếu không kết nối được: kiểm tra đúng IP, receiver còn mở, cùng mạng, cổng
8765 được phép và router không bật cô lập thiết bị. Từ Windows:

```powershell
Test-NetConnection 192.168.1.40 -Port 8765
```

## Kiểm thử phần mềm

Từ thư mục cha của `vehicle_testing`:

```powershell
python -B -m unittest vehicle_testing.tests.test_wifi vehicle_testing.tests.test_wifi_client -v
```

Ba bài kiểm tra HTTP loopback cần bật riêng (không mở GPIO):

```powershell
$env:RUN_WIFI_HTTP_INTEGRATION='1'
python -B -m unittest vehicle_testing.tests.test_wifi vehicle_testing.tests.test_wifi_client -v
Remove-Item Env:RUN_WIFI_HTTP_INTEGRATION
```

Trên Linux có thể dùng `RUN_WIFI_HTTP_INTEGRATION=1 python3 -B -m unittest
vehicle_testing.tests.test_wifi vehicle_testing.tests.test_wifi_client -v` trên
một dòng. Kiểm thử loopback không thay thế thử Wi-Fi/phần cứng trên xe.
