# 📖 TRUYỆN DỊCH VIỆT (AI Novel Translation & Reading Platform)

> **Truyện Dịch Việt** là nền tảng đọc và tải tiểu thuyết Trung Quốc dịch tự động bằng AI (DeepSeek API) chất lượng cao. Hệ thống tích hợp tính năng tự động cào và đồng bộ chương mới ngầm 24/7 từ các nền tảng truyện Trung Quốc, quản lý dịch hàng loạt thông minh, trình đọc tối ưu typography tiếng Việt, tải truyện tùy chọn dải chương (EPUB/TXT) và cổng quản trị Admin chuyên sâu.

---

## 🌟 Tính Năng Nổi Bật

### 1. 👥 Cổng Độc Giả (Public Portal)
- **Đọc truyện trực tuyến chất lượng cao**:
  - Tinh chỉnh chuẩn phông chữ tiếng Việt (Google Fonts: *Lora*, *Literata*, *Be Vietnam Pro*, *Merriweather*).
  - 4 màu nền giấy đọc chống mỏi mắt: **📜 Sepia Giấy Vàng**, **☀️ Trắng Tinh**, **🌙 Ban Đêm (Dark)**, **🖤 OLED Đen Tuyền**.
  - Tùy chỉnh cỡ chữ (15px - 30px), dãn dòng (1.6 - 2.2), căn đều 2 bên (Justified), thụt lề đầu dòng chuẩn sách (`text-indent: 1.8em`).
  - Hỗ trợ 3 chế độ xem: **Tiếng Việt thuần túy**, **Song ngữ đối chiếu Trung - Việt**, hoặc **Bản gốc Raw**.
- **Tải truyện miễn phí theo dải chương (Range Downloader)**:
  - Tải trọn bộ hoặc chọn dải chương tùy ý (Ví dụ: Từ chương 1 đến 50, chương 51 đến 100...).
  - Định dạng **`.EPUB`** (có mục lục navigation để đọc trên máy đọc sách Kindle, Kobo, Moon+ Reader) hoặc **`.TXT`** (thuần văn bản).
  - Tùy chọn tải bản dịch **Tiếng Việt** hoặc **Nguyên tác Tiếng Trung (Raw)**.
- **Tiến độ dịch thuật trực tiếp**: Hiển thị phần trăm hoàn thành, số chương đã dịch / tổng số chương của từng tác phẩm.
- **Tương tác cộng đồng**:
  - **❤️ Tủ Truyện Yêu Thích**: Lưu truyện yêu thích vào trình duyệt (`localStorage`) để đọc lại nhanh.
  - **🚀 Nút Yêu Cầu Dịch Tiếp**: Độc giả gửi phiếu yêu cầu ưu tiên dịch tác phẩm yêu thích.
  - **💬 Bình luận & Thảo luận**: Chọn biểu tượng đạo hiệu (🧙‍♂️, ⚔️, 🐉, 🌸, 🔥, 📜, ⚡), bình luận theo truyện hoặc theo từng chương đọc.
- **☕ Hệ thống Donate QR Code**: Tự động hiển thị banner trượt từ Header sau 2 giây và modal chuyển khoản Techcombank VietQR/Napas247 kèm nút 1-click Copy số tài khoản.

---

### 2. 🛡️ Cổng Quản Trị Thông Minh (Admin Portal - `/admin`)
- **Tự động đồng bộ nguồn ngầm 24/7 (Continuous Auto-Sync)**:
  - Tùy chỉnh chu kỳ quét tự động (5 phút, 15 phút, 30 phút, 1 giờ).
  - Tự động kết nối nguồn nguyên tác Trung Quốc (Piaotian, Biquge...), phát hiện chương mới vừa ra và nạp raw vào database (**hoàn toàn không tốn token DeepSeek**).
  - Nhật ký quét đồng bộ thời gian thực (Live Sync Activity Logs).
  - Nút **"Khám Phá BXH Trung Quốc"**: Tự động quét và nạp các bộ truyện Hot nhất theo thể loại (Tu chân tiên hiệp, Huyền huyễn ma pháp...).
- **Quản lý dịch hàng loạt thông minh (Smart Batch Translation Queue)**:
  - **Chính sách ưu tiên thông minh**:
    - 🎯 *Ưu tiên theo lượt Độc Giả Yêu Cầu (Smart AI)*: Tự động xếp các truyện có nhiều lượt vote nhất lên đầu hàng đợi để dịch trước.
    - ⚡ *Dịch toàn bộ chương còn thiếu*.
    - 🔄 *Dịch xoay vòng (Round-Robin)*: Mỗi truyện dịch N chương rồi luân chuyển.
  - Bộ điều khiển hàng đợi: Khởi động, Tạm dừng, Tiếp tục, Hủy hàng đợi.
- **Phòng Dịch DeepSeek AI Chuyên Sâu Từng Truyện (`/admin/novel/{id}`)**:
  - Tùy chọn dải chương, số luồng song song (1 - 5 luồng), dịch lại chương lỗi.
  - Màn hình **Live SSE Console Output** xem trực tiếp tiến độ dịch từng chương thời gian thực.
  - **Từ Điển Glossary**: Quản lý bảng quy chuẩn danh xưng nhân vật, công pháp, địa danh gán cứng (`宁拙 -> Ninh Chuyết`, `火柿仙城 -> Hỏa Thị Tiên Thành`...).

---

## 🏗️ Kiến Trúc Dự Án

```
truyen/
├── .env                     # Biến môi trường & DeepSeek API Key
├── .env.example             # Cấu hình mẫu
├── Dockerfile               # Cấu hình container Python 3.12
├── docker-compose.yml       # Điều phối dịch vụ Docker
├── requirements.txt         # Thư viện phụ thuộc
├── README.md                # Tài liệu tổng quan
├── docs/                    # Bộ tài liệu chi tiết của dự án
│   ├── ARCHITECTURE.md      # Kiến trúc hệ thống & Database Schema
│   ├── USER_GUIDE.md        # Hướng dẫn dành cho Độc giả
│   ├── ADMIN_GUIDE.md       # Hướng dẫn Quản trị viên
│   ├── API_REFERENCE.md     # Tài liệu REST API đầy đủ
│   ├── DEPLOYMENT.md        # Hướng dẫn Triển khai & Production
│   └── CI_CD.md             # Quy trình CI/CD, GitHub Actions & DuckDNS
├── tests/                   # Bộ kiểm thử tự động (Pytest)
│   └── test_api.py          # Unit & Integration tests
├── scripts/                 # Scripts tiện ích & Tự động hóa
│   └── duckdns_updater.py   # Tự động đồng bộ IP động lên DuckDNS
├── .github/workflows/       # Quy trình CI/CD GitHub Actions
│   └── ci-cd.yml            # Pipeline kiểm thử, build Docker & deploy HF
├── app/
│   ├── main.py              # FastAPI server, REST APIs & Route views
│   ├── config.py            # Quản lý cấu hình & đường dẫn
│   ├── database.py          # SQLAlchemy async engine (SQLite WAL mode)
│   ├── models.py            # Database Models (Novel, Chapter, Glossary, Comment)
│   ├── crawler/             # Bộ thu thập dữ liệu & Tự động đồng bộ
│   │   ├── base.py          # Abstract Crawler
│   │   ├── piaotia.py       # Crawler Piaotian (GBK encoding, clean DOM parser)
│   │   ├── biquge.py        # Crawler Biquge
│   │   └── auto_updater.py  # Auto-Updater 24/7 background worker & sync logs
│   ├── translator/          # Bộ dịch thuật DeepSeek AI
│   │   ├── deepseek.py      # DeepSeek API client + Prompt Tiên Hiệp + Glossary
│   │   ├── worker.py        # Worker hàng đợi đa luồng & SSE broadcaster
│   │   └── batch_manager.py # Bộ quản lý dịch hàng loạt thông minh
│   ├── exporters/           # Bộ xuất file offline (.TXT & .EPUB)
│   │   └── epub_txt.py      # Tạo EPUB/TXT theo dải chương hoặc trọn bộ
│   ├── static/              # Tài nguyên tĩnh (ảnh QR donate, icons)
│   └── templates/           # Giao diện Web (Tailwind CSS + DaisyUI)
│       ├── base.html        # Layout chung, logo, donate modal & 2s banner
│       ├── index.html       # Trang chủ độc giả & Bảng tiến độ dịch
│       ├── novel_detail.html# Chi tiết truyện, bình luận, nút yêu thích & vote
│       ├── reader.html      # Trình đọc chương (typography, themes, comment)
│       └── admin/           # Phân hệ Quản trị Admin riêng biệt
│           ├── admin_base.html
│           ├── admin_dashboard.html # Quản lý kho, dịch hàng loạt, nhật ký sync
│           └── admin_novel_translate.html # Phòng dịch DeepSeek & Live SSE
└── data/                    # Nơi lưu database novels.db & file export
```

---

## 🚀 Hướng Dẫn Cài Đặt & Khởi Chạy

### Yêu Cầu Hệ Thống
- Python 3.10+ hoặc Docker & Docker Compose.
- API Key DeepSeek (lấy tại [platform.deepseek.com](https://platform.deepseek.com)).

### 1. Cấu hình file `.env`
Tạo file `.env` tại thư mục gốc của dự án:
```env
APIKEY_DEEPSEEK=sk-your-deepseek-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
MAX_CONCURRENT_TRANSLATIONS=3
REQUEST_TIMEOUT=90
```

---

### 2. Khởi chạy bằng Docker Compose (Khuyên dùng)
```bash
docker compose up -d --build
```
Mở trình duyệt truy cập:
- **Cổng Độc Giả**: `http://localhost:8000`
- **Cổng Quản Trị Admin**: `http://localhost:8000/admin`

---

### 3. Khởi chạy trực tiếp với Python trên Windows / Linux / macOS
```bash
# 1. Tạo và kích hoạt môi trường ảo
python -m venv venv
venv\Scripts\activate      # Trên Windows
source venv/bin/activate   # Trên Linux/macOS

# 2. Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt

# 3. Khởi chạy server FastAPI
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📚 Danh Sách Tài Liệu Chi Tiết

Vui lòng tham khảo các tài liệu chuyên sâu trong thư mục [`docs/`](file:///c:/Users/phung/Documents/truyen/docs/):

1. 🏛️ [**Kiến Trúc Hệ Thống & Database Schema** (`docs/ARCHITECTURE.md`)](file:///c:/Users/phung/Documents/truyen/docs/ARCHITECTURE.md)
2. 📖 [**Hướng Dẫn Độc Giả Đọc & Tải Truyện** (`docs/USER_GUIDE.md`)](file:///c:/Users/phung/Documents/truyen/docs/USER_GUIDE.md)
3. 🛡️ [**Hướng Dẫn Quản Trị Viên Dịch Thuật & Đồng Bộ** (`docs/ADMIN_GUIDE.md`)](file:///c:/Users/phung/Documents/truyen/docs/ADMIN_GUIDE.md)
4. 🔌 [**Tài Liệu REST API Tham Chiếu** (`docs/API_REFERENCE.md`)](file:///c:/Users/phung/Documents/truyen/docs/API_REFERENCE.md)
5. 🚢 [**Hướng Dẫn Triển Khai & Production** (`docs/DEPLOYMENT.md`)](file:///c:/Users/phung/Documents/truyen/docs/DEPLOYMENT.md)
6. 🔄 [**Quy Trình CI/CD & Tự Động Hóa Triển Khai** (`docs/CI_CD.md`)](file:///c:/Users/phung/Documents/truyen/docs/CI_CD.md)

---

## 📄 Bản Quyền & Đóng Góp

Dự án được xây dựng phục vụ mục đích phi thương mại cho cộng đồng đam mê tiểu thuyết tiên hiệp / kiếm hiệp / huyền huyễn. Toàn bộ sự ủng hộ qua mã QR Techcombank sẽ được sử dụng trực tiếp để duy trì máy chủ và chi phí API dịch truyện miễn phí.
