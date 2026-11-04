# Thử FE → backend → MQTT → convert → Python → robot

Đây là đường thử riêng trong `vehicle_testing`, chưa thay firmware chính thức.
Receiver cũ vẫn chạy parser/runner cũ; bài thử này dùng **python_receiver**.

```text
FE Upload Code
  → API backend → device/<UUID>/code (chuỗi FE UTF-8)
  → ConvertBlockToPython → lưu .fe.txt và .py → báo uploaded
FE Chạy Code
  → API backend → device/<UUID>/execute (payload execute)
  → tiến trình Python riêng → robot_sdk → driver
  → executing → block/log → done, stopped hoặc error
```

## 1. Chuẩn bị

- Chép source `vehicle_testing` mới lên Pi. Dùng Python 3.10+; kiểm thử trên máy
  phát triển dùng 3.11.9. Không cần file `convert.py` ở gốc để chạy receiver.
- Dùng đúng **broker của backend** và UUID của robot đang chọn trong FE. Nếu BE
  dùng `tcp://localhost:1883`, Pi cần IP LAN của máy chạy broker, không phải
  `localhost` của Pi. Cổng mặc định 1883; hai bên phải truy cập cùng broker.
- Tắt receiver/firmware cũ đang nghe cùng UUID trước khi thử. Hai receiver cùng
  nhận một lệnh có thể gây điều khiển trùng. Không chạy chung với chương trình
  terminal khác đang sở hữu motor/GPIO.
- Giữ nguyên source FE/BE. Listener trạng thái BE hiện đọc UUID từ `parts[2]`
  (chuỗi `status`) thay vì `parts[1]` trong topic `device/<UUID>/status`. Đây là
  ghi nhận ngoài phạm vi chỉnh sửa: trạng thái trên FE có thể không cập nhật.
  Dùng log receiver trên Pi và topic MQTT để xác nhận bài thử, không coi thông
  báo HTTP thành công hoặc trạng thái FE là bằng chứng xe đã chạy.

Các lệnh dưới đây chạy từ thư mục **chứa `vehicle_testing`**, ví dụ `/home/pi/stem`.
Kích hoạt môi trường Python đang dùng trên Pi. Nếu tạo môi trường mới:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r vehicle_testing/requirements-mqtt.txt
```

Chỉ cài thư viện phần cứng trên Pi khi chuyển sang thử thật:

```bash
python3 -m pip install -r vehicle_testing/requirements.txt
```

## 2. Mở receiver ở chế độ mô phỏng

Thay `IP_BROKER_CUA_BE` và `UUID_ROBOT_TREN_FE` bằng giá trị thật:

```bash
python3 -m vehicle_testing.connections.mqtt.python_receiver --broker IP_BROKER_CUA_BE --device-id UUID_ROBOT_TREN_FE --dry-run
```

Mặc định không có `--run` cũng là mô phỏng. Giữ terminal mở, chờ log kết nối và
subscribe thành công. Chế độ này chạy file Python thật với SDK mô phỏng; không
mở GPIO/I²C và bỏ thời gian chờ của các hành động.

Cũng có thể chạy trực tiếp ngay trong thư mục chứa file, ví dụ trên Pi:

```bash
cd /home/pi/vehicle_testing/connections/mqtt
python3 python_receiver.py --broker IP_BROKER_CUA_BE --device-id UUID_ROBOT_TREN_FE --dry-run
```

Receiver tự xác định thư mục package từ vị trí file. Không cần đặt `PYTHONPATH`
hoặc đổi môi trường `.venv`. Cách chạy `python3 -m ...` từ thư mục cha vẫn giữ nguyên.

## 3. Thao tác trên FE

1. Mở project, chọn đúng robot và kênh **MQTT**.
2. Tạo chương trình đầu tiên chỉ gồm **Bắt đầu → tiến 0,5 giây**. Có thể thêm
   block Stop nếu FE đã định nghĩa; `finally: robot.stop()` cũng dọn thiết bị khi
   chương trình kết thúc. Không thử quay hoặc nâng tay trong lần kiểm tra bánh đầu.
3. Bấm **Xem code**: phải thấy `robot.sendCmd("move_forward:0.5")`. Nhãn FE nếu
   còn ghi cm cần sửa sau; hợp đồng hiện tại của giá trị này là **giây**.
4. Bấm **Upload Code**. Pi phải ghi `CONVERT OK`, đường dẫn `.py`, rồi `UPLOADED`.
   Upload **không chạy xe**. Đừng chỉ dựa vào thông báo HTTP thành công trên FE.
5. Xem `vehicle_testing/received_programs/<id>.fe.txt` và `<id>.py`: bản đầu là
   source FE, bản sau phải gọi `robot.move_forward(0.5)`.
6. Bấm **Chạy Code**. Pi phải in `SDK MODE: MO PHONG`, ID block, lệnh tiến và
   `EXECUTE ket thuc: done`. Mỗi upload chỉ được chạy một lần; muốn chạy lại phải
   Upload Code lại. MQTT hiện chạy bản đã upload, không tự lấy bản FE vừa sửa.

Chương trình mẫu để đối chiếu: `examples/mqtt_python_smoke.txt`.

## 4. Chuyển sang thử xe thật

Sau khi mô phỏng đã qua, nhấn `Ctrl+C` đóng receiver mô phỏng. Trong lần thử đầu,
đặt xe vững, kê bánh khỏi mặt sàn để xác nhận chiều quay, dây và kênh motor.
Mở lại với cùng broker/UUID:

```bash
python3 -m vehicle_testing.connections.mqtt.python_receiver --broker IP_BROKER_CUA_BE --device-id UUID_ROBOT_TREN_FE --run --speed 0.25 --timeout 10
```

Trên FE **Upload Code lại**, kiểm tra Pi báo nhận, rồi **Chạy Code**. `--speed`
là PWM tiến/lùi (0.25 = 25%), không phải RPM đo được; không thay hệ số/tốc độ quay
trong config. Với động cơ/tải cụ thể, mức này có thể chưa đủ để bánh quay.
Thời gian tổng chương trình còn có các khoảng chờ đổi chiều của driver.

Chạy thật dùng driver có sẵn: PCA9685 cho bánh, BCM18 cho tay nâng, TM1640 cho
ma trận. Không đổi wiring, mốc xung hay bảng chiều bánh. Góc quay/nâng là giá trị
yêu cầu, chưa được bài thử phần mềm xác nhận là góc cơ khí thực tế.

## 5. Dừng

Mặc định `--run` **không nhận chương trình có `hand_up`**. Mỗi tiến trình con mới
giả định tay bắt đầu ở vị trí hạ; không biết vị trí thật do lượt trước để lại.
Nếu thử nâng sau này, đóng receiver, đặt tay về vị trí hạ đã quy ước rồi mở lại
với `--run --lift-start-lowered`. Mỗi lần mở receiver chỉ cho **một lượt chương
trình có tay nâng**; muốn chạy lượt nâng tiếp theo phải đặt lại vị trí và mở lại.
Mô phỏng không cần cờ này. Không dùng cờ để bỏ qua việc đặt vị trí ban đầu.

- `Ctrl+C` trong terminal receiver trên Pi: yêu cầu chương trình con dừng, chờ dọn
  thiết bị rồi đóng MQTT.
- Hoặc publish payload `stop` tới `device/<UUID>/stop` với `retain=False`.
  Ví dụ nếu có `mosquitto_pub`:

  ```bash
  mosquitto_pub -h IP_BROKER_CUA_BE -t device/UUID_ROBOT_TREN_FE/stop -m stop -q 1
  ```

**Nút đỏ hiện tại trên FE chỉ dừng simulator**, chưa gửi MQTT Stop. Trong bài thử
này giữ terminal Pi sẵn để dùng Ctrl+C. Khi chưa xác nhận dừng phần cứng, không
dựa vào việc đóng trang FE; có thể cần ngắt nguồn motor.

Receiver mặc định giới hạn mỗi lượt 30 giây (`--timeout`). Hủy hợp tác bằng file
Stop; nếu con không thoát sẽ gửi SIGTERM. Trường hợp buộc kill, receiver chặn
upload mới và yêu cầu kiểm tra phần cứng trước khi khởi động lại. Việc kill tiến
trình không tự chứng minh PWM đã về 0. Lỗi dọn thiết bị từ SDK cũng chặn
upload tiếp theo, không chỉ trường hợp buộc kill.

## 6. Phản hồi và giới hạn của bài thử

- `device/<UUID>/status`: uploaded, executing, done, stopped, error; heartbeat idle.
- `device/<UUID>/block`: JSON có block_id, program_id, status, timestamp.
- `device/<UUID>/log`: JSON log của chương trình con.
- Lệnh retained hoặc có cờ MQTT `dup` bị bỏ qua; upload lỗi không dùng lại bản cũ. Đang chạy thì
  không nhận upload mới. Mất kết nối broker sẽ yêu cầu dừng và bỏ bản chờ.
- SDK hiện chỉ nhận các API trong bảng converter. Không nhận Python tùy ý từ
  FE và không phải sandbox cách ly quyền truy cập.
- Test tự động đã có với broker loopback và SDK mô phỏng. Chúng không thay việc
  xác minh FE/backend đang triển khai, mạng LAN, dịch vụ trên Pi và chuyển động.

Test Python từ thư mục gốc:

```bash
python3 -m unittest vehicle_testing.tests.test_python_mqtt_pipeline vehicle_testing.tests.test_python_mqtt_integration -v
```

Không yêu cầu sửa hay build lại FE/BE cho đường thử này. Nếu robot không hiện
trong danh sách FE do cơ chế trạng thái, cần xử lý ngoài bài thử; receiver không
tự sửa dữ liệu backend hoặc giả mạo UUID để vượt qua việc chọn robot.
