# Triển khai Truyện Dịch Việt

Mục tiêu: một Oracle VM, Docker Compose, web FastAPI + worker riêng, SQLite trên ổ đĩa bền vững, Caddy cấp HTTPS. Chưa có thao tác tạo VM, thay DNS hoặc deploy nào được thực hiện bởi các file cấu hình này. Xem [Oracle Always Free](ORACLE_ALWAYS_FREE.md) trước khi tạo tài nguyên.

## 1. Chuẩn bị host

Dùng Ubuntu 24.04 ARM64 cho A1. Cài Docker Engine và Compose plugin theo [kho APT chính thức](https://docs.docker.com/engine/install/ubuntu/), kiểm tra khóa/kho trước khi cài. Không dùng `curl | sh`. Docker group có quyền tương đương root: chỉ cấp cho tài khoản vận hành đáng tin.

Đặt bản source/release đã kiểm thử tại `/opt/truyen`. Các lệnh dưới đây chỉ chạy trên host đã được người dùng phê duyệt, trong thư mục đó.

```bash
cd /opt/truyen
cp .env.example .env
chmod 600 .env
sudo install -d -m 0750 -o 10001 -g 10001 data data/exports data/backups
```

**Nếu đã có dữ liệu:** sao lưu trước, kiểm tra đường dẫn tuyệt đối, sau đó chỉ đổi owner của thư mục `data` của dự án sang UID/GID `10001:10001`. Không xóa dữ liệu, không dùng `docker compose down -v`. Compose bind-mount `./data`, hoặc đường dẫn tuyệt đối trong `TRUYEN_DATA_PATH`; không mount `.env` vào container.

## 2. Cấu hình an toàn

Sửa `.env` bằng editor trên host; không gửi file này vào chat, GitHub hoặc Docker image. Tạo mật khẩu admin bằng `python -m app.auth hash-password` (nhập kín), tạo `SESSION_SECRET` ngẫu nhiên dài ít nhất 32 ký tự. Công cụ hash cần runtime Python đã cài dependencies; hoặc chạy image đã build bằng `docker run --rm -it --entrypoint python IMAGE -m app.auth hash-password`.

```dotenv
APP_ENV=production
SKIP_DOTENV=1
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH='paste-generated-password-hash-here'
SESSION_SECRET='paste-long-random-secret-here'
SESSION_COOKIE_SECURE=true
APIKEY_DEEPSEEK='paste-private-api-key-here'
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_MAX_TOKENS=8192
MAX_CONCURRENT_TRANSLATIONS=2
TRANSLATION_DAILY_TOKEN_LIMIT=100000
DOMAIN=truyendichviet.example.org
ACME_EMAIL=you@example.org
```

Giữ dấu nháy đơn quanh hash chứa `$` để Compose không nội suy. Tên domain chỉ là mẫu; dùng tên bạn kiểm soát. Model được Compose ghim `deepseek-v4-flash`; client gửi `thinking: {type: disabled}`. Token quota là giới hạn vận hành, **không phải cam kết chi phí tuyệt đối**; đặt thêm giới hạn/tài khoản API phù hợp tại DeepSeek. Không có DeepSeek key thật trong CI.

Không đặt `DATABASE_URL` trỏ ra ngoài `/app/data` khi dùng volume mặc định. `CRAWLER_ALLOWED_HOSTS` chỉ liệt kê domain nguồn đã kiểm tra và có quyền khai thác. Không mở truy cập tùy ý để chữa lỗi nguồn không được hỗ trợ.

Một chuỗi dạng API key đã bị loại khỏi tài liệu cũ. Nếu đó từng là khóa thật, chủ tài khoản phải thu hồi/đổi khóa, kiểm tra lịch sử Git/image và usage. Xóa text không vô hiệu hóa khóa.

## 3. DNS, firewall và HTTPS

Trỏ bản ghi A của domain tới IPv4 VM; chỉ tạo AAAA nếu IPv6 hoạt động. Ví dụ tên miễn phí có thể là `truyendichviet.duckdns.org` nếu đăng ký được; chưa kiểm tra khả dụng. Domain `.vn`/`.com` thường có phí.

Trong OCI NSG/security list và host firewall: TCP22 chỉ từ IP quản trị, TCP80/443 từ Internet; UDP443 tùy chọn cho HTTP/3. **Không mở 8000**. Docker có thể bypass một số quy tắc UFW, vì vậy giới hạn cả tại OCI và publish port của Compose. [Docker firewall caveat](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations).

Caddy là service duy nhất publish public. FastAPI chỉ bind `127.0.0.1:8000` trên host; `--no-proxy-headers` tránh tin header giả. Rate limit hiện nhìn thấy địa chỉ proxy khi qua Caddy; không tự đổi sang trust-all proxy. Admin cookie production yêu cầu HTTPS.

## 4. Khởi động lần đầu

Build tại VM (có thể tốn vài phút) hoặc pull image GHCR đã được CI kiểm thử. Với ARM phải dùng image `linux/arm64`; pipeline phát hành cả ARM64/AMD64.

```bash
docker compose -f docker-compose.yml -f deploy/compose.production.yml config --quiet
docker compose -f docker-compose.yml -f deploy/compose.production.yml up -d --build --wait --wait-timeout 180
docker compose -f docker-compose.yml -f deploy/compose.production.yml ps
curl --fail https://YOUR_DOMAIN/health/ready
docker compose exec -T worker python -m app.worker --healthcheck
```

Không dùng `docker compose config` không có `--quiet`: output có thể chứa secrets. Nếu `config --quiet` lỗi do biến thiếu, sửa `.env`; không tắt validation.

Web tạo/cập nhật schema trước khi báo ready; worker chỉ khởi động sau readiness. Giữ **1 web process, 1 worker** cho cấu hình SQLite này. Worker lease ngăn hai bộ dịch chủ động; không scale ngang khi chưa chuyển kiến trúc DB. Restart không phải bằng chứng resume chính xác: cần kiểm tra job thật bằng mock trước, rồi thử một chương có ngân sách được cho phép.

Kiểm tra thủ công trước khi mở public: khách đọc được, `/admin` yêu cầu đăng nhập, API quản trị từ chối khách, đăng nhập/logout, crawl nguồn được phép, đồng bộ không trùng, bản dịch không bị cắt, tải TXT/EPUB, trạng thái worker và quota.

## 5. Snapshot và cập nhật

```bash
docker compose exec -T web python scripts/backup_sqlite.py /app/data/novels.db /app/data/backups/manual-20260827.db
```

Script dùng SQLite backup API nên bao gồm dữ liệu đã commit trong WAL, kiểm tra `PRAGMA quick_check`, tạo file mới mode0600, từ chối ghi đè. Không copy đơn lẻ file `.db` đang chạy. Sao lưu ra thiết bị/dịch vụ khác theo lịch bạn duyệt; snapshot cùng VM không bảo vệ khỏi mất volume. File export có thể tái tạo, nhưng cấu hình secrets và chứng chỉ cần chính sách sao lưu riêng.

Với image đã publish và quyền pull được cấu hình trên host:

```bash
bash scripts/deploy_oracle.sh ghcr.io/OWNER/REPO:FULL_40_CHARACTER_COMMIT_SHA
```

Thay mẫu bằng owner/repo viết thường và SHA thật. Script khóa chống deploy chồng, pull image cố định, snapshot trước migration, chạy Compose và đợi health của web/worker. Nếu lỗi, dừng worker để tránh ghi tiếp; không tự restore DB hoặc hạ schema. Script không cập nhật source/config từ Git: đồng bộ bộ `docker-compose.yml`, `deploy/`, `scripts/` đúng release đã review trước khi chạy. Có gián đoạn ngắn khi recreate container.

## 6. Rollback và restore

1. Dừng web/worker, giữ Caddy nếu muốn trả lỗi tạm. Đọc `.deploy/previous-image.txt` và snapshot predeploy; bảo toàn logs và dữ liệu lỗi.
2. Nếu schema tương thích ngược, đặt `TRUYEN_IMAGE` về image trước rồi `docker compose -f docker-compose.yml -f deploy/compose.production.yml up -d --no-build --wait`. Giữ cùng đường dẫn volume.
3. Nếu schema không tương thích, kiểm tra snapshot và phục hồi trước. **Mất các ghi sau thời điểm snapshot**; phải được người vận hành đồng ý.

Ví dụ restore tới file MỚI trên host (cả web/worker đã dừng):

```bash
python3 scripts/backup_sqlite.py data/backups/PREDEPLOY.db data/novels-restored.db --restore
```

Sau khi kiểm tra nội dung, di chuyển DB hiện tại **cùng** các sidecar `novels.db-wal`, `novels.db-shm` (nếu có) vào thư mục giữ lỗi mới, không xóa. Đổi `novels-restored.db` thành `novels.db`, đặt owner10001/group10001 và mode0600 rồi khởi động image cũ. Không thay DB khi bất kỳ tiến trình ghi nào còn chạy. Diễn tập restore trên bản sao trước lần public đầu tiên.

## 7. Vận hành

Log Docker được giới hạn 3 file × 10 MB/service. Theo dõi dung lượng disk, chi phí/token DeepSeek, queue lỗi và heartbeat. Theo dõi `/health/ready` qua HTTPS nhưng không dùng request giả để né chính sách thu hồi VM nhàn rỗi. Nâng dependency/base image có kiểm thử, tránh dùng tag `latest` cho release.
