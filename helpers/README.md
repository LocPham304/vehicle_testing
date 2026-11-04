# ConvertBlockToPython

Bộ chuyển đổi chính nằm trong `ConvertBlockToPython.py`. File `convert.py` ở gốc
chỉ gọi lại module này; không còn hai bản logic độc lập.

Helper đọc chuỗi `report_block(...)` / `robot.sendCmd("tên:giá_trị")`, kiểm tra
rồi sinh Python gọi `robot_sdk.Robot`. Chuyển đổi và lưu file không thực thi mã,
không import thư viện phần cứng và không mở GPIO/I²C.

## Gọi từ Python

Từ thư mục gốc `C:\Project\SIGINX\stem`:

```python
from vehicle_testing.helpers.ConvertBlockToPython import ConvertBlockToPython

source = ('report_block("block-1") robot.sendCmd("move_forward:2")\n'
          'report_block("block-2") robot.sendCmd("hand_up:90")')
helper = ConvertBlockToPython()
python_code = helper.convert(source)  # Mặc định giữ toàn bộ ID block.
print(python_code)
```

Nội dung chính của mã sinh ra:

```python
from robot_sdk import Robot

REQUIRED_RESOURCES = ('motor', 'hand')

robot = Robot()
try:
    robot.report_block('block-1')
    robot.move_forward(2.0)
    robot.report_block('block-2')
    robot.hand_up(90.0)
finally:
    robot.stop()
```

`REQUIRED_RESOURCES` là thông tin phân nhóm cho agent/SDK; chưa tự chọn hoặc mở
thiết bị. SDK thử nghiệm hiện có ở `vehicle_testing/robot_sdk.py`; worker của
receiver Python cung cấp import `robot_sdk` cho mã đã sinh. Xem
[bài thử MQTT](../docs/MQTT_PYTHON_TEST.md) để chạy với mô phỏng hoặc phần cứng.
SDK dùng cùng tên hàm và đơn vị với bảng lệnh. Đoạn Python sinh ra
khởi tạo `Robot` khi được thực thi/import; converter không tự thực hiện bước đó.

## Lưu file và CLI

```python
output = helper.convert_file("source.txt", "program.py")
# Nếu cần bỏ ID:
python_code = helper.convert(source, keep_block_ids=False)
```

Từ thư mục gốc `stem`:

```powershell
python -m vehicle_testing.helpers.ConvertBlockToPython --input vehicle_testing/examples/scratch_sample.txt --output vehicle_testing/examples/converted_sample.py
```

Cách gọi qua file gốc cũng dùng đúng bộ chuyển đổi này:

```powershell
python convert.py --input vehicle_testing/examples/scratch_sample.txt --output vehicle_testing/examples/converted_sample.py
```

Thêm `--drop-block-ids` để bỏ sự kiện block. CLI chỉ sinh file, không chạy robot.
Mã đầu ra mới không còn template driver cũ có `--dry-run`. Kiểm thử dùng SDK giả
trong `tests/test_convert_block_to_python.py`, không điều khiển phần cứng.

Hàm độc lập `convert_block_to_python(source, keep_block_ids=False)` vẫn giữ mặc
định của bản `convert.py` ban đầu. Class `.convert()` / `.convert_file()` và CLI
mặc định giữ ID, tương ứng hành vi helper trước đó.

## Khai báo block mới

Chỉ sửa hai bảng trong `ConvertBlockToPython.py`, ví dụ lệnh đã hỗ trợ:

```python
COMMANDS = {
    # ...
    "hand_up": _number(0, 90),
}
COMMAND_RESOURCES = {
    # ...
    "hand_up": "hand",
}
```

Generator FE gửi `robot.sendCmd("hand_up:90")`. SDK nhận `robot.hand_up(90.0)`;
SDK cần ánh xạ tiếp sang `HandController.hand_up(angle=degrees)`, không truyền
90 vào vị trí tham số thời gian của driver. Đổi tên hiển thị block không ảnh
hưởng converter nếu tên lệnh FE sinh vẫn khớp.

| Lệnh | Tham số | Nhóm |
| --- | --- | --- |
| move_forward, move_backward | Giây, > 0 và <= 500 | motor |
| turn_left, turn_right | Độ yêu cầu, > 0 và <= 360 | motor |
| hand_up | Góc đích tuyệt đối 0–90°, không phải góc tăng thêm | hand |
| led_strip | Chuỗi tối đa 64 ký tự, cho phép rỗng | matrix |
| stop | Không tham số (`stop` hoặc `stop:`) | Không yêu cầu thiết bị mới |

`parse_commands(..., keep_block_ids=True)` trả `Command` và `BlockMarker` theo
đúng thứ tự. `Command.resource` cho biết nhóm; `get_required_resources(events)`
trả các nhóm có dùng, không trùng lặp. Marker đứng riêng cũng được giữ.

## Phạm vi

- Chấp nhận lệnh dính dòng, comment, CRLF, lề thừa và literal tiếng Việt.
- Giữ nội dung chuỗi, kể cả ký tự phân dòng Unicode và lề trong literal nhiều dòng.
- Chỉ nhận hai loại lời gọi cố định; không thực thi import, biểu thức, if/for.
- Giới hạn nguồn 64 KiB, 1.000 câu lệnh; lỗi báo theo dòng gốc.
- Từ chối lệnh chưa khai báo hoặc thiếu nhóm thiết bị, giá trị sai giới hạn.
- File nguồn UTF-8/BOM được đọc đúng; không cho ghi đè chính file đầu vào.
- Bản thân converter không nghe MQTT/WebSocket. Đường MQTT thử nghiệm dùng
  `connections/mqtt/python_receiver.py`, worker và SDK riêng; các receiver cũ
  chưa chuyển sang đường chạy này. `try/finally` không thay thế cơ chế Stop/timeout
  và không bảo đảm dọn phần cứng sau SIGKILL/mất điện.
