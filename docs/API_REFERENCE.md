# 🔌 TÀI LIỆU REST API (API Reference)

Tài liệu tham chiếu toàn bộ các API Endpoints của hệ thống **Truyện Dịch Việt**.

---

## 1. Tương Tác Độc Giả (Public Interaction APIs)

### 1.1 Thêm Yêu Thích (Favorite)
- **Endpoint**: `POST /api/novels/{novel_id}/favorite`
- **Mô tả**: Tăng lượt yêu thích của bộ truyện.
- **Phản hồi mẫu**:
```json
{
  "status": "success",
  "favorite_count": 12,
  "message": "Đã thêm 'Tiên Công Khai Vật' vào Tủ Truyện Yêu Thích!"
}
```

### 1.2 Yêu Cầu Dịch Tiếp (Request Translation)
- **Endpoint**: `POST /api/novels/{novel_id}/request-translation`
- **Mô tả**: Độc giả vote yêu cầu ưu tiên dịch tiếp tác phẩm.
- **Phản hồi mẫu**:
```json
{
  "status": "success",
  "request_count": 45,
  "message": "Đã ghi nhận yêu cầu dịch (+1). Nhóm Truyện Dịch Việt sẽ ưu tiên dịch tiếp tác phẩm này!"
}
```

### 1.3 Lấy Danh Sách Bình Luận (Get Comments)
- **Endpoint**: `GET /api/novels/{novel_id}/comments`
- **Query Params**: `chapter_index` *(tùy chọn: lọc theo chương cụ thể)*
- **Phản hồi mẫu**:
```json
[
  {
    "id": 1,
    "user_name": "Đạo Hữu Ninh Chuyết",
    "user_avatar": "🧙‍♂️",
    "content": "Bản dịch Cổ Chân Nhân rất mượt, cảm ơn nhóm dịch!",
    "likes": 5,
    "created_at": "10:30 27/08/2026",
    "chapter_index": null
  }
]
```

### 1.4 Gửi Bình Luận Mới (Post Comment)
- **Endpoint**: `POST /api/novels/{novel_id}/comments`
- **Request Body**:
```json
{
  "user_name": "Đạo Hữu Vô Danh",
  "user_avatar": "🐉",
  "content": "Chương này đọc cuốn quá!",
  "chapter_index": 7
}
```

### 1.5 Thả Tim Bình Luận (Like Comment)
- **Endpoint**: `POST /api/comments/{comment_id}/like`
- **Phản hồi mẫu**: `{"status": "success", "likes": 6}`

---

## 2. Tải & Xuất File Truyện (Download APIs)

### 2.1 Tải Truyện Tùy Biến (Flexible Download)
- **Endpoint**: `GET /api/novels/{novel_id}/download`
- **Query Parameters**:
  - `format`: `"epub"` hoặc `"txt"` *(mặc định: `epub`)*.
  - `start`: Số chương bắt đầu *(ví dụ: `1`)*.
  - `end`: Số chương kết thúc *(ví dụ: `50`)*.
  - `lang`: `"vi"` *(tiếng Việt)* hoặc `"raw"` *(nguyên tác tiếng Trung)*.
- **Phản hồi**: File Binary Stream (`application/epub+zip` hoặc `text/plain; charset=utf-8`).

---

## 3. Dịch Hàng Loạt Thông Minh (Batch Translation APIs)

### 3.1 Lấy Trạng Thái Hàng Đợi Dịch (Get Batch Status)
- **Endpoint**: `GET /api/admin/batch-translate/status`
- **Phản hồi mẫu**:
```json
{
  "is_running": true,
  "is_paused": false,
  "policy": "request_priority",
  "concurrency": 3,
  "current_novel_id": 1,
  "current_novel_title": "Tiên Công Khai Vật",
  "queue_length": 3,
  "queue": [
    {
      "novel_id": 1,
      "title": "Tiên Công Khai Vật",
      "pending_chapters": 900,
      "request_count": 45,
      "status": "translating"
    }
  ],
  "total_queued_chapters": 1200,
  "recent_logs": []
}
```

### 3.2 Khởi Động Dịch Hàng Loạt (Start Batch)
- **Endpoint**: `POST /api/admin/batch-translate/start`
- **Request Body**:
```json
{
  "novel_ids": [1, 2, 3],
  "policy": "request_priority",
  "concurrency": 3,
  "chapters_per_novel": 50
}
```

### 3.3 Tạm Dừng / Tiếp Tục / Hủy Hàng Đợi
- `POST /api/admin/batch-translate/pause` -> Tạm dừng
- `POST /api/admin/batch-translate/resume` -> Tiếp tục
- `POST /api/admin/batch-translate/stop` -> Hủy bỏ toàn bộ

---

## 4. Tự Động Đồng Bộ Nguồn (Auto-Updater & Ingestion APIs)

### 4.1 Cào Bộ Truyện Mới (Crawl Novel)
- **Endpoint**: `POST /api/novels/crawl`
- **Request Body**:
```json
{
  "url": "https://www.piaotia.com/html/15/15701/index.html",
  "title_vi": "Tiên Công Khai Vật"
}
```

### 4.2 Đồng Bộ Chương Mới Cho 1 Truyện (Sync Single Novel)
- **Endpoint**: `POST /api/admin/sync/novel/{novel_id}`
- **Phản hồi**: `{"status": "success", "new_chapters": 2, "total_chapters": 1043}`

### 4.3 Đồng Bộ Toàn Bộ Kho Truyện Ngay (Sync All)
- **Endpoint**: `POST /api/auto-updater/sync-now`

### 4.4 Khám Phá Truyện Hot BXH (Discover Hot)
- **Endpoint**: `POST /api/auto-updater/discover-hot`
- **Request Body**:
```json
{
  "category": "2",
  "count": 10
}
```
*(category: 2 = Tu chân tiên hiệp, 1 = Huyền huyễn, 0 = Tất cả)*

### 4.5 Cập Nhật Cấu Hình Quét 24/7 (Update Sync Config)
- **Endpoint**: `POST /api/admin/sync/config`
- **Request Body**: `{"interval_minutes": 15, "auto_translate": false}`

---

## 5. Dịch Thuật Đơn Lẻ & SSE Stream (Single Translation APIs)

### 5.1 Bắt Đầu Dịch Truyện
- **Endpoint**: `POST /api/novels/{novel_id}/translate`
- **Request Body**:
```json
{
  "start_chapter": 1,
  "end_chapter": 50,
  "concurrency": 3,
  "retranslate_completed": false
}
```

### 5.2 Dừng Dịch Truyện
- **Endpoint**: `POST /api/novels/{novel_id}/stop`

### 5.3 Live SSE Stream (Server-Sent Events)
- **Endpoint**: `GET /api/stream/{novel_id}`
- **Format**: `text/event-stream`
- **Sự kiện truyền phát**:
  - `chapter_started`: `{ "event": "chapter_started", "chapter_index": 1, "title_raw": "..." }`
  - `chapter_completed`: `{ "event": "chapter_completed", "chapter_index": 1, "title_vi": "..." }`
  - `error`: `{ "event": "error", "message": "..." }`
  - `finished`: `{ "event": "finished" }`

---

## 6. Quản Lý Từ Điển Glossary (Glossary APIs)

- `POST /api/novels/{novel_id}/glossary`: Thêm từ mới (`{"original_term": "宁拙", "translated_term": "Ninh Chuyết", "note": "Main"}`)
- `DELETE /api/glossary/{glossary_id}`: Xóa từ điển
