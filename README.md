# Điều khiển robot tiến/lùi theo thời gian

Chương trình Python dựa trên `pi4-source/test-banh-xe.py`, dùng thư viện
Adafruit để điều khiển PCA9685. Nhập lệnh ở terminal để chạy cả bốn bánh
theo thời gian: soạn các dòng lệnh trước, gõ `chay` để thực hiện kịch bản,
rồi gửi lệnh dừng sau từng chuyển động. Không đo quãng đường hoặc tốc độ thực tế.

## Cấu trúc

| File | Trách nhiệm |
| --- | --- |
| `config.py` | Địa chỉ I²C, tần số PWM, PWM mặc định, kênh và chiều của từng động cơ |
| `controller.py` | Xuất tín hiệu, chạy nhóm bánh, dừng và giải phóng kết nối |
| `main.py` | Nhận và kiểm tra lệnh terminal, quản lý phiên chạy |
| `tests/test_robot.py` | Kiểm tra luồng điều khiển qua đầu ra giả lập và CLI |

Các lệnh dưới đây chạy từ thư mục gốc `raspberry-py`, dùng Python 3.10 trở lên.

## Thử trên máy tính, không cần Raspberry Pi

```sh
python stem_project/main.py --dry-run
```

Không cần cài thư viện phần cứng cho chế độ này. Thời gian chờ vẫn diễn ra
đúng theo lệnh để dễ quan sát luồng chạy. Thêm `--verbose` để xem các kênh:

```sh
python stem_project/main.py --dry-run --verbose
```

## Chạy trên Raspberry Pi

Bật I²C trên Raspberry Pi và dùng môi trường Python có hỗ trợ Adafruit Blinka.
Ví dụ tạo môi trường riêng trên Raspberry Pi OS:

```sh
python3 -m venv --system-site-packages stem_project/.venv
source stem_project/.venv/bin/activate
python -m pip install -r stem_project/requirements.txt
python stem_project/main.py
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

**Enter sau mỗi dòng `tien`/`lui`/`ngung` chỉ lưu lệnh, xe chưa chạy.** Chương trình
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

Thứ tự tham số là **chiều → số giây → PWM tùy chọn**. Mỗi lần bỏ trống PWM đều
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
python -m unittest discover -s stem_project/tests -v
```

Các bài kiểm tra dùng bộ ghi đầu ra trong bộ nhớ, không kết nối I²C.
Chúng kiểm tra bốn bánh cùng được cấp PWM, đảo chiều, hiệu chỉnh riêng từng
bánh, mặc định PWM, nghỉ với đầu ra motor bằng 0, tiếp tục sau khoảng nghỉ,
ngắt trong lúc nghỉ, lưu lệnh trước khi `chay`, thứ tự kịch bản, không chạy lại
kịch bản cũ, hủy kịch bản, đầu vào không hợp lệ, lỗi ghi giữa chừng và dừng khi bị ngắt.
Kết quả này không thay thế kiểm tra trên xe thực tế.

## Mở rộng

Giao diện khác có thể sử dụng lại bộ điều khiển mà không đọc lệnh terminal:

```python
from stem_project.controller import MotorController, PCA9685Output

controller = MotorController(PCA9685Output())
try:
    controller.move(direction="forward", seconds=2)  # PWM mặc định 50%
    controller.pause(seconds=0.5)
    controller.move(direction="backward", seconds=1, speed=0.3)
finally:
    controller.close()
```

Sau này thêm hành vi vào `MotorController`, hoặc thêm giao diện mới gọi nó.
Nếu bổ sung API/điều khiển mạng, cần bảo đảm chỉ một lệnh sở hữu quyền điều
khiển motor tại một thời điểm; bộ điều khiển hiện tại được thiết kế cho một
phiên chạy tuần tự.
