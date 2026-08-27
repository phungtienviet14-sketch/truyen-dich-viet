# Oracle Always Free — trước khi triển khai

Tài liệu kiểm tra ngày 27/08/2026. Đây là kế hoạch và lệnh người dùng tự thực hiện sau xác nhận; chưa đăng nhập OCI, chưa tạo tài nguyên, chưa đổi DNS.

## Phạm vi miễn phí và lựa chọn

[Oracle công bố](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) A1 miễn phí 1.500 OCPU-giờ + 9.000 GB-giờ mỗi tháng, tương đương tổng **2 OCPU/12 GB RAM**, trong **home region**. Tổng boot/block volume miễn phí **200 GB** dùng chung toàn tenancy; VM nhàn rỗi có thể bị thu hồi, capacity có thể hết. Kiểm tra lại quyền lợi thực tế trong Console trước khi tạo.

Đề xuất ban đầu: một `VM.Standard.A1.Flex`, Ubuntu24.04 ARM64, 1 OCPU/6 GB RAM hoặc tối đa2/12 nếu toàn bộ allowance còn trống, boot50 GB, không thêm paid load balancer/NAT gateway/database. Cấu hình Compose giới hạn tổng CPU1.75 nên dùng2 OCPU nếu có allowance. Web+worker+Caddy trên một VM, SQLite trên boot volume và snapshot ngoài VM. DeepSeek API và domain riêng vẫn có thể tốn tiền.

Service limit cho phép tạo không đồng nghĩa miễn phí. Tổng cả VM/volume khác, free trial credit, backup và dịch vụ phụ đều phải tính. Budget alert **không tự dừng chi phí**. Không nâng Pay As You Go, đổi region, tự thử shape trả phí hoặc chạy vòng tạo VM khi hết capacity.

## Đăng nhập CLI trên máy người dùng

CLI có thể đã cài nhưng chưa nằm trong PATH. Kiểm tra `Get-Command oci` hoặc dùng đường dẫn executable đã cài; không cài lại/chỉnh credentials nếu chưa cần.

```powershell
oci --version
oci session authenticate --profile-name TRUYEN --region YOUR_HOME_REGION
oci session validate --profile TRUYEN --auth security_token
```

Thay `YOUR_HOME_REGION` bằng home region trong Console. CLI mở trình duyệt; người dùng tự nhập tài khoản/MFA và hoàn tất prompt. Không gửi token, private key, mật khẩu hoặc toàn bộ `~/.oci/config` vào chat. Profile `TRUYEN` mới tránh ghi đè profile khác.

Session token tạm thời cần `--auth security_token` khi gọi CLI; hết hạn thì đăng nhập/refresh theo hướng dẫn chính thức. [OCI token authentication](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/clitoken.htm).

Sau đăng nhập:

```powershell
python scripts/oracle_preflight.py --profile TRUYEN
```

Nếu CLI không có PATH, thêm `--oci-cli 'C:/path/to/oci.exe'`. Script chỉ đọc profile region/tenancy, gọi API liệt kê region và limits; không đọc file private key/token, không in credentials, không tạo/chỉnh bất kỳ tài nguyên nào. CLI tự dùng credential khi ký request. Script dừng nếu region khác home region. Kết quả entitlement không xác nhận capacity hoặc chi phí0.

## Thông tin phải xác nhận trước khi tạo VM

- Home region, compartment đích và quyền IAM.
- Tổng A1 OCPU/RAM đang dùng; boot/block volume và backup đang dùng toàn tenancy.
- Shape/image được Console đánh dấu Always Free, cấu hình CPU/RAM/disk và estimated cost sau free trial.
- Dải IP quản trị để giới hạn SSH; public key SSH do người dùng chọn (không phải private key).
- VCN/subnet/Internet Gateway/NSG nào có sẵn và phần nào được phép tạo mới.
- Domain chính xác đã sở hữu hoặc tên DuckDNS muốn đăng ký nếu còn trống.

Không có script `oci compute instance launch` tự động trong repo. Sau khi người dùng đăng nhập và xác nhận các lựa chọn trên, mới lập lệnh tạo cụ thể; cần kiểm tra rõ những tài nguyên được tạo và tổng allowance trước khi thực thi.

## Bước sau khi được phê duyệt

Tạo VM trong home region, không attach dịch vụ phụ chưa cần. Chỉ mở TCP22 từ IP quản trị, TCP80/443 public, tùy chọn UDP443; không mở8000. Trỏ DNS tới IP VM rồi theo [Deployment](DEPLOYMENT.md). Pull image ARM64 đã được kiểm thử, tạo `.env` trên VM, bảo vệ admin, snapshot dữ liệu cũ trước startup/migration. Kiểm tra HTTPS/DB/worker và một job thử được cho phép.

Không có đảm bảo uptime hoặc miễn phí vĩnh viễn cho hệ thống ứng dụng. Dữ liệu quan trọng phải có bản sao ngoài VM; Oracle có chính sách thu hồi tài nguyên nhàn rỗi.
