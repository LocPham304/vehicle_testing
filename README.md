# Điều khiển robot tiến/lùi, chạy ngang và quay Mecanum

Chương trình Python dựa trên `pi4-source/test-banh-xe.py`, dùng thư viện
Adafruit để điều khiển PCA9685. Nhập lệnh ở terminal để chạy cả bốn bánh
tiến/lùi hoặc trượt ngang theo thời gian, cùng lệnh quay tại chỗ theo góc ước lượng:
soạn các dòng lệnh trước, gõ `chay` để thực hiện kịch bản,
rồi gửi lệnh dừng sau từng chuyển động. Không đo quãng đường hoặc tốc độ thực tế.

## Cấu trúc

| File | Trách nhiệm |
| --- | --- |
| `config.py` | Địa chỉ I²C, tần số PWM, PWM mặc định, kênh và chiều của từng động cơ |
| `controller.py` | Xuất tín hiệu, chạy nhóm bánh, dừng và giải phóng kết nối |
| `main.py` | Nhận và kiểm tra lệnh terminal, quản lý phiên chạy |
| `tests/test_robot.py` | Kiểm tra luồng điều khiển qua đầu ra giả lập và CLI |
| `tests/test_turning.py` | Kiểm tra chiều quay Mecanum, hiệu chỉnh góc, dừng và kịch bản có lệnh quay |
| `tests/test_strafing.py` | Kiểm tra chiều chạy ngang, PWM, xếp lệnh và dừng khi lỗi hoặc bị ngắt |
| `tests/test_strafe_calibration.py` | Kiểm tra bù PWM riêng từng bánh, cấu hình sai và giữ nguyên các chế độ khác |

Các lệnh dưới đây chạy từ thư mục gốc `raspberry-py`, dùng Python 3.10 trở lên.

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
python3 -m venv --system-site-packages vehicle_testing/.venv
source vehicle_testing/.venv/bin/activate
python -m pip install -r vehicle_testing/requirements.txt
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

Mặc định cả bốn bánh được cấp cùng mức PWM; phần hiệu chỉnh bên dưới cho phép
giảm riêng từng bánh trong chế độ chạy ngang. Kiểm tra chiều từng bánh khi kê xe trước,
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

### Hiệu chỉnh PWM riêng cho chạy ngang

Video thực tế cho thấy xe dịch ngang kèm lệch dọc và thay đổi hướng thân xe.
Người vận hành đã xác nhận các bánh đều tạo lực, con lăn quay tự do và bốn bánh
tiếp xúc sàn đều. Những điều này chưa xác nhận tốc độ từng bánh bằng nhau.

Trong `config.py` có hai bảng hiệu chỉnh độc lập:

```python
STRAFE_LEFT_GAINS = {"FR": 1.0, "FL": 1.0, "RL": 1.0, "RR": 1.0}
STRAFE_RIGHT_GAINS = {"FR": 1.0, "FL": 1.0, "RL": 1.0, "RR": 1.0}
```

Đây là **giá trị trung tính**, không phải bộ hệ số đã đo trên xe. Khi tất cả bằng
`1.0`, tín hiệu đầu ra giữ nguyên như bản trước. Công thức:

```text
PWM từng bánh = PWM của lệnh × hệ số của bánh trong bảng tương ứng
```

Ví dụ `ngang_trai 3 0.5` với hệ số FR bằng `0.95` sẽ cấp FR 47,5%, các bánh có
hệ số `1.0` vẫn nhận 50%. Log `PWM tung banh (sau hieu chinh)` hiển thị mức PWM
yêu cầu sau tính toán; đây không phải tốc độ thực đo bằng encoder.

Hệ số phải là số hữu hạn trong `(0, 1]`, đủ đúng bốn tên `FR/FL/RL/RR`.
Thiếu/thừa tên, số âm, `0`, `nan`, `inf`, chuỗi, boolean hoặc hệ số lớn hơn `1`
đều bị từ chối trước khi ghi đầu ra chuyển động. Chỉ cho giảm PWM của bánh mạnh
hơn, không tăng vượt PWM lệnh. Nếu giảm làm bánh không khởi động, khôi phục giá
trị trước đó và đánh giá lại thay vì tiếp tục giảm.

Chỉ lệnh ngang sử dụng các hệ số này. Tiến/lùi và quay tại chỗ vẫn dùng đúng PWM
cũ, kể cả khi bảng hiệu chỉnh ngang bị nhập sai. Chiều quay và `inverted` của từng
bánh được giữ nguyên; cơ chế dừng khi lỗi/Ctrl+C vẫn áp dụng.

Quy trình hiệu chỉnh trên mặt sàn:

1. Giữ nguyên PWM lệnh (ví dụ `0.5`), tải và mặt sàn. Đánh dấu hướng đầu xe,
   vị trí xuất phát; quay từ vị trí cố định thấy đường ron gạch.
2. Bắt đầu với hệ số `1.0`. Thay một nhóm bánh mỗi lần, bước nhỏ khoảng 2–5%.
   Thử ngắn trước, rồi chạy `ngang_trai 3 0.5` để so sánh độ lệch và hướng thân xe.
3. Sửa ngay `config.py` trên Pi đang chạy, hoặc chép lại file đã sửa từ máy tính.
   **Thoát và khởi động lại chương trình** sau mỗi lần sửa để nạp hệ số mới.
4. Giữ thay đổi nếu sai lệch giảm lặp lại qua vài lần thử; nếu sai lệch tăng,
   khôi phục giá trị trước đó. Lưu lại từng bộ hệ số và kết quả.
5. Hiệu chỉnh thay đổi hướng thân xe trước, sau đó mới đánh giá lệch tiến/lùi.
   Hiệu chỉnh `STRAFE_RIGHT_GAINS` riêng cho chiều phải, không tự sao chép chiều trái.

Với `ngang_trai` và mô hình lắp bánh hiện tại, bảng dưới là **hướng thử theo mô hình**,
không phải kết luận đã đo được motor nào nhanh hơn:

| Quan sát | Nhóm có thể thử giảm cùng một lượng nhỏ |
| --- | --- |
| Thân xe xoay trái (ngược chiều kim đồng hồ nhìn từ trên) | FR và FL |
| Thân xe xoay phải | RL và RR |
| Hướng thân đã ổn định nhưng còn dịch về phía trước | FR và RL |
| Hướng thân đã ổn định nhưng còn dịch về phía sau | FL và RR |

Ví dụ thử giảm nhóm trước 5% khi thân xoay trái: đặt FR/FL bằng `0.95`, RL/RR
giữ `1.0` trong `STRAFE_LEFT_GAINS`, khởi động lại và so sánh cùng lệnh cũ.
Không áp dụng đồng thời nhiều dòng của bảng ngay lần đầu. Thay đổi có thể ảnh
hưởng lẫn nhau ngoài thực tế; nếu không cải thiện, cần đo vận tốc bánh và kiểm
tra lại mô hình/cơ khí. Đây là bù thủ công theo điều kiện thử, chưa phải giữ hướng
tự động bằng cảm biến và chưa xác nhận đã khắc phục sai lệch trên xe.

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

Các bài kiểm tra dùng bộ ghi đầu ra trong bộ nhớ, không kết nối I²C.
Chúng kiểm tra bốn bánh cùng được cấp PWM, đảo chiều, hiệu chỉnh riêng từng
bánh, mặc định PWM, nghỉ với đầu ra motor bằng 0, tiếp tục sau khoảng nghỉ,
ngắt trong lúc nghỉ, lưu lệnh trước khi `chay`, thứ tự kịch bản, không chạy lại
kịch bản cũ, hủy kịch bản, đầu vào không hợp lệ, lỗi ghi giữa chừng và dừng khi bị ngắt.
Kết quả này không thay thế kiểm tra trên xe thực tế.

## Mở rộng

Giao diện khác có thể sử dụng lại bộ điều khiển mà không đọc lệnh terminal:

```python
from vehicle_testing.controller import MotorController, PCA9685Output

controller = MotorController(PCA9685Output())
try:
    controller.move(direction="forward", seconds=2)  # PWM mặc định 50%
    controller.pause(seconds=0.5)
    controller.move(direction="backward", seconds=1, speed=0.3)
    controller.strafe(direction="left", seconds=0.5, speed=0.3)
    controller.strafe(direction="right", seconds=0.5)  # PWM mặc định 50%
    controller.turn_left(angle=15)   # Góc ước lượng, PWM cố định TURN_SPEED
    controller.turn_right(angle=15)
finally:
    controller.close()
```

Sau này thêm hành vi vào `MotorController`, hoặc thêm giao diện mới gọi nó.
Nếu bổ sung API/điều khiển mạng, cần bảo đảm chỉ một lệnh sở hữu quyền điều
khiển motor tại một thời điểm; bộ điều khiển hiện tại được thiết kế cho một
phiên chạy tuần tự.
