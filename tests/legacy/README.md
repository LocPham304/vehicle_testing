# Kiểm thử công cụ đã bỏ

Hai file này trước đây kiểm tra `vehicle_testing.probe_servo` và
`vehicle_testing.probe_lift_pwm`. Hai module đó đã không còn trong source trước
lần sắp xếp thư mục ngày 29/10/2026; chạy discovery khi đó báo 16 lỗi import.

Giữ lại các kiểm tra để tham khảo nếu phục hồi công cụ dò servo sau này.
Chúng được đổi tên thành `*_checks.py` và thư mục này không có `__init__.py`,
nên không thuộc bộ test tự động hiện tại. Không dùng chúng làm bằng chứng kiểm
chứng chức năng đang có. Các test PWM, hiệu chỉnh, nâng/hạ và càng còn hoạt động
vẫn nằm trong `tests/` và được chạy bình thường.
