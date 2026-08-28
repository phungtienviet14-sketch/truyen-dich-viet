# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này. Đọc kỹ phần **Ràng buộc bất biến** trước khi sửa bất cứ thứ gì.

## Hệ thống là gì

Nền tảng đọc tiểu thuyết Trung Quốc dịch sang tiếng Việt bằng DeepSeek API. FastAPI + Jinja2 + SQLAlchemy async, chạy trên SQLite (một máy) hoặc Postgres/Neon (nhiều máy).

**Kiến trúc vận hành hiện tại:** PC ở nhà nạp truyện và dịch, ghi vào Neon Postgres; Render chỉ phục vụ nội dung đã nạp. Lý do ở phần dưới.

## Lệnh thường dùng

```bash
# Test (CI chạy đúng bộ này, cổng coverage 80%)
.venv/Scripts/python.exe -m pytest -q

# Lint như CI
.venv/Scripts/python.exe -m ruff check --select E9,F63,F7,F82 app scripts tests

# Chạy toàn bộ stack (web + worker)
docker compose build && docker compose up -d
docker compose logs -f worker

# Sinh hash mật khẩu admin
.venv/Scripts/python.exe -m app.auth hash-password

# Worker riêng, không qua Docker
.venv/Scripts/python.exe -m app.worker
```

## Bản đồ mã nguồn

| Đường dẫn | Trách nhiệm |
| --- | --- |
| `app/main.py` | Middleware bảo mật, rate limit, audit log, health check, lifespan |
| `app/auth.py` | Session admin + độc giả, PBKDF2, CSRF, kiểm origin, `RateLimiter` |
| `app/config.py` | Biến môi trường; `normalize_database_url()` chuyển chuỗi libpq sang asyncpg |
| `app/database.py` | Engine, migration portable (`migrate_novels`, `migrate_sqlite`), `dialect_insert` |
| `app/models.py` | Novel, Chapter, Glossary, Comment, User, Session, AuditLog |
| `app/catalog.py` | 9 thể loại nguồn, các cột xếp hạng, bộ lọc tìm kiếm |
| `app/routes/public.py` | Trang độc giả: thư viện, đọc, xếp hạng, tìm kiếm, thể loại, export |
| `app/routes/admin.py` | **Toàn bộ route quản trị** — router có `require_admin` ở cấp router |
| `app/routes/auth.py` | Đăng nhập admin, đăng ký/đăng nhập độc giả, đồng bộ dữ liệu |
| `app/crawler/security.py` | Ranh giới mạng: allowlist host, ghim DNS, chặn body quá cỡ, rate limit |
| `app/crawler/piaotia.py` | Parser nguồn chính; `parse_source_stats()` lấy số liệu xếp hạng |
| `app/crawler/auto_updater.py` | Vòng đồng bộ định kỳ, khám phá truyện mới, nạp raw |
| `app/crawler/sync_store.py` | Giao dịch ngắn cho sync; `SyncLease`, `merge_catalog`, `storage_used_mb` |
| `app/crawler/identity.py` | `work_key()` — vân tay chống trùng truyện giữa các nền tảng |
| `app/translator/jobs.py` | Hàng đợi SQL bền vững, lease singleton, hạn mức token ngày |
| `app/translator/dispatcher.py` | Thực thi từng cửa sổ công việc dưới lease |
| `app/translator/deepseek.py` | Client DeepSeek, chia chunk, kiểm chất lượng output |
| `app/embedded_worker.py` | Worker chạy trong process web (chỉ cho host một service) |

## Ràng buộc bất biến

Vi phạm những điều này sẽ gây hỏng thật, không phải chuyện phong cách.

**Không bao giờ tự ý dịch truyện.** Dịch tiêu tốn tiền thật của chủ hệ thống. `auto_translate` đang được ghi `false` trong bảng `system_settings`. Không thêm đường nào tự động gọi DeepSeek.

**Route quản trị chỉ đặt trong `app/routes/admin.py`.** Router đó gắn `require_admin` ở cấp router. Đặt một thao tác quản trị vào `public.py` là mở nó cho toàn bộ Internet.

**Crawler fail-closed.** Mọi URL nguồn phải đi qua `canonical_url()`. Chỉ HTTPS, chỉ host trong `CRAWLER_ALLOWED_HOSTS`, chặn IP literal và dải private, tự kiểm từng redirect. Không nới lỏng để "chữa" một nguồn không hỗ trợ.

**Dữ liệu truyện là dữ liệu không tin cậy.** Tiêu đề và nội dung đến từ trang bị cào. Trong JavaScript luôn dùng `textContent` / `replaceChildren` / `ui.safeImageURL`, **không bao giờ** `innerHTML`. Trong Jinja thì auto-escape đã lo, nhưng đừng nhúng dữ liệu vào chuỗi JavaScript.

**Migration phải portable.** `migrate_novels()` chạy trên cả SQLite lẫn Postgres. Dùng `TIMESTAMP`, **không** dùng `DATETIME` (chỉ SQLite hiểu). Chỉ thêm cột, không xoá.

**Không tăng số uvicorn worker.** `RateLimiter` đếm trong RAM và `Dockerfile` cố định `--workers 1`. Tăng worker sẽ âm thầm nhân hạn mức rate limit lên.

## Cạm bẫy đã gặp thật

**Render không cào được truyện.** Nguồn dùng Cloudflare và thử thách IP của trung tâm dữ liệu; không header hay retry nào vượt qua (`SourceChallenged` trong `crawler/security.py`). Máy ở nhà thì không bị chặn. Vì thế `RUN_EMBEDDED_WORKER=0` trên Render — nếu để `1`, khi PC tắt Render sẽ giành lease và lấp hàng đợi bằng lỗi.

**Chuỗi kết nối Neon có `channel_binding=require`.** asyncpg không nhận tham số libpq này. `normalize_database_url()` chỉ giữ lại keyword asyncpg hiểu. Đừng "đơn giản hoá" hàm này về `str.replace`.

**Template được nướng vào image.** `docker compose restart` **không** nạp thay đổi template. Phải `docker compose build` lại.

**Jinja: `{% set %}` trong vòng lặp không tới được `{% include %}`.** Dùng `{% with a = x, b = y %}` để truyền biến vào template được include. Đã có lỗi thật vì chuyện này (số liệu xếp hạng không hiện).

**Partial dùng chung phải phòng thủ.** `_pagination.html` đặt giá trị mặc định cho input, vì có test render template với context tối thiểu.

**Không giới hạn ký tự wildcard trong tìm kiếm.** `catalog.search_filter()` escape `%` và `_`; người đọc gõ "100%" là muốn ký tự đó.

## Dung lượng và hiệu năng

Số liệu đo thật trên thư viện 149 truyện / 412.177 chương (xem `docs/STORAGE.md`):

- Mục lục ~0,35 KB/chương; nội dung raw ~6,5 KB/chương sau nén TOAST.
- **Index của bảng `chapters` chiếm nhiều hơn cả nội dung.** Kiểm tra `pg_stat_user_indexes` trước khi thêm index mới.
- `CRAWLER_RAW_BUDGET_MB` (mặc định 400) dừng lưu raw khi DB chạm ngưỡng, nhưng **vẫn tiếp tục đồng bộ mục lục**.
- Trang chi tiết truyện phân trang 100 chương; trang đọc **không** tải mục lục (drawer tự fetch qua API).
- `merge_catalog` chèn theo lô 500 dòng. Đừng quay lại chèn từng dòng — Neon ở Singapore, mỗi dòng là một lượt đi-về.

## Quy ước test

- `tests/conftest.py` cô lập database vào thư mục tạm và **cấm mọi HTTP ra ngoài** (dùng `MockTransport`).
- Fixture có sẵn: `client`, `admin_client`, `db`, `sample_novel`.
- Test hàm thuần để ở `test_catalog.py` / `test_config.py` (không có mark asyncio ở module).
- Khi sửa lỗi, viết test tái hiện đúng lỗi đó trước.
