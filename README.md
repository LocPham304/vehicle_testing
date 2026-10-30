# Điều khiển robot Mecanum và tay nâng/hạ

Chương trình Python dựa trên `pi4-source/test-banh-xe.py`, dùng thư viện
Adafruit để điều khiển PCA9685. Nhập lệnh ở terminal để chạy cả bốn bánh
tiến/lùi hoặc trượt ngang theo thời gian, cùng lệnh quay tại chỗ theo góc ước lượng:
soạn các dòng lệnh trước, gõ `chay` để thực hiện kịch bản,
rồi gửi lệnh dừng sau từng chuyển động. Không đo quãng đường hoặc tốc độ thực tế.
Tay nâng/hạ dùng GPIO BCM 18 (hạ −10°, nâng 80°), càng dùng GPIO BCM 12 (mở 100°, đóng 0°).

## Cấu trúc

Xem [bảng lệnh chạy qua cả bốn phương thức](docs/RUN_COMMANDS.md) để mở receiver
trên Pi và gửi kịch bản từ laptop hoặc FE/BE.

Code triển khai được gom theo chức năng. Các file chạy quen thuộc ở ngoài cùng
chỉ gọi module tương ứng, nên những lệnh đang dùng trên Pi/laptop vẫn giữ nguyên.

```text
vehicle_testing/
├── config.py                    # Chỉnh GPIO, PWM, góc và hệ số bánh xe tại đây
├── hardware/                    # Điều khiển phần cứng
│   ├── motors.py                # PCA9685 và chuyển động Mecanum
│   ├── servos.py                # Tay nâng/hạ và càng
│   ├── pwm.py                   # Nhận diện driver PWM từ device tree
│   ├── ultrasonic.py            # Cảm biến khoảng cách
│   └── displays/
│       ├── link.py              # Giao thức CLK/DATA
│       ├── matrix.py            # Font, chạy chữ và CLI thử LED ma trận
│       └── seven_segment.py     # LED 4 số, nhập tay và khoảng cách tự động
├── runtime/                     # Xử lý và thực hiện kịch bản
│   ├── parser.py                # Parse robot.sendCmd/report_block thành dữ liệu
│   ├── runner.py                # Thực hiện lệnh bằng motor/LED, có dry-run
│   ├── session.py               # Bản chờ, worker và hủy chạy dùng chung USB/Wi-Fi
│   ├── console.py               # Console upload/run/stop/status dùng chung
│   └── paths.py                 # Vị trí file mẫu, độc lập thư mục đang đứng
├── connections/                 # Các cách gửi/nhận kịch bản
│   ├── mqtt/
│   │   └── receiver.py          # Qua broker MQTT
│   ├── usb/
│   │   ├── receiver.py          # Chạy trên Pi
│   │   ├── client.py            # Chạy trên laptop
│   │   └── protocol.py          # JSON, giới hạn khung và chống lặp request
│   ├── wifi/
│   │   ├── receiver.py          # HTTP trực tiếp trên Pi
│   │   ├── client.py            # HTTP client trên laptop
│   │   └── udp_receiver.py      # Broadcast UUID + LF + code/EXEC từ BE
│   └── bluetooth/
│       ├── receiver.py          # Phiên Bluetooth Classic SPP trên Pi
│       ├── bluez.py             # Đăng ký dịch vụ và nhận socket từ BlueZ
│       └── client.py            # COM Outgoing Bluetooth trên Windows
├── cli/
│   ├── robot.py                 # Điều khiển terminal: tien/lui/chay/...
│   └── check_pwm.py             # Kiểm tra cấu hình PWM, chỉ đọc
├── examples/                    # Kịch bản mẫu
├── tests/                       # Kiểm thử chức năng hiện có và các lệnh chạy cũ
│   └── legacy/                  # Giữ test cho công cụ dò servo đã bỏ
├── docs/                        # Hướng dẫn USB, Wi-Fi, PWM và ghi chú thiết kế
├── requirements*.txt            # Dependency chung, USB và MQTT
└── *.py                         # Các file gọi lệnh cũ, xem bảng bên dưới
```

Muốn sửa logic, mở file triển khai trong thư mục chức năng. `config.py` giữ
nguyên vị trí và cấu hình hiện tại. `examples/scratch_sample.txt` cũng giữ nguyên.

| File gọi ở ngoài cùng | Module triển khai |
| --- | --- |
| `main.py` | `cli/robot.py` |
| `scratch_runner.py` | `runtime/runner.py` |
| `scratch_receiver.py` | `connections/mqtt/receiver.py` |
| `usb_receiver.py`, `usb_client.py` | `connections/usb/receiver.py`, `client.py` |
| `wifi_receiver.py`, `wifi_client.py` | `connections/wifi/receiver.py`, `client.py` |
| `wifi_udp_receiver.py` | `connections/wifi/udp_receiver.py` |
| `bluetooth_receiver.py`, `bluetooth_client.py` | `connections/bluetooth/receiver.py`, `client.py` |
| `test_displays.py` | `hardware/displays/matrix.py` |
| `seven_segment.py` | `hardware/displays/seven_segment.py` |
| `ultrasonic.py` | `hardware/ultrasonic.py` |
| `check_lift_pwm.py` | `cli/check_pwm.py` |
| `controller.py` | Import tương thích đến `hardware/motors.py` cho các file thử bánh bên ngoài source này |

Ví dụ vẫn chạy `python3 wifi_receiver.py --run` trong `vehicle_testing`.
Nếu muốn dùng đường dẫn module mới, từ thư mục cha chạy
`python3 -m vehicle_testing.connections.wifi.receiver --run`.
Các package không tự mở GPIO/I²C khi import.

Lịch sử thiết kế trong `docs/` có thể dùng tên file trước khi chuyển. Hai công
cụ `probe_servo.py` và `probe_lift_pwm.py` đã không còn trước lần sắp xếp này;
các test cũ được giữ riêng tại [tests/legacy](tests/legacy/README.md), không nằm
trong discovery hiện tại. Kiểm thử nâng/hạ, càng và PWM đang có vẫn chạy bình thường.

Các lệnh dưới đây chạy từ thư mục gốc `raspberry-py`, dùng Python 3.10 trở lên.

## Kết nối bằng dây USB-C

Thử nghiệm USB được đặt trong `vehicle_testing`, chưa chuyển vào `stem_firmware`.
Pi 4 cần được cấu hình USB Serial Gadget trước để laptop thấy cổng COM.
Xem [hướng dẫn USB](docs/USB.md) về cáp, nguồn, `dwc2`/`g_serial` và cấu hình lần đầu.

Sau khi cấu hình xong, trong `vehicle_testing` trên Pi:

```sh
python3 -m pip install -r requirements-usb.txt
python3 usb_receiver.py --dry-run
```

Trên PowerShell Windows, cũng trong `vehicle_testing`:

```powershell
python -m pip install -r requirements-usb.txt
python usb_client.py
```

Chọn cổng COM rồi nhập `upload`, sau đó **tự nhập `run`** khi muốn chạy.
Upload không tự chạy. `stop` yêu cầu dừng, `status` xem trạng thái, `exit` thoát.
`upload` mặc định gửi `examples/scratch_sample.txt` của laptop. Bật phần cứng thật
bằng cách thay `--dry-run` trên Pi thành `--run`. Giữ công cụ gửi mở để có ping;
mất tin hợp lệ trong 5 giây sẽ yêu cầu dừng và xóa kịch bản chờ. Không chạy đồng
thời các receiver USB, MQTT, Wi-Fi, Bluetooth ở chế độ điều khiển phần cứng.

## Nhận Wi-Fi UDP broadcast từ FE/BE

BE thực tế gửi `UUID\n<kịch bản>` và `UUID\nEXEC` qua UDP 50000. Trên Pi:

```sh
cd ~/vehicle_testing
source .venv/bin/activate
python3 wifi_udp_receiver.py --device-id robot-003 --dry-run
```

Trên web chọn Wi-Fi, **Upload Code**, rồi **Chạy Code**. Thay `--dry-run` bằng
`--run` để chạy phần cứng. Không cần nhập IP Pi/BE: receiver nghe trên mọi IPv4
của Pi và tự nhận IP BE từ gói upload đúng UUID, hợp lệ. EXEC phải đến từ BE vừa
upload. BE đổi IP thì upload lại, không cần khởi động lại receiver.
Mỗi upload cho phép một EXEC; chạy tiếp cần upload
lại. Chỉ mở một receiver điều khiển phần cứng. Adapter này chưa có gói dò xe,
ACK, STOP hay heartbeat với BE; hiện hỗ trợ code trọn vẹn trong một datagram.
Xem [giao thức và cách thử UDP](docs/WIFI_UDP.md) trước khi dùng kịch bản nhiều
mảnh. Các công cụ HTTP dưới đây vẫn giữ nguyên.

Tự nhận IP chưa xác thực hay cấp quyền độc quyền cho học sinh: khi xe rảnh,
máy trong LAN biết UUID có thể upload hợp lệ để thay bản chờ và IP BE trước.
EXEC từ IP BE cũ bị bỏ qua, log ghi IP gửi và IP đã upload. `--sender-ip` chỉ
thêm bộ lọc nguồn, không chống giả mạo IP. Giao thức vẫn chưa có request ID để
ràng buộc EXEC với đúng phiên bản kịch bản hoặc loại bỏ mọi gói trễ/phát lại.

## Kết nối Wi-Fi bằng HTTP trực tiếp

Laptop và Pi cùng mạng, không cần MQTT broker hoặc thư viện bổ sung.
Trong `vehicle_testing` trên Pi, dùng venv đã cài phần cứng:

```sh
source .venv/bin/activate
python3 wifi_receiver.py --dry-run
```

Trên PowerShell laptop, trong `vehicle_testing`:

```powershell
python wifi_client.py --host 192.168.1.40
```

Thay IP bằng IP hiện tại của Pi. Nhập `upload`, rồi nhập riêng `run` để thực hiện;
`stop`, `status`, `exit` giống console USB. Upload không tự chạy. Giữ client mở
để tự ping; mất liên lạc khoảng 5 giây sẽ yêu cầu dừng và xóa bản chờ.
Muốn chạy motor/LED thật, thay `--dry-run` trên Pi thành `--run`, rồi kết nối và
upload lại. Mặc định không có cờ là preview. Chỉ mở một receiver điều khiển phần
cứng mỗi lần. Xem [hướng dẫn Wi-Fi và API HTTP](docs/WIFI.md) để thử độc lập với
MQTT, lấy sự kiện block/trạng thái và kết nối lại.

## Kết nối Bluetooth Classic SPP

Đọc [hướng dẫn Bluetooth](docs/BLUETOOTH.md) để cài BlueZ/D-Bus trên Pi, ghép đôi
laptop và tạo COM Outgoing trước lần thử đầu. Sau khi cấu hình xong, trong
`vehicle_testing` trên Pi:

```sh
source .venv/bin/activate
python3 bluetooth_receiver.py --dry-run
```

Trên PowerShell laptop, cũng trong `vehicle_testing`:

```powershell
python -m pip install -r requirements-bluetooth.txt
python bluetooth_client.py
```

Chọn số thứ tự cổng COM Bluetooth của Pi; nhập riêng `upload` rồi `run` ở dấu
nhắc `bt>`. Có `stop`, `status`, `exit`; client tự ping, ngắt link/hết heartbeat
sẽ yêu cầu dừng và xóa bản chờ. Bluetooth không cần Wi-Fi hay broker.
`--dry-run` là mô phỏng; muốn chạy motor/LED thật, dùng `--run` trên Pi rồi mở
lại client và upload lại. Chỉ mở một receiver điều khiển phần cứng mỗi lần.

## Chạy kịch bản Scratch có sẵn trên Pi

Đứng trong thư mục `vehicle_testing`, dùng môi trường Python đã chạy được
motor và LED trước đó:

```sh
python3 scratch_runner.py
```

Lệnh này **điều khiển phần cứng thật**, đọc mặc định file
`examples/scratch_sample.txt` theo vị trí chương trình, không cần MQTT,
UUID, FE hoặc BE. Chương trình kiểm tra toàn bộ cú pháp/lệnh/font trước
khi mở thiết bị, sau đó chạy một lượt:

1. Tiến 2 giây, dừng motor.
2. Quay trái 180° theo hệ số thời gian trong `config.py`, dừng motor.
3. Lùi 2 giây, dừng motor; tiếp tục lùi 2 giây rồi dừng motor.
4. LED ma trận chạy chữ `FFFFFFFFFFF` một lượt, sau đó `VAN BAN` một lượt.
5. Tắt LED và giải phóng kết nối motor/GPIO.

`report_block` được ghi vào terminal theo đúng thứ tự, chưa gửi lên web.
Tiến/lùi dùng PWM mặc định và hệ số bánh hiện có; góc quay là ước lượng,
chưa có cảm biến góc. LED dùng BCM7/BCM5, độ sáng 2, cùng font với
`test_displays.py`: tiếng Việt được bỏ dấu và đổi thành chữ hoa. Chữ dài
cuộn một lượt, chờ 0,1 giây giữa các khung; chữ ngắn giữ 1 giây.
Nhấn **Ctrl+C** để yêu cầu dừng motor, tắt LED và thoát. Chạy riêng runner,
không mở đồng thời các chương trình khác đang điều khiển cùng motor/GPIO.

Thử luồng trên máy tính mà không mở phần cứng hoặc chờ thời gian:

```sh
python3 scratch_runner.py --dry-run
```

Chỉnh kịch bản trong `examples/scratch_sample.txt`, hoặc chọn file khác:

```sh
python3 scratch_runner.py --file examples/scratch_sample.txt
```

Từ thư mục cha dùng `python3 -m vehicle_testing.scratch_runner` với cùng
tham số. Runner chỉ ánh xạ các lệnh đã parse sang API điều khiển sẵn có,
không dùng `exec`/`eval` để thực thi Python trong file.

## Nhận và chạy code Scratch qua MQTT

Receiver mặc định **chỉ nhận, parse và in kịch bản**. Thêm `--run` để `/execute`
chạy motor/LED qua runner; thêm `--dry-run` để thử cùng luồng bằng đầu ra mô phỏng,
không mở phần cứng và không chờ thời gian chuyển động/cuộn chữ. Ba chế độ đều
parse dữ liệu, không thực thi Python tùy ý bằng `exec`/`eval`. FE/BE chưa được sửa.

Đứng trong `vehicle_testing`, thử ngay file mẫu (không cần FE, BE hay MQTT):

```sh
python3 scratch_receiver.py --file examples/scratch_sample.txt
```

File mẫu là đoạn người dùng đã cung cấp: **7 marker và 6 lệnh**. Kết quả giữ
đúng thứ tự và block ID, bao gồm marker bắt đầu không có hành động ngay sau
nó và hai lệnh lùi giống nhau. Mỗi lệnh gắn block ID gần nhất phía trước;
nếu chưa có marker thì block ID là `None`. Log ghi cả số dòng nguồn.

Để nhận trực tiếp từ backend qua broker MQTT TCP hiện có, cài dependency
trong môi trường Python đang dùng trên Pi rồi khởi động receiver:

```sh
python3 -m pip install -r requirements-mqtt.txt
python3 scratch_receiver.py --broker IP_BROKER --device-id UUID_THIET_BI
```

Thay `IP_BROKER` bằng IP/hostname của broker (không kèm `tcp://`); thay
`UUID_THIET_BI` bằng **đúng UUID robot đang chọn trên web**, không tự đổi
`robot001` thành `robot-001`. Có thể truyền `--port`, mặc định là 1883.
Nếu chạy từ thư mục cha thì dùng `python3 -m vehicle_testing.scratch_receiver`
và cùng các tham số. Bản này dùng MQTT TCP, chưa cấu hình tài khoản/TLS.

Luồng kiểm tra ở chế độ preview mặc định:

1. Chạy receiver và chờ thông báo subscribe thành công.
2. Trên FE, Upload code. BE gửi tới `device/<UUID>/code`; Pi parse ngay và
   in từng marker/lệnh. Upload sai cú pháp, lệnh hoặc UTF-8 sẽ xóa bản đang
   chờ và báo lỗi có số dòng.
3. Bấm Run. BE gửi chuỗi `execute` tới `device/<UUID>/execute`; receiver in
   lại **PREVIEW EXECUTE** của bản hợp lệ gần nhất. Motor/LED chưa chạy.
4. Heartbeat mỗi giây chỉ gửi `idle` lên `device/<UUID>/status`. Không gửi
   `executing`, `done` hay `/block` vì đây chưa phải lượt chạy thật.
5. Mất kết nối sẽ xóa bản đang chờ; sau khi kết nối lại cần Upload lại.
   Execute retained và payload execute khác chuỗi `execute` được bỏ qua.
   Ctrl+C đóng receiver và kết nối MQTT.

### Chạy kịch bản vừa nhận qua MQTT trên xe

Sau khi cập nhật source, dừng receiver cũ bằng Ctrl+C và khởi động lại trong
`vehicle_testing` trên Pi:

```sh
python3 scratch_receiver.py --broker 127.0.0.1 --device-id robot-001 --run
```

`--run` bật điều khiển phần cứng thật khi nhận `/execute`; lúc khởi động hoặc
chỉ upload chưa mở motor/LED. Không chạy đồng thời runner riêng hay chương trình
khác đang sở hữu cùng motor/GPIO. Broker có thể nằm trên Pi như lệnh trên,
hoặc thay `127.0.0.1` bằng IP máy chạy broker.

Từ laptop, giữ nguyên cách gửi MQTT đã thử thành công: gửi toàn bộ source
tới `device/robot-001/code`, sau đó gửi `execute` tới
`device/robot-001/execute`. Pi kiểm tra cú pháp, lệnh và font trước khi lưu;
upload không hợp lệ xóa bản đang chờ, không chạy lại bản cũ. `/execute` giao
chính bản đã nhận qua MQTT cho `execute_program()`, không đọc file mẫu.

Mỗi lúc chỉ có một luồng thực thi. Upload mới trong lúc chạy chuẩn bị bản
cho lần kế tiếp; lượt đang chạy giữ nguyên bản riêng. Execute khi đang bận
bị bỏ qua, không xếp hàng. Execute retained hoặc MQTT đánh dấu `dup` bị bỏ qua;
hai lần gửi mới sau khi đã hoàn tất vẫn là hai yêu cầu chạy riêng.

Dừng từ PowerShell trên laptop (đã cài `paho-mqtt`, thay IP bằng IP Pi thực tế):

```powershell
python -c "from paho.mqtt.publish import single; single('device/robot-001/stop', 'stop', hostname='192.168.1.40', qos=1)"
```

Hoặc trên máy có `mosquitto_pub`:

```sh
mosquitto_pub -h 192.168.1.40 -q 1 -t 'device/robot-001/stop' -m 'stop'
```

Topic `/stop` chỉ nhận chuỗi `stop` mới, không retained và không đánh dấu `dup`.
Luồng thực thi dùng thời gian chờ có thể ngắt cho cả motor và LED; sau yêu cầu
dừng sẽ gửi lệnh dừng motor, tắt LED và giải phóng thiết bị. Ctrl+C cũng yêu cầu
dừng và chờ giải phóng trước khi đóng MQTT. Khi MQTT phát hiện mất kết nối,
chương trình yêu cầu dừng và xóa bản đang chờ; kết nối lại cần upload lại.
Phát hiện mất mạng phụ thuộc keepalive MQTT, không phải dừng tức thì ngay khi
Wi-Fi rớt. Các thao tác I²C/GPIO bị kẹt vẫn có thể trì hoãn việc dừng.

Trạng thái trên `device/robot-001/status`:

| Payload | Ý nghĩa |
| --- | --- |
| `idle` | Heartbeat khi không chạy |
| `executing` | Đang thực thi, tiếp tục heartbeat mỗi giây |
| `done` | Hoàn tất và đã giải phóng thiết bị |
| `stopped` | Dừng theo yêu cầu và đã giải phóng thiết bị |
| `error` | Lỗi thực thi hoặc giải phóng, xem log trên Pi |

`done`/`stopped`/`error` được gửi một lần khi kết thúc; heartbeat sau đó trở lại
`idle`. `report_block` hiện ghi vào terminal, chưa đẩy highlight lên web. BE hiện
chỉ xử lý `idle`/`executing`/`done`, chưa xử lý `stopped`/`error`; lỗi lấy UUID
trong listener BE ở bên dưới vẫn cần sửa để trạng thái web cập nhật đúng.

Để thử bằng mô phỏng, thay `--run` bằng `--dry-run`. Không thêm cả hai cùng lúc.
Kịch bản chỉ giữ trong RAM, không tự chạy lại khi khởi động. Thay đổi này chưa
cài dịch vụ tự khởi động cùng Pi.

Các dạng được hỗ trợ:

| Dạng | Ý nghĩa trong parser |
| --- | --- |
| `report_block("id")` | Marker tiến độ, giữ nguyên ID |
| `robot.sendCmd("move_forward:5")` | Tiến 5 **giây** |
| `robot.sendCmd("move_backward:2")` | Lùi 2 **giây** |
| `robot.sendCmd("turn_left:180")` / `turn_right:90` | Quay theo **độ** |
| `robot.sendCmd("led_strip:văn:bản")` | Chuỗi gốc `văn:bản`, chỉ tách dấu `:` đầu tiên |

Tham số số phải dương và hữu hạn; hỗ trợ số thập phân. Text không bị bỏ
dấu/đổi chữ trong parser. Việc chuẩn hóa font thuộc bước hiển thị sau này.
Chỉ nhận lời gọi có một chuỗi cố định, chưa hỗ trợ biến, vòng lặp, điều kiện,
import, hàm tùy ý hay biểu thức tính toán. Bản preview giới hạn nguồn
**64 KiB UTF-8 và 1000 sự kiện**; backend hiện cho phép payload lớn hơn nên
receiver có thể từ chối một upload mà BE đã nhận.

**Cần đồng bộ trước khi chạy từ FE/BE:** block tiến/lùi trong dữ liệu BE hiện
còn ghi `cm`, trong khi hợp đồng vừa thống nhất là giây. Listener status
của BE cũng đang lấy UUID từ `parts[2]` thay vì `parts[1]` trong topic
`device/<UUID>/status`; vì vậy kết quả online trên web chưa phải bằng chứng
receiver không nhận được MQTT. Các điểm FE/BE này chưa được sửa ở bước parse.

## Nhập nội dung cho LED ma trận 16×8

Chạy riêng chương trình test trên Raspberry Pi. Từ thư mục gốc:

```sh
python3 vehicle_testing/test_displays.py --target matrix --interactive
```

Nếu terminal đang ở ngay trong `vehicle_testing`, dùng:

```sh
python3 test_displays.py --target matrix --interactive
```

Tại dấu nhắc `Nhap noi dung>`, nhập nội dung rồi Enter. Có thể nhập nội dung
mới khi chữ cũ đang chạy. Ví dụ `Xin chào đèn` sẽ thành `XIN CHAO DEN`.
Enter trống xóa màn hình; nhập `thoat`, Ctrl+D (EOF) hoặc Ctrl+C để thoát.
Chương trình gửi lệnh tắt LED và dọn riêng GPIO đã dùng khi kết thúc.

Font hỗ trợ A–Z, 0–9, khoảng trắng và các dấu `.,!?':;+-/=()_`. Chữ thường
đổi thành chữ hoa, tiếng Việt bỏ dấu (kể cả đ/Đ). Ký tự chưa có font được báo
rõ và giữ nguyên nội dung đang hiển thị. Nội dung vừa 16 cột sẽ đứng yên ở
giữa; nội dung dài hơn chạy từ phải sang trái và lặp lại. Cách vẽ hiện dùng
bit 0 làm hàng trên cùng; chiều hiển thị thực tế tùy cách lắp ma trận.

Để truyền nội dung ngay khi chạy, hoặc dùng lại mẫu HELLO:

```sh
python3 vehicle_testing/test_displays.py --target matrix --text "Xin chào robot 123!"
python3 vehicle_testing/test_displays.py --target matrix --hello
```

Các chế độ `--text`/`--hello` chỉ áp dụng cho ma trận (`--target matrix` hoặc `both`). Chạy
không có chế độ chữ vẫn giữ mẫu `OK` và số `1234` như trước. Mặc định ma trận
dùng SCLK **BCM7**, DIN **BCM5** theo code cũ; đổi bằng `--matrix-clk` và
`--matrix-dio` theo dây thực tế. BCM7 phải rảnh, không được SPI0 hoặc chương
trình khác sử dụng đồng thời. Chế độ nhập liên tục dùng terminal Linux/SSH;
chương trình test không mở motor hoặc servo.

## LED 7 đoạn: nhập số và tự cập nhật khoảng cách

Trên Raspberry Pi, nếu terminal đang ở trong `vehicle_testing`, chạy:

```sh
python3 seven_segment.py
```

Hoặc từ thư mục cha dùng `python3 -m vehicle_testing.seven_segment`. LED bắt
đầu ở `0000`, và chương trình chờ tại `led7>`:

```text
123       # Hiện 0123, chế độ nhập tay
auto      # Mở cảm biến siêu âm và cập nhật khoảng cách
456       # Đóng cảm biến, chuyển về nhập tay, hiện 0456
thoat     # Tắt LED, đóng cảm biến nếu còn mở và thoát
```

Chỉ nhập nội dung trước dấu `#`; phần sau là giải thích. Enter trống xóa LED
và rời chế độ auto. Ctrl+C hoặc EOF cũng thoát và dọn tài nguyên. Dữ liệu
không hợp lệ giữ nguyên chế độ và nội dung cũ. Có thể nhập `auto` lại sau
khi đã quay về thủ công.

Mặc định CLK **BCM16**, DIO **BCM6**; cảm biến TRIG **BCM8**, ECHO **BCM11**.
Tất cả là số BCM, độc lập với số kênh PCA9685. Có thể đổi theo dây thực tế
bằng `--clk`, `--dio`, `--trig`, `--echo`. Chương trình từ chối mở cảm biến
nếu chân cảm biến trùng chân LED. Chạy riêng các test dùng cùng GPIO.

Chế độ auto nghỉ 0,2 giây sau mỗi lần đọc; có thể đổi bằng `--interval`.
Khoảng cách làm tròn đến cm (27,5 thành 0028). Timeout, lỗi đọc hoặc giá trị
không hiển thị được sẽ hiện `----` và tiếp tục thử; dữ liệu hợp lệ sau đó
tự khôi phục. Không có chức năng điều khiển/dừng xe. LED hiển thị số chưa
đồng nghĩa số đo đã được hiệu chuẩn với thước.

```sh
python3 seven_segment.py --auto
python3 seven_segment.py --brightness 4 --trig 8 --echo 11
```

File test cũ cũng có đường vào tương đương:

```sh
python3 test_displays.py --target 7seg --interactive
python3 test_displays.py --target 7seg --distance
```

API để chương trình khác (hoặc adapter Scratch sau này) gọi lại:

```python
from vehicle_testing.seven_segment import SevenSegmentDisplay

with SevenSegmentDisplay() as led:
    led.show_number(123)       # 0123; nhận số 0..9999, làm tròn phần thập phân
    led.set_brightness(3)      # 0..7, không đổi số đang hiển thị
    led.show_error()           # ----
    led.clear()                # Xóa bốn vị trí
    # Giữ đối tượng trong suốt phiên ứng dụng; ra khỏi with sẽ tắt LED.
```

Đầu vào của `show_number()` có thể đến từ hằng số, biến, phép tính hoặc
`sensor.read_distance_cm()` của `UltrasonicSensor`. Import module không mở
GPIO, motor hay servo. Phần Scratch/frontend/runtime chưa được nối trong
thay đổi này; hiện chưa có API hiển thị chữ, chạy chữ hoặc nhiệt độ cho LED
7 đoạn.

## Đọc cảm biến siêu âm riêng

Chạy trên Raspberry Pi từ thư mục gốc, với TRIG mặc định là **BCM 8** và ECHO
là **BCM 11**, nguồn cảm biến OhStem **3,3 V** và GND chung:

```sh
python3 -m vehicle_testing.ultrasonic
```

Hoặc nếu terminal đang ở ngay trong thư mục `vehicle_testing`:

```sh
python3 ultrasonic.py
```

Nếu đấu GPIO khác, truyền `--trig 17 --echo 27` theo dây thực tế. Các chân
phải đang rảnh; BCM 8/11 còn dùng cho SPI0. Không chạy đồng thời module này
với `test_ultrasonic.py` vì chúng dùng cùng chân cảm biến.

Module in từng số đo theo cm, nghỉ 0,2 giây giữa các lần đọc và báo
`KHONG DOC DUOC` khi ECHO bị treo hoặc timeout. Nhấn Ctrl+C để thoát và dọn
riêng hai chân cảm biến. Giá trị ngoài khoảng 3–400 cm được giữ nguyên kèm
ghi chú; phạm vi thực tế cần kiểm chứng vì tài liệu OhStem cũng ghi 3–200 cm.

Code khác có thể dùng `with UltrasonicSensor() as sensor:` rồi gọi
`sensor.read_distance_cm()` (import từ `vehicle_testing.ultrasonic`). Hàm trả
`float` theo cm, phát sinh `TimeoutError` khi không đọc được, và không lọc/làm
mượt dữ liệu. Bên gọi cần để khoảng nghỉ giữa các lần đo. Thư viện GPIO chỉ
được nạp lúc tạo cảm biến; import module trên máy tính không mở phần cứng.

Đây là chức năng đọc riêng; lệnh điều khiển trong `main.py` chưa gọi cảm biến
và chưa có chức năng tự dừng khi gặp vật cản.

## Thử trên máy tính, không cần Raspberry Pi

```sh
python vehicle_testing/main.py --dry-run
```

Không cần cài thư viện phần cứng cho chế độ này. Thời gian chờ vẫn diễn ra
đúng theo lệnh để dễ quan sát luồng chạy. Thêm `--verbose` để xem các kênh:

```sh
python vehicle_testing/main.py --dry-run --verbose
```

## Chạy trên Raspberry Pi

Bật I²C trên Raspberry Pi và dùng môi trường Python có hỗ trợ Adafruit Blinka.
Ví dụ tạo môi trường riêng trên Raspberry Pi OS:

```sh
sudo apt install python3-venv
python3 -m venv --system-site-packages vehicle_testing/.venv
source vehicle_testing/.venv/bin/activate
python -s -m pip install --no-user -r vehicle_testing/requirements.txt
python vehicle_testing/main.py
```

Chương trình mở kết nối và gửi lệnh dừng khi khởi động; chỉ chạy bánh khi nhận
`chay` và kịch bản đã có lệnh hợp lệ. Không chạy đồng thời với các chương trình khác đang
điều khiển cùng PCA9685.

## Lệnh điều khiển

```text
tien 2
lui 2
tien 3
lui 1
chay
```

**Enter sau mỗi dòng chuyển động hoặc `ngung` chỉ lưu lệnh, xe chưa chạy.** Chương trình
báo `Da luu lenh #...` để xác nhận đã thêm vào kịch bản. Khi nhập đủ, gõ
`chay` rồi Enter để thực hiện lần lượt từ trên xuống. Mỗi lệnh gửi lệnh dừng
trước khi sang lệnh tiếp theo. Cả bốn lệnh trên đều dùng PWM **50%**.

Bạn cũng có thể dán cả khối, bao gồm dòng `chay`. Nếu dòng cuối chưa có ký tự
xuống dòng thì nhấn Enter thêm để gửi. Sau khi thực hiện, danh sách lệnh được
xóa; gõ `chay` lần nữa không chạy lại kịch bản cũ. Có thể soạn kịch bản mới
trong cùng phiên.

Để nghỉ giữa các chuyển động, thêm **`ngung <giây>`**:

```text
tien 2
ngung 0.5
lui 1
chay
```

Kịch bản này tiến 2 giây, gửi lệnh dừng các bánh và chờ 0,5 giây, sau đó mới
lùi 1 giây. Các lệnh tiến/lùi thiếu PWM vẫn dùng 50%.
`ngung` không nhận tham số PWM và không hủy những lệnh phía sau.
Thời gian nghỉ có thể là số thập phân hoặc số lớn, ví dụ `ngung 0.5`,
`ngung 10`, `ngung 3600`; chương trình không đặt mức tối đa. Thời gian phải
là số dương hữu hạn, vì vậy `0`, số âm, `nan` và `inf` đều bị từ chối.

Nếu muốn chọn PWM cho một lệnh, nhập thêm tham số thứ ba:

```text
tien 2 0.3
lui 2
lui 1 0.3
chay
thoat
```

- `tien 2`: lưu lệnh tiến khoảng 2 giây ở PWM mặc định 50%.
- `lui 2`: lưu lệnh lùi khoảng 2 giây ở PWM mặc định 50%, kể cả khi lệnh trước dùng PWM khác.
- `tien 2 0.3`: lưu lệnh tiến khoảng 2 giây ở PWM 30%.
- `lui 1 0.3`: lưu lệnh lùi khoảng 1 giây ở PWM 30%.
- `ngung 0.5`: lưu lệnh gửi yêu cầu dừng các bánh, chờ 0,5 giây rồi tiếp tục kịch bản.
- `chay`: thực hiện kịch bản đã lưu; danh sách rỗng thì chỉ thông báo, xe không chạy.
- `dung`: gửi lại lệnh dừng các kênh động cơ và xóa toàn bộ kịch bản đang soạn.
- `thoat`: hủy kịch bản chưa chạy, gửi lệnh dừng và đóng kết nối.

Với lệnh tiến/lùi, thứ tự tham số là **chiều → số giây → PWM tùy chọn**. Mỗi lần bỏ trống PWM đều
dùng 50%, không ghi nhớ PWM của lệnh trước. Giá trị mặc định dùng chung nằm ở
`DEFAULT_SPEED = 0.5` trong `config.py`, áp dụng cả khi gọi `MotorController.move()`
mà không truyền `speed`. Số giây phải hữu hạn và lớn hơn 0; PWM phải hữu hạn và
trong khoảng `(0, 1]`. Dùng dấu chấm cho phần thập phân.
Giá trị sai, kể cả PWM `5`, `nan` hoặc `inf`, bị từ chối.

Khi thực hiện kịch bản, các chuyển động chạy đồng bộ; chương trình trở về
dấu nhắc nhập lệnh sau khi kịch bản hoàn tất.
Trong lúc đang thực hiện chuyển động hoặc chờ `ngung`, dùng **Ctrl+C** để yêu cầu dừng và thoát, thay vì nhập
`dung`. Hết đầu vào (EOF) cũng đóng phiên và hủy các lệnh chưa được xác nhận
bằng `chay`; không tự chạy kịch bản khi EOF. Dòng không hợp lệ bị từ chối,
không thêm vào danh sách; các dòng hợp lệ trước đó vẫn được giữ để bạn tiếp tục soạn.
Lỗi khi thực hiện một lệnh sẽ hủy các lệnh còn lại và thoát phiên.
Ctrl+C trả mã thoát 130; lỗi phần
cứng hoặc dừng thất bại trả mã 1. Bình thường trả mã 0.

## Tay nâng/hạ qua GPIO BCM 18

Servo DS-S006M nâng/hạ nối vào **GPIO BCM 18** trên Raspberry Pi, dùng driver
**`pwm-gpio` của kernel ở 50 Hz**, qua API sysfs của `rpi-hardware-pwm`.
Chân này đã được người dùng xác nhận bằng phép thử `probe_servo.py --pin 18`.
Tần số này độc lập với PWM 1000 Hz của PCA9685 điều khiển bánh xe.
Không chạy đồng thời với chương trình khác đang dùng GPIO 18 hoặc GPIO 12.
Giữ nguyên dây; không còn dùng `RPi.GPIO` để phát xung nâng/hạ trong `main.py`.
Đây vẫn là PWM phần mềm, do bộ định thời kernel tạo xung; không phải PWM phần cứng.
`--dry-run` không mở GPIO hoặc sysfs PWM.

Giữ hai dòng đang dùng cho càng và thêm dòng thứ ba dưới `[all]` trong
`/boot/firmware/config.txt`:

```ini
dtparam=audio=off
dtoverlay=pwm,pin=12,func=4
dtoverlay=pwm-gpio,gpio=18
```

Khởi động lại Pi. Sau khi cập nhật source, từ thư mục `~/vehicle_testing`, chạy:

```sh
.venv/bin/python check_lift_pwm.py
```

Lệnh chỉ đọc, không làm servo chuyển động. Nó tìm đúng provider `pwm-gpio`
của BCM 18, không mặc định là `pwmchip1`. Nếu số chip của càng đổi, kiểm tra
driver phần cứng được báo rồi sửa `CLAW_PWM_CHIP` trong `config.py`;
đầu ra càng sẽ từ chối mở nhầm chip `pwm-gpio`.
Sau khi nạp overlay này, không chạy `probe_servo.py --pin 18` hoặc chương trình
`RPi.GPIO` khác trên BCM 18, kể cả khi `main.py` đã thoát: kernel đang sở hữu chân.

```text
nang 4
ha 4
chay
```

Chỉ dùng `nang [giây]` và `ha [giây]`: nâng tới **80°**, hạ tới **−10°**.
Bỏ số giây thì mặc định 2 giây (`SERVO_MOVE_SECONDS`); thời gian phải hữu hạn,
ít nhất 2 giây (`SERVO_MIN_MOVE_SECONDS`). Không nhận thêm góc hoặc PWM.
Lệnh đặt góc tay cũ đã được bỏ khỏi CLI.

**Nâng/hạ đã được cho phép chạy thử theo yêu cầu người dùng**, giữ mốc −10°/80°.
Trong `config.py`, cấu hình thử đã được đổi theo chiều vật lý thực tế (xung tăng là nâng):

```python
SERVO_CALIBRATED = False
SERVO_DOWN_PULSE_US = 450.0   # Mốc hạ người dùng đã thử và chọn.
SERVO_UP_PULSE_US = 1400.0    # Nâng 80°.
```

Người dùng xác nhận hạ 450 µs phù hợp sau khi tự thử các thông số; giữ nâng
1400 µs đang tạm ổn. 450 µs là mốc riêng của cơ cấu này, thấp hơn dải danh định
500–2500 µs được nêu cho DS-S006M; không áp dụng như mặc định cho servo khác.

`SERVO_CALIBRATED=False` thông báo hai xung chưa được đo trên xe, không còn khóa
lệnh. Constructor đầu ra sẽ cảnh báo rõ chế độ thử. Xung thiếu, không hữu hạn,
trùng nhau hoặc ngoài 450–2500 µs vẫn bị từ chối trước khi mở PWM nâng/hạ.
Người dùng đã báo tay chạm/ép điểm chặn với ánh xạ cũ; đổi driver không chứng minh
hai đầu hành trình đã đúng. Nếu chạm khung, dùng Ctrl+C để dừng phép thử và sửa
hai mốc xung theo thực tế. Xem [ghi chú hiệu chỉnh tay](docs/lift-calibration.md).

Phép thử `nang 4` bật lên ngay và chạm chặn; lần dò 1510/1520 µs sau đó vẫn
giật rất mạnh. Các số 1500/500 µs chưa được xác nhận phù hợp. Đã dừng hướng
dẫn thử tiếp các đợt xung ngắn tại điểm chặn. Công cụ dò không bảo đảm chuyển
động chậm; xem ghi chú trên về dữ liệu cần đo trước khi chọn mốc mới.

**Trước khi khởi động, để tay ở vị trí hạ −10°**, theo vị trí khởi đầu người dùng
đã xác nhận có thể chuẩn bị. Đây là vị trí giả định (`SERVO_START_ANGLE`), không phải góc đọc từ cảm biến;
khởi tạo không tự phát xung hoặc đưa tay về gốc. Các lệnh chuyển góc theo từng
bước tối đa 20 ms, tăng/giảm tốc nhẹ ở hai đầu, sau đó chờ thêm 0,1 giây.
`nang 4` chuyển yêu cầu −10° → 80° trong 4 giây; `ha 4` đi ngược lại.
Gửi lại cùng một đích đã yêu cầu sẽ bỏ qua. Lỗi/ngắt giữa chừng làm mất mốc và
chặn các lệnh tay tiếp theo; cần chuẩn bị lại mốc hạ và khởi động lại.

Các số −10°/80° là mốc góc quy ước của cơ cấu. Chương trình
nội suy giữa `SERVO_DOWN_PULSE_US` và `SERVO_UP_PULSE_US`; không tự suy ra xung từ
số độ. Xung nâng/hạ được kiểm tra trong 450–2500 µs để chấp nhận mốc 450 µs
người dùng đã thử; đây là giới hạn phần mềm, không xác nhận toàn khoảng đó
là hành trình cơ khí cho phép.

Enter chỉ lưu lệnh; `chay` mới thực hiện. Có thể xen kẽ với lệnh bánh xe và càng;
chương trình gửi lệnh dừng bánh trước khi điều khiển tay. BCM 18 dùng bộ định thời
kernel để tạo xung thay cho luồng Python; chưa xác nhận độ rung trên cơ cấu thật.
Giữ PWM chạy giữa các bước, chỉ đổi duty, bỏ qua xung nguyên µs trùng nhau.
Không đổi overlay để xuất PWM0 phần cứng ra BCM 18,
vì kênh PWM0 đang dùng cho càng BCM 12.

PWM servo nâng/hạ mặc định được tắt sau mỗi hành trình (`SERVO_HOLD_POSITION=False`),
sau khoảng chờ cuối 0,1 giây, để không tiếp tục giữ cứng tay. Servo càng cũng
mặc định ngắt PWM sau lệnh như mô tả dưới đây. Cơ cấu có thể hạ theo tải khi mất
lực giữ. Nếu di chuyển tay bằng tay, chương trình không cập nhật được góc thực;
cần chuẩn bị lại mốc hạ và khởi động lại trước khi chạy tiếp.
Đặt `SERVO_HOLD_POSITION=True` khi cần giữ lực và đã xác nhận cơ cấu phù hợp.
`dung` vẫn hủy kịch bản đang soạn.
Khi `thoat`, EOF, Ctrl+C hoặc lỗi, chương trình tắt PWM và giải phóng riêng từng GPIO servo đã mở;
sau đó servo không còn được yêu cầu giữ lực và tay có thể hạ theo tải.

Thử luồng trên máy tính trước:

```sh
python vehicle_testing/main.py --dry-run
```

Sau khi kiểm tra lệnh, dùng cách chạy trên Raspberry Pi ở phần trên để chạy thật.
Giới hạn góc và chiều nâng/hạ vẫn cần xác nhận với cơ cấu thực tế.

### Mở/khép càng qua GPIO BCM 12

Servo càng 12G dùng **GPIO BCM 12**, đã được người dùng xác nhận bằng probe.
Theo xác nhận mới nhất trên xe: **tăng góc từ 0° lên 100° thì mở càng**,
giảm từ 100° về 0° thì khép càng.

```text
mo_cang 2
dong_cang 2
chay
```

Chỉ dùng `mo_cang [giây]` và `dong_cang [giây]`, không cần lệnh đặt mốc góc.
Mở yêu cầu **100°**, đóng yêu cầu **0°**. Giới hạn riêng của càng là 0–100°.
Các giá trị riêng của càng nằm ở `CLAW_OPEN_ANGLE`, `CLAW_CLOSE_ANGLE`,
`CLAW_MIN_ANGLE` và `CLAW_MAX_ANGLE` trong `config.py`; nâng/hạ dùng riêng −10–80°.
Người dùng xác nhận càng có thể khép; các góc yêu cầu chưa phải số đo cơ khí.

**Trước mỗi lần khởi động chương trình, để càng khép ở vị trí 0°**.
`CLAW_START_ANGLE` là vị trí khởi đầu giả định;
chương trình không tự chạy càng về gốc, không đọc được góc và không phát PWM khi
khởi tạo. Nếu càng không ở vị trí này, lần phát xung đầu vẫn có thể gây bật nhanh.

`mo_cang 2` chia chuyển động yêu cầu **0° → 100° trong 2 giây**;
`dong_cang 2` chuyển **100° → 0° trong 2 giây**. Bỏ số giây mặc định 2
(`CLAW_MOVE_SECONDS`). Mỗi khoảng tối đa 20 ms (`CLAW_UPDATE_INTERVAL_SECONDS`)
cập nhật một góc; đường chuyển góc tăng tốc và giảm tốc nhẹ ở hai đầu.
Thời gian phải hữu hạn và **ít nhất 2 giây** (`CLAW_MIN_MOVE_SECONDS`), không nhận
thêm góc hoặc PWM. Có thể dùng `mo_cang 4`/`dong_cang 4` để chia bước chậm hơn.
Sau góc cuối, chờ thêm `CLAW_SETTLE_SECONDS = 0.1` giây trước khi ngắt PWM;
lệnh 2 giây mất ít nhất khoảng **2,1 giây** tổng cộng, có thể dài hơn do lịch chạy hệ điều hành.
Thời gian này điều khiển lịch gửi góc yêu cầu; chưa xác nhận tốc độ cơ cấu thật.
`probe_servo.py` vẫn gửi góc trực tiếp, không áp dụng cách chuyển từng bước này.

Trên Pi 4 / Debian 13 Trixie của người dùng, riêng càng dùng **PWM phần cứng của
kernel** qua `rpi-hardware-pwm`, PWM0 trên BCM 12. Xung được tạo bởi bộ PWM;
Python chỉ thay đổi độ rộng xung khi chuyển góc. Không tắt/bật PWM hoặc đổi tần số
ở mỗi bước. Đây là xử lý một nguồn có thể gây giật trong lúc di chuyển; chưa
xác nhận nguyên nhân trên xe là xung, nguồn điện hay tải cơ khí.
Các bước góc vẫn được giữ; góc trùng cùng độ rộng xung nguyên µs không gửi lại.
Góc quy ước của càng tách khỏi góc điện của servo: **khép 0° → 1611 µs**,
**mở 100° → 500 µs**. `CLAW_CLOSE_PULSE_US` và `CLAW_OPEN_PULSE_US` giữ hai
mốc điện của bản PWM từng chạy ổn, không phải số đo mới trên cơ cấu. Vì vậy
đổi tên mốc góc không làm lần phát xung đầu nhảy từ mốc khép sang mốc mở.
Phần mềm nội suy giữa hai xung này trong thời gian yêu cầu; nếu càng vẫn tới
đích sớm, cần xác định lại hai mốc điện theo hành trình thật. Chỉ tăng thời gian
hoặc đổi đường nội suy không xác nhận cơ cấu sẽ chuyển động đúng số giây đó.
Nâng/hạ dùng riêng driver `pwm-gpio` trên BCM 18 như phần thiết lập ở trên.

Thiết lập một lần theo [hướng dẫn Pi 4 / Trixie](docs/pi4-claw-pwm.md).
Trong `/boot/firmware/config.txt`, dưới `[all]`, cấu hình riêng BCM 12:

```ini
dtparam=audio=off
dtoverlay=pwm,pin=12,func=4
```

Tắt audio analog để nhường bộ PWM. Không dùng overlay mặc định xuất PWM ra BCM 18,
vì đó là servo nâng/hạ. Khởi động lại Pi để áp dụng, sau đó chạy từ thư mục
`vehicle_testing` trong môi trường Python đang dùng:

```sh
sudo apt install python3-venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -s -m pip install --no-user -r requirements.txt
python main.py
```

Nếu thiếu quyền ghi `/sys/class/pwm`, có thể thử với đúng Python hiện tại:

```sh
sudo "$(command -v python)" main.py
```

Với cả hai overlay, phép kiểm tra trên Pi đã xác nhận càng dùng `pwmchip1`:
`CLAW_PWM_CHIP=1`, `CLAW_PWM_CHANNEL=0`. BCM 18 được tìm tự động (hiện `pwmchip0`).
Chạy lại công cụ kiểm tra nếu kernel đánh số chip khác. Thiếu overlay, quyền truy cập hoặc lỗi phát xung sẽ
dừng kịch bản, không tự chuyển về PWM cũ. `--dry-run` không nhập thư viện PWM
phần cứng hoặc truy cập sysfs. Phương án này không cần daemon pigpio; thư viện
pigpio có hạn chế trên các bản Debian mới.
Không chạy `probe_servo.py` hay chương trình servo khác cùng lúc với `main.py`.

Mặc định **`CLAW_HOLD_POSITION = False`**: hết thời gian thì gửi duty 0 để ngắt
PWM riêng BCM 12. Càng không giữ lực kẹp liên tục và vật đang kẹp có thể tuột.
Nâng/hạ BCM 18 cũng mặc định tắt PWM sau hành trình. `CLAW_HOLD_POSITION = True` giữ PWM sau thao tác;
chỉ dùng sau khi kiểm tra nguyên nhân giật thực tế. Người dùng từng xác nhận
càng hết giật ngay khi Ctrl+C tắt PWM; chưa xác định nguyên nhân phần cứng.

Nếu góc yêu cầu cuối đã trùng đích (gồm lệnh đóng ngay sau khởi động), bỏ qua thao
tác và không phát lại PWM. Sau khi nhả PWM, vị trí thật có thể thay đổi do ngoại lực;
chương trình không đo được sự thay đổi đó. Khi đã dịch chuyển càng bằng cách khác,
cần chuẩn bị lại trạng thái khép và khởi động lại. Lỗi/ngắt giữa chừng làm mất vị
trí tham chiếu và chặn lệnh càng tiếp theo tới khi khởi động lại.
Các lệnh vẫn xếp hàng tới khi nhập `chay`, dừng bánh trước khi điều khiển càng,
hủy phần còn lại khi lỗi/ngắt, và giải phóng riêng từng GPIO khi thoát.

Nếu các góc trung gian vẫn làm càng bật tới hết hành trình, chia bước trong phần
mềm chưa đủ để xử lý: cần xác định dải xung thực và phản ứng của servo. Chuyển
chậm cũng không khắc phục việc góc đích vượt giới hạn cơ khí. Hướng dẫn
[Adafruit về hiệu chỉnh servo](https://learn.adafruit.com/16-channel-pwm-servo-driver/using-the-adafruit-library)
khuyến nghị tiếp cận dần và dừng trước giới hạn hành trình để tránh hỏng bánh răng.

### Chẩn đoán cổng servo chưa xác định GPIO

Tên in trên bo như PWM4 hoặc S1 cần được đối chiếu với đường mạch; số cổng
không tự trở thành số BCM. Các ví dụ cũ trong repo có thể dùng chân khác;
chưa có sơ đồ xác nhận từng cổng trên bo Edison Academy Rev1.1.
Trên xe hiện tại, phép thử thực tế đã xác nhận **nâng/hạ = BCM 18**,
**càng = BCM 12**; hai giá trị này đã được áp dụng trong `config.py`.

`probe_servo.py` thử riêng **một GPIO được chọn**, không mở PCA9685 hoặc motor.
Thoát `main.py` và các chương trình servo khác trước khi thử thật. Chạy từ
thư mục `vehicle_testing` trên Pi:

```sh
python probe_servo.py --pin 18
```

Phép thử chỉ yêu cầu **40° → 30° → 40°**, mỗi góc giữ hai giây, rồi tắt PWM
và giải phóng riêng GPIO đã chọn. Sau đó tay không còn được yêu cầu giữ lực.
Quan sát xem servo nào di chuyển; log không đo được chuyển động thực tế.
File hỗ trợ các ứng viên `12`, `13`, `18`, `19` để tìm chân trên xe chưa xác định.
Với xe hiện tại, đã xác nhận **18 nâng/hạ, 12 càng**; không cần dò lại.
Nếu các chân đều không có chuyển động thì cần kiểm tra nguồn VCC/GND
và tín hiệu tại giắc bằng thiết bị đo.
Chỉ thử khi cơ cấu cho phép chuyển động trong khoảng 30–40°.
Thêm `--dry-run` để chỉ in yêu cầu, không nhập thư viện GPIO và không chờ.

### Càng luôn mở hết dù đổi góc: xác định loại servo trước

Nhãn "12G Digital Servo" chưa xác nhận servo định vị hay quay liên tục.
Các lệnh càng dùng thang điện 180° với hai góc đích 0°/100° theo cấu hình;
đó chưa phải dải cơ khí đã hiệu chỉnh của càng thực tế.
Theo ánh xạ hiện tại, khép 0°/mở 100° tương ứng 1611/500 µs. Nếu servo quay
liên tục, dải này có thể chỉ yêu cầu quay cùng một chiều; nếu là servo định vị,
cơ cấu cũng có thể chạm hết hành trình trong dải này. Chưa xác định nguyên nhân
chỉ từ việc cả các góc đều làm càng mở hết. Ngắt PWM chỉ dừng yêu cầu giữ xung,
không xác nhận góc được điều khiển đúng.

Để phân biệt, tắt nguồn và tách liên kết cơ khí của servo khỏi càng trước khi
thử xung trực tiếp. Không thử xung quanh 1500 µs khi cơ cấu vẫn gắn và chưa biết
biên hành trình; 1500 µs không được bảo đảm là vị trí an toàn hoặc điểm dừng.
Thoát các chương trình servo khác. Chạy từng lệnh riêng trên Pi:

```sh
python probe_servo.py --pin 12 --pulse-us 1500 --seconds 2
python probe_servo.py --pin 12 --pulse-us 1450 --seconds 2
python probe_servo.py --pin 12 --pulse-us 1550 --seconds 2
```

Quan sát **trong lúc xung còn được phát**: nếu trục cứ quay và hai phía làm
quay ngược chiều, điều đó phù hợp với servo quay liên tục. Nếu trục tới các
vị trí rồi đứng yên dù xung vẫn còn, điều đó phù hợp với servo định vị.
Phép thử giới hạn 1000–2000 µs, mỗi lần tối đa 3 giây, rồi tắt PWM và chỉ dọn
GPIO được chọn; không tự đo hoặc kết luận loại servo. Điểm dừng thực tế có
thể khác 1500 µs. Có thể thêm `--dry-run` để xem yêu cầu mà không mở GPIO.
Nếu xác nhận servo quay liên tục, cần đổi lệnh càng sang tốc độ/thời gian hoặc
thêm phản hồi vị trí; chưa được coi góc cấu hình là góc thực.
Tham khảo sự khác nhau giữa xung vị trí và xung tốc độ tại
[Adafruit: servo pulse](https://makecode.adafruit.com/reference/pins/servo-set-pulse).

## Bù PWM riêng từng bánh

Trong `config.py`, cấu hình hệ số thử nghiệm:

```python
WHEEL_GAIN = {"FR": 0.90, "FL": 1.00, "RL": 1.00, "RR": 1.00}
```

PWM thực cấp cho từng bánh = PWM yêu cầu × `WHEEL_GAIN[tên bánh]`.
Ví dụ lệnh yêu cầu PWM 50% thì FR nhận 45%, các bánh hoạt động còn lại nhận 50%.
Bánh không hoạt động vẫn nhận PWM 0; hệ số không thay đổi chiều quay.
Log `PWM tung banh` hiển thị mức PWM sau khi bù, kể cả bánh đang dừng.

Hệ số áp dụng cho tiến/lùi, ngang, bốn hướng chéo và quay trái/phải, ở cả hai
chiều motor. Vì vậy sau khi đổi hệ số cần kiểm tra lại góc quay đã hiệu chỉnh.
Mỗi hệ số phải là số hữu hạn trong `(0, 1]`; dùng `1.00` để bỏ bù cho bánh đó.
Khởi động lại chương trình sau khi sửa cấu hình.

FR `0.90` là mức thử do người dùng chọn, chưa xác nhận xe giữ thẳng trên sàn.
PWM giảm 10% không có nghĩa tốc độ bánh giảm đúng 10%; chương trình chưa có
phản hồi tốc độ bánh hoặc hướng thân xe.

## Chạy ngang trái/phải bằng bánh Mecanum

Lệnh `ngang_trai <giây> [PWM]` và `ngang_phai <giây> [PWM]` yêu cầu cả thân xe
dịch ngang theo hướng trái/phải của xe, giữ nguyên hướng đầu xe. Đây là chuyển
động trượt ngang, khác với `trai`/`phai` yêu cầu xoay thân xe.

Thử từng chiều riêng trên mặt sàn bằng thời gian ngắn:

```text
ngang_trai 0.5 0.3
chay
```

Quan sát xong mới thử:

```text
ngang_phai 0.5 0.3
chay
```

`0.5` là **giây**, không phải cm hoặc độ; `0.3` là PWM 30%. Bỏ PWM thì mỗi lệnh
dùng `DEFAULT_SPEED`, hiện là 50%, không kế thừa PWM của lệnh trước.
Thời gian phải dương và hữu hạn; PWM trong `(0, 1]`, cùng quy tắc với tiến/lùi.

Với kiểu lắp con lăn Mecanum dạng X như tài liệu và chiều tiến vật lý đã xác nhận:

| Lệnh | FR | FL | RL | RR |
| --- | --- | --- | --- | --- |
| `ngang_trai` | Tiến | Lùi | Tiến | Lùi |
| `ngang_phai` | Lùi | Tiến | Lùi | Tiến |

Cả bốn bánh dùng cùng PWM yêu cầu, sau đó bù riêng theo `WHEEL_GAIN`.
Kiểm tra chiều từng bánh khi kê xe trước,
rồi đặt xuống sàn để kiểm tra thân xe có thực sự trượt ngang. Nếu xe xoay hoặc
đi chéo, cần kiểm tra cách lắp con lăn, vị trí và chiều từng bánh, khả năng khởi
động ở PWM đang dùng. Chương trình chưa đo quãng đường hoặc giữ hướng bằng cảm biến,
nên bánh trượt, tải và mặt sàn có thể làm xe lệch hướng.

Có thể ghép với tiến/lùi, xoay và nghỉ:

```text
tien 0.5 0.3
ngung 1
ngang_trai 0.5 0.3
ngung 1
ngang_phai 0.5 0.3
chay
```

`dung` xóa kịch bản đang soạn; khi đang chạy, nhấn **Ctrl+C** để yêu cầu dừng
và thoát. Hết đầu vào hoặc `thoat` không tự chạy các lệnh còn chờ.

## Chạy chéo 45 độ theo bốn hướng

Các lệnh `tren_trai`, `tren_phai`, `duoi_trai`, `duoi_phai`
yêu cầu xe dịch chéo theo hướng thân xe, giữ hướng đầu xe. Nhìn từ trên xuống,
trục x hướng phải, trục y hướng đầu xe. Góc được tính từ trục x; đây là góc
hướng dịch chuyển. `Trên` là về phía đầu xe, `dưới` là về phía sau xe.

Theo bảng và công thức trong [How a Mecanum Drive Works của Seamonsters 2605](https://seamonsters-2605.github.io/archive/mecanum/):

```text
FR = RL = sin(góc - π/4) × PWM
FL = RR = sin(góc + π/4) × PWM
```

| Lệnh | Góc | FR | FL | RL | RR |
| --- | --- | --- | --- | --- | --- |
| `tren_trai` | 3π/4 = 135° | Tiến | 0 | Tiến | 0 |
| `tren_phai` | π/4 = 45° | 0 | Tiến | 0 | Tiến |
| `duoi_trai` | −3π/4 = −135° | 0 | Lùi | 0 | Lùi |
| `duoi_phai` | −π/4 = −45° | Lùi | 0 | Lùi | 0 |

Mỗi lệnh dùng cùng PWM yêu cầu cho hai bánh hoạt động, sau đó bù riêng theo
`WHEEL_GAIN`. Hai bánh ghi `0` có cả PWM,
IN1 và IN2 bằng 0. Trạng thái thả trôi hoặc hãm phụ thuộc driver thực tế.
`inverted` vẫn áp dụng cho các bánh hoạt động để giữ đúng chiều vật lý.
Góc −3π/4 tương đương 5π/4; góc −π/4 tương đương 7π/4 trong bảng nguồn.

Chạy chương trình rồi thử riêng từng hướng. Ví dụ trên phải:

```text
tren_phai 0.5 0.3
chay
```

Lệnh trên chạy chéo trên phải 0,5 giây ở PWM 30% rồi yêu cầu dừng.
Thay tên lệnh bằng `duoi_trai` hoặc `duoi_phai` để thử hai hướng lùi.
Bỏ PWM thì dùng `DEFAULT_SPEED`, hiện là 50%. Enter chỉ lưu lệnh;
có thể ghép với tiến/lùi, ngang, quay và nghỉ. Dùng `dung` để xóa kịch bản
chưa chạy; Ctrl+C yêu cầu dừng và thoát khi đang thực hiện.

Thử mô phỏng từ thư mục gốc:

```sh
python -m vehicle_testing.main --dry-run --verbose
```

Thời gian cấp PWM chưa bao gồm hai khoảng chờ đổi chiều theo
`DIRECTION_CHANGE_DELAY_SECONDS`. Phần mềm chưa đo hướng hoặc quãng đường;
kết quả test không xác nhận xe thực tế đi đúng 45°. Cần kiểm tra chiều bánh
khi kê xe và hướng dịch chuyển trên sàn, với kiểu lắp Mecanum dạng X phù hợp.
Người dùng đã xác nhận hướng trên trái chạy ổn trên xe. Ba hướng mới còn cần
kiểm tra thực tế; xác nhận này chưa phải phép đo góc chính xác.

## Quay trái/phải tại chỗ bằng bánh Mecanum

Nhập `trai <độ>` hoặc `phai <độ>`, sau đó nhập `chay`. Ví dụ thử riêng
từng chiều trước, quan sát xe rồi mới soạn kịch bản kết hợp:

```text
trai 15
chay
```

```text
phai 15
chay
```

Góc là góc đổi hướng của **thân xe**, nhìn từ trên xuống; trái là ngược chiều
kim đồng hồ, phải là cùng chiều kim đồng hồ. Xe xoay tại chỗ, không phải trượt ngang.
Với chiều tiến vật lý đã xác nhận cho từng bánh:

| Lệnh | FR | FL | RL | RR |
| --- | --- | --- | --- | --- |
| `trai` | Tiến | Lùi | Lùi | Tiến |
| `phai` | Lùi | Tiến | Tiến | Lùi |

Lệnh quay dùng **PWM cố định theo `TURN_SPEED` trong `config.py`**, độc lập với PWM của
lệnh tiến/lùi/chạy ngang. Không nhập PWM riêng: `trai 90 0.5` bị từ chối để tránh dùng hệ số
hiệu chỉnh ở sai mức PWM. Góc phải dương và hữu hạn; chấp nhận số thập phân như
`trai 15.5`, từ chối `0`, số âm, `nan` và `inf`.

Đây là điều khiển theo thời gian, **chưa đọc encoder hoặc cảm biến góc**:

```text
thời gian chạy motor = góc yêu cầu × hệ số giây/độ
```

Hai hệ số trong `config.py` ban đầu tham khảo source cũ là `0.0133`.
Cấu hình hiện tại đã được thay đổi thành:

```python
TURN_SPEED = 0.5
TURN_LEFT_SECONDS_PER_DEGREE = 0.0179
TURN_RIGHT_SECONDS_PER_DEGREE = 0.0179
```

Với cấu hình trên, yêu cầu 90° sẽ cấp PWM khoảng 1,611 giây, không đảm bảo thân xe quay đúng
90°. Xác nhận chiều quay với xung ngắn trước; sau đó đặt xe trên mặt sàn sử dụng,
đánh dấu hướng ban đầu và đo góc sau khi xe dừng. Hiệu chỉnh riêng từng chiều:

```text
hệ số mới = hệ số cũ × góc yêu cầu / góc thực tế đo được
```

Ví dụ minh họa với hệ số cũ `0.0133`: yêu cầu quay trái 90° nhưng đo được 75°:
`TURN_LEFT_SECONDS_PER_DEGREE = 0.0133 × 90 / 75 = 0.01596`.
Đo lặp lại và kiểm tra thêm các góc 15°, 45°, 90°. Nếu bánh không khởi động hoặc
góc đo bằng 0, kiểm tra chuyển động trước, không áp dụng phép chia trên.
Đổi `TURN_SPEED`, tải, mặt sàn hoặc tình trạng pin có thể cần hiệu chỉnh lại.
Góc nhỏ dễ bị ảnh hưởng bởi thời gian khởi động và quán tính; một hệ số tuyến tính
không đảm bảo chính xác ở mọi góc. Nếu cần độ chính xác cao hơn, cần bổ sung phản hồi góc.

Các lệnh có thể kết hợp và vẫn chỉ chạy sau `chay`:

```text
tien 0.5 0.3
ngung 1
trai 15
ngung 1
phai 15
ngung 1
lui 0.5 0.3
chay
```

`ngung` là khoảng nghỉ tùy chọn. Khi đang chạy, **Ctrl+C** yêu cầu dừng motor
và thoát; lệnh `dung` dùng lúc đang soạn để xóa danh sách. Thử chiều quay khi kê
bánh giúp kiểm tra tín hiệu, nhưng hiệu chỉnh góc phải thực hiện khi xe tiếp xúc mặt sàn.

## Kiểm tra và hiệu chỉnh phần cứng

Bảng dưới lấy nguyên từ file thử ban đầu, chưa được xác minh bằng sơ đồ bo
Edison Academy Rev1.1 hoặc thử nghiệm phần cứng trong lần triển khai này:

| Tên | Vị trí theo file gốc | PWM | IN1 | IN2 |
| --- | --- | --- | --- | --- |
| FR | Trước phải / M1 | 0 | 2 | 1 |
| FL | Trước trái / M2 | 6 | 4 | 5 |
| RL | Sau trái / M3 | 15 | 14 | 13 |
| RR | Sau phải / M4 | 9 | 10 | 11 |

Đây là **kênh PCA9685**, không phải số chân GPIO. Đối chiếu bảng và vị trí bánh
bằng file thử từng bánh trước khi dùng chương trình chạy cả nhóm. Lần thử cả
nhóm đầu tiên nên kê bánh khỏi mặt đất, dùng thời gian ngắn, ví dụ nhập
`tien 0.5 0.3`, sau đó nhập `chay` để thực hiện.
PWM thấp có thể chưa đủ làm động cơ khởi động.

Mặc định mọi bánh dùng IN1 HIGH / IN2 LOW cho chiều tiến, giống file gốc.
Nếu một bánh quay ngược chiều tiến vật lý, sửa riêng bánh đó trong `config.py`:

```python
"FR": MotorPins(pwm=0, in1=2, in2=1, inverted=True),
```

Không thay số kênh chỉ để đảo chiều. Bảng cấu hình được kiểm tra để từ chối
các kênh trùng nhau hoặc ngoài khoảng 0–15.

Khi đổi chiều, bộ điều khiển đưa PWM của cả nhóm về 0, chờ ngắn, đặt chiều
cho cả nhóm rồi mới cấp PWM. Các lệnh I²C vẫn được ghi lần lượt, không phải
các bánh bật đồng thời tuyệt đối. Khi dừng, chương trình thử ghi tất cả các
kênh động cơ ngay cả khi một kênh báo lỗi; các kênh khác trên PCA9685 được giữ nguyên.

Lệnh dừng chỉ là yêu cầu gửi qua I²C, không xác nhận bánh đã đứng yên. Lỗi bus,
mất nguồn, kết thúc tiến trình cưỡng bức hoặc lỗi phần cứng có thể ngăn việc
gửi lệnh dừng. Chương trình chưa đọc encoder hoặc có cơ chế dừng phần cứng độc lập.

## Kiểm tra phần mềm

```sh
python -m unittest discover -s vehicle_testing/tests -v
```

Các bài kiểm tra dùng bộ ghi đầu ra trong bộ nhớ, không kết nối I²C hoặc GPIO thật.
Chúng kiểm tra bốn bánh cùng được cấp PWM ở các lệnh cũ, chỉ FR/RL được cấp PWM
khi đi hướng trên trái/dưới phải hoặc FL/RR khi đi hướng trên phải/dưới trái,
đảo chiều, mặc định PWM, nghỉ với đầu ra motor bằng 0, tiếp tục sau khoảng nghỉ,
ngắt trong lúc nghỉ, lưu lệnh trước khi `chay`, thứ tự kịch bản, không chạy lại
kịch bản cũ, hủy kịch bản, đầu vào không hợp lệ, lỗi ghi giữa chừng và dừng khi bị ngắt.
Kết quả này không thay thế kiểm tra trên xe thực tế.

## Mở rộng

Giao diện khác có thể sử dụng lại bộ điều khiển mà không đọc lệnh terminal:

```python
from vehicle_testing.hardware.motors import MotorController, PCA9685Output

controller = MotorController(PCA9685Output())
try:
    controller.move(direction="forward", seconds=2)  # PWM mặc định 50%
    controller.pause(seconds=0.5)
    controller.move(direction="backward", seconds=1, speed=0.3)
    controller.strafe(direction="left", seconds=0.5, speed=0.3)
    controller.strafe(direction="right", seconds=0.5)  # PWM mặc định 50%
    controller.move_forward_left(seconds=0.5, speed=0.3)  # Trên trái 3π/4
    controller.move_forward_right(seconds=0.5, speed=0.3)  # Trên phải π/4
    controller.move_backward_left(seconds=0.5, speed=0.3)  # Dưới trái −3π/4
    controller.move_backward_right(seconds=0.5, speed=0.3)  # Dưới phải −π/4
    controller.turn_left(angle=15)   # Góc ước lượng, PWM cố định TURN_SPEED
    controller.turn_right(angle=15)
finally:
    controller.close()
```

Sau này thêm hành vi vào `MotorController`, hoặc thêm giao diện mới gọi nó.
Nếu bổ sung API/điều khiển mạng, cần bảo đảm chỉ một lệnh sở hữu quyền điều
khiển motor tại một thời điểm; bộ điều khiển hiện tại được thiết kế cho một
phiên chạy tuần tự.
