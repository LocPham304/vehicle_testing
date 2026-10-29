# Điều khiển qua Bluetooth Classic SPP

Code nằm trong `connections/bluetooth/`: `receiver.py` quản lý kết nối/phiên
chạy, `bluez.py` đăng ký dịch vụ với BlueZ, `client.py` là công cụ trên laptop.
Hai file gọi ở ngoài cùng là `bluetooth_receiver.py` và `bluetooth_client.py`.

```text
Laptop Windows → COM Bluetooth Outgoing → Bluetooth Classic SPP → Pi
                                                               → parser/session/runner
                                                               → motor và LED
```

Không cần Wi-Fi, IP, broker, Internet hoặc cáp USB để truyền lệnh. Pi và laptop
phải có Bluetooth đang hoạt động. Phần này dùng radio của Pi qua BlueZ, không
dùng module HC-05/ESP32 trên xe. Đây là SPP/RFCOMM, chưa triển khai BLE GATT.

Chỉ mở một receiver điều khiển phần cứng tại một thời điểm. Dừng receiver USB,
Wi-Fi và MQTT đang điều khiển motor/LED trước khi chuyển sang Bluetooth.

## 1. Cài trên Pi một lần

Trong terminal Pi, qua SSH hoặc console đang có:

```sh
sudo apt update
sudo apt install bluez python3-dbus python3-gi
sudo systemctl start bluetooth
```

Trong `vehicle_testing`, dùng venv đã có thư viện motor/LED:

```sh
cd ~/vehicle_testing
source .venv/bin/activate
python3 -c "import dbus; from gi.repository import GLib; print('BlueZ Python OK')"
```

Nếu venv không thấy `dbus`/`gi` dù apt đã cài, bật quyền dùng package hệ thống
cho venv hiện tại, rồi kích hoạt và kiểm tra lại:

```sh
deactivate
/usr/bin/python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python3 -c "import dbus; from gi.repository import GLib; print('BlueZ Python OK')"
```

Lệnh trên cập nhật venv hiện có, không dùng `--clear`. Nếu thiếu module `venv`,
cài `python3-venv` bằng apt. Không cài `dbus-python`/PyGObject trên Windows để
chạy client; hai thư viện đó chỉ phục vụ receiver Linux.

## 2. Bật radio và mở cửa sổ ghép đôi trên Pi

Trong **terminal Pi thứ nhất**, chạy:

```sh
bluetoothctl
```

Trong dấu nhắc của `bluetoothctl`, nhập từng dòng:

```text
power on
agent DisplayYesNo
default-agent
pairable on
discoverable on
show
```

`show` cho biết tên/Alias và địa chỉ Bluetooth của Pi. Giữ terminal này mở để
xác nhận mã ghép đôi và yêu cầu truy cập dịch vụ khi Windows kết nối. Nếu báo
đã có agent, có thể dùng agent đang có; chạy `default-agent`.

Nếu radio bị khóa phần mềm, chạy `sudo rfkill unblock bluetooth` từ terminal
shell rồi thử `power on` lại. Nếu không có controller, xem `bluetoothctl list`,
`rfkill list` và `systemctl status bluetooth`; receiver sẽ báo lỗi khi không
có adapter hoặc adapter chưa bật. Chương trình không tự sửa cấu hình boot.

## 3. Mở receiver trên Pi

Trong **terminal Pi thứ hai**:

```sh
cd ~/vehicle_testing
source .venv/bin/activate
python3 bluetooth_receiver.py --dry-run
```

Giữ receiver mở. Khi log báo đã đăng ký SPP, dịch vụ `STEM Robot Serial` sẵn
sàng để Windows tìm thấy. Bluetooth Classic SPP dùng UUID chuẩn
`00001101-0000-1000-8000-00805f9b34fb`, kênh RFCOMM mặc định `3`.
Tên Pi trong danh sách ghép đôi là Alias ở bước 2; tên dịch vụ Serial không
nhất thiết là tên thiết bị đó.

Chế độ chạy giống các receiver hiện có:

| Câu lệnh trên Pi | Hành vi khi nhận `run` |
| --- | --- |
| `python3 bluetooth_receiver.py` | Preview: kiểm tra và in kịch bản |
| `python3 bluetooth_receiver.py --dry-run` | Runner mô phỏng, không phát tín hiệu motor/GPIO |
| `python3 bluetooth_receiver.py --run` | Runner điều khiển motor/LED thật |

## 4. Ghép đôi và chọn COM trên Windows

1. Bật Bluetooth trên laptop, vào Settings → Bluetooth & devices → Add device
   → Bluetooth, chọn Pi theo tên ở bước 2.
2. Xác nhận mã ghép đôi trên Windows và terminal `bluetoothctl` của Pi khi được
   hỏi. Nếu có yêu cầu cho phép dịch vụ Serial/SPP, xác nhận cho laptop đang thử.
3. Trên Pi, có thể dùng `devices`, rồi `info AA:BB:CC:DD:EE:FF` để kiểm tra
   `Paired: yes`. Thay địa chỉ bằng địa chỉ Bluetooth của **laptop**.
4. Để cho phép laptop này truy cập dịch vụ ở lần sau, trong `bluetoothctl` dùng
   `trust AA:BB:CC:DD:EE:FF`. Chỉ chọn đúng laptop bạn muốn điều khiển.
5. Trên Windows, xem Device Manager → Ports (COM & LPT), hoặc More Bluetooth
   settings → COM Ports. Dùng cổng **Outgoing** của Pi, ví dụ `COM8`. Nếu chưa
   được tạo, chọn Add → Outgoing, chọn Pi và dịch vụ Serial/SPP.

Cần giữ receiver mở khi Windows tìm dịch vụ. Nếu Pi đã được ghép đôi trước
khi receiver SPP được chạy và Windows chưa thấy dịch vụ, bật receiver, làm mới
dịch vụ hoặc gỡ riêng pairing Pi rồi ghép lại. Số COM tùy máy, không cố định.
Bluetooth đã Paired chưa có nghĩa là client đã mở kết nối Serial.

Sau khi ghép đôi xong, có thể `discoverable off` và `pairable off` trong
`bluetoothctl`. Laptop đã ghép đôi vẫn có thể kết nối lại. Nếu chưa đánh dấu
trusted, giữ agent sẵn sàng để xác nhận quyền dịch vụ khi được hỏi.

## 5. Gửi kịch bản từ laptop

Trong PowerShell tại thư mục `vehicle_testing` trên laptop:

```powershell
python -m pip install -r requirements-bluetooth.txt
python bluetooth_client.py
```

Danh sách đánh số COM có thể gồm cả thiết bị USB khác. Chọn **số thứ tự** ứng
với COM Outgoing Bluetooth của Pi. Ví dụ `1. COM8` thì nhập `1`.
Có thể mở thẳng cổng đã biết hoặc chỉ liệt kê cổng:

```powershell
python bluetooth_client.py --port COM8
python bluetooth_client.py --list
```

Sau khi thấy trạng thái Pi, nhập từng lệnh và Enter:

```text
bt> upload
bt> status
bt> run
bt> stop
bt> exit
```

- `upload`: gửi `examples/scratch_sample.txt` trên laptop; **không tự chạy**.
- `upload "C:\thu muc\kich-ban.txt"`: gửi một file UTF-8 khác.
- `status`: xem bản chờ, trạng thái và `mode: preview/dry-run/hardware`.
- `run`: thực hiện đúng kịch bản đã upload gần nhất hợp lệ.
- `stop`: yêu cầu hủy lượt đang chạy; có thể RUN lại bản chờ.
- `exit`: gửi stop và đóng COM; Pi xóa bản chờ sau khi ngắt kết nối/timeout.

`accepted` là nhận RUN; `executing` báo bắt đầu, `done` báo chạy xong. Các marker
`report_block` được trả về dưới dạng sự kiện `block` cùng `block_id`.
Trong `dry-run`, chuyển động không chờ đủ thời gian thực và xe đứng yên.

Muốn chạy phần cứng thật: `exit` client, Ctrl+C receiver, chạy receiver với
`--run`, rồi mở lại client, **upload lại** và RUN. Kiểm tra phản hồi có
`mode: hardware`. Khi đã ghép đôi/trusted, thường chỉ cần mở receiver và client;
không phải ghép đôi lại mỗi lần.

## 6. Ngắt kết nối và giới hạn

Client tự ping khoảng mỗi giây. Khi ngắt Bluetooth, đóng COM, mất luồng hoặc
không có yêu cầu hợp lệ trong 5 giây, receiver yêu cầu hủy runner và xóa bản
chờ. EOF đóng kết nối ngay; trường hợp radio/driver chưa báo ngắt dùng timeout.
Kết nối lại là phiên mới, cần upload lại; không tự RUN lại. Chỉ một kết nối
điều khiển được chấp nhận; kết nối khác bị từ chối đến khi phiên cũ dọn xong.

Nếu cần thời gian chờ dài hơn để thử đường truyền chậm, dùng chẳng hạn
`python3 bluetooth_receiver.py --dry-run --link-timeout 10`. Độ trễ dừng khi mất
liên lạc cũng tăng theo thông số này. Kênh RFCOMM có thể đổi bằng `--channel`
trong khoảng 1..30 nếu kênh mặc định bị chiếm; Windows cần làm mới dịch vụ.

Giao thức là UTF-8 JSON kết thúc LF, cùng schema/giới hạn với
[USB](USB.md): source tối đa 64 KiB, frame tối đa 512 KiB, 64 request ID gần nhất
để nhận diện trùng. Upload không hợp lệ xóa bản chờ. Source được parse thành
dữ liệu, không chạy Python tùy ý. Tham số baud của COM không đặt tốc độ radio.

Đây là công cụ thử qua Python; FE/BE chưa tích hợp Bluetooth. Browser API/cầu
nối trên máy người dùng cần được chọn và kiểm chứng riêng khi làm giao diện
Scratch. Chưa có dịch vụ tự khởi động, lưu bền kịch bản hay đồng bộ quyền điều
khiển giữa các receiver chạy thành các tiến trình khác nhau.
Yêu cầu dừng phần mềm không xác nhận bánh đứng yên nếu I²C/phần cứng gặp lỗi.

Nếu COM không mở: kiểm tra cổng Outgoing của đúng Pi, receiver còn đăng ký SPP,
quyền dịch vụ trên Pi, Bluetooth cả hai máy và ứng dụng khác có đang giữ COM.
Nếu BlueZ khởi động lại, chạy lại receiver để đăng ký lại profile.

## Kiểm thử và tài liệu nền

Từ thư mục cha của `vehicle_testing`:

```powershell
python -B -m unittest vehicle_testing.tests.test_bluetooth vehicle_testing.tests.test_bluetooth_bluez vehicle_testing.tests.test_bluetooth_client -v
```

Bài kiểm tra socket stream thực trên máy tính được bật riêng:

```powershell
$env:RUN_BT_STREAM_INTEGRATION='1'
python -B -m unittest vehicle_testing.tests.test_bluetooth_client -v
Remove-Item Env:RUN_BT_STREAM_INTEGRATION
```

Các test dùng runner mô phỏng, D-Bus giả lập và socket cục bộ; chưa xác nhận
radio Pi, driver COM trên laptop hoặc chuyển động trên xe thật.

Tài liệu chính thức đã đối chiếu:

- [BlueZ ProfileManager API](https://github.com/bluez/bluez/blob/master/doc/org.bluez.ProfileManager.rst): đăng ký profile, kênh RFCOMM, yêu cầu pairing/authorization.
- [BlueZ Profile API](https://bluez.readthedocs.io/en/latest/profile-api/): nhận FD và dọn kết nối trong Profile1.
- [Microsoft: Bluetooth host radio support](https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/bluetooth-host-radio-support): hỗ trợ SPP chuẩn trên Windows.
