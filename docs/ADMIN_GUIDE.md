# 🛡️ HƯỚNG DẪN QUẢN TRỊ VIÊN (Admin Guide)

Tài liệu này hướng dẫn quản trị viên vận hành hệ thống **Truyện Dịch Việt**, điều phối dịch thuật DeepSeek AI, quản lý tự động đồng bộ chương mới 24/7 và thiết lập từ điển Glossary.

---

## 1. Truy Cập Trang Quản Trị

- Mở trình duyệt và truy cập: **`http://localhost:8000/admin`**
- Hoặc bấm vào biểu tượng chiếc khiên bảo vệ `🛡️` ở góc trên bên phải thanh Header của website.

---

## 2. Quản Lý Kho Truyện & Nạp Dữ Liệu

### 2.1 Thêm Bộ Truyện Mới Thủ Công
1. Bấm nút **"Thêm Link Cào"** trên thanh tiêu đề Admin.
2. Nhập URL mục lục truyện từ các nguồn được hỗ trợ:
   - **Piaotian (飘天文学)**: `https://www.piaotia.com/html/15/15701/index.html` (Khuyên dùng: tốc độ cao, không chặn bot).
   - **Biquge (笔趣阁)**: `https://www.bqgui.cc/book/12345/`
3. Nhập tên Việt hóa mong muốn (Ví dụ: *Tiên Công Khai Vật*).
4. Bấm **"Cào Dữ Liệu"**. Hệ thống sẽ tự động bóc tách thông tin tác giả, ảnh bìa, tóm tắt và nạp toàn bộ danh mục chương vào cơ sở dữ liệu với trạng thái `pending`.

### 2.2 Tự Động Nạp Truyện Hot Từ Bảng Xếp Hạng Trung Quốc
1. Bấm nút **"Nạp Truyện Hot BXH"** trên thanh tiêu đề Admin.
2. Chọn thể loại mong muốn:
   - *Võ Hiệp & Tu Chân Tiên Hiệp* (武侠修真)
   - *Huyền Huyễn Ma Pháp* (玄幻魔法)
   - *Tất Cả Mới Cập Nhật* (最新更新)
3. Chọn số lượng truyện muốn nạp (5, 10 hoặc 15 bộ).
4. Bấm **"Nạp Ngay"**. Hệ thống sẽ tự động cào và nạp đầy đủ vào kho mà không tiêu tốn token dịch AI.

---

## 3. Tự Động Đồng Bộ Chương Mới 24/7 (Tab "Tự Động Đồng Bộ 24/7")

Hệ thống được trang bị worker chạy ngầm định kỳ để kiểm tra khi tác giả ra chương mới:

- **Cấu hình chu kỳ quét**: Chọn *5 phút, 15 phút, 30 phút hoặc 60 phút/lần* và bấm **"Lưu Cấu Hình"**.
- **Công tắc bật/tắt**: Bấm nút **"Đang BẬT / Đang TẮT"** để kích hoạt hoặc tạm dừng quét ngầm.
- **Đồng bộ thủ công tức thì**:
  - Bấm **"Quét Toàn Bộ Thư Viện Ngay"** để kiểm tra đồng loạt tất cả các bộ truyện.
  - Hoặc bấm nút **"Đồng bộ"** ở từng dòng truyện trong Tab 1.
- **Nhật Ký Đồng Bộ Thời Gian Thực (Live Sync Logs)**: Theo dõi bảng lịch sử quét để biết truyện nào vừa có thêm chương mới (+X chương).

---

## 4. Quản Lý Dịch Hàng Loạt Thông Minh (Tab "Dịch Hàng Loạt Thông Minh")

Admin không cần phải mở từng truyện để dịch thủ công mà có thể sử dụng bộ điều phối hàng đợi thông minh:

### 4.1 Lựa Chọn Chính Sách Ưu Tiên
- 🎯 **Ưu tiên theo lượt Độc Giả Yêu Cầu (Smart AI - Khuyên Dùng)**:
  - Hệ thống tự động phân tích cột **"Độc Giả Vote 🚀"** và xếp các bộ truyện có lượt yêu cầu cao nhất lên đầu hàng đợi để dịch trước.
- ⚡ **Dịch toàn bộ chương còn thiếu**: Dịch tuần tự các chương chưa hoàn thành của tất cả truyện.
- 🔄 **Dịch xoay vòng (Round-Robin)**: Mỗi truyện dịch một số lượng chương nhất định (ví dụ: 10 chương) rồi chuyển sang truyện tiếp theo để đảm bảo truyện nào cũng có chương mới đều đặn.

### 4.2 Thao Tác Nhanh Với Các Truyện Đã Chọn (Bulk Selection)
Tại Tab 1 (Kho Truyện):
1. Tích chọn các ô Checkbox của các bộ truyện bạn muốn dịch.
2. Thanh công cụ màu xanh sẽ xuất hiện:
   - Bấm **"Dịch Hàng Loạt Đã Chọn"** -> Tự động nạp danh sách vào hàng đợi dịch.
   - Bấm **"Đồng Bộ Nguồn Đã Chọn"** -> Tự động cập nhật chương mới từ nguồn.

### 4.3 Điều Khiển Hàng Đợi
- **Khởi Động Hàng Đợi**: Bắt đầu tiến trình dịch ngầm.
- **Tạm Dừng / Tiếp Tục**: Tạm dừng tạm thời khi cần bảo trì hoặc hạ tải.
- **Dừng Hẳn**: Hủy bỏ hàng đợi.
- **Bảng Giám Sát Hàng Đợi**: Hiển thị tác phẩm đang dịch, số chương chờ và trạng thái của từng tác phẩm trong hàng đợi.

---

## 5. Phòng Dịch DeepSeek Chuyên Sâu Từng Truyện (`/admin/novel/{id}`)

Khi cần dịch chi tiết, tinh chỉnh hoặc theo dõi trực tiếp một bộ truyện cụ thể:

1. Bấm vào nút **"Phòng Dịch DeepSeek"** ở bộ truyện tương ứng.
2. **Thiết lập dải chương & số luồng**:
   - Nhập dải chương cần dịch: *Từ chương [X] đến chương [Y]*.
   - Số luồng dịch song song (Concurrency): 1 đến 5 luồng (Khuyên dùng: 3 luồng để tối ưu tốc độ và tránh bị rate-limit).
   - Tùy chọn: *Dịch lại chương đã xong* hoặc *Dịch lại chương lỗi*.
3. Bấm **"Bắt Đầu Dịch"**.
4. **Màn hình Live SSE Console**:
   - Toàn bộ sự kiện dịch từng chương, thời gian hoàn thành, tiêu đề tiếng Việt và thông báo lỗi sẽ được truyền phát trực tiếp (Server-Sent Events) lên màn hình terminal đen mà không cần tải lại trang.

---

## 6. Quản Lý Từ Điển Glossary (Quy Chuẩn Danh Xưng)

Để đảm bảo AI dịch đồng nhất 100% tên nhân vật chính, địa danh, công pháp trong suốt bộ truyện:

1. Trong Phòng Dịch của truyện, bấm nút **"Từ Điển Glossary"**.
2. Nhập từ gốc tiếng Trung (Ví dụ: `宁拙`) và bản dịch chuẩn tiếng Việt (Ví dụ: `Ninh Chuyết`).
3. Bấm **"Thêm"**.
4. Toàn bộ từ điển này sẽ được tự động tiêm vào System Prompt của DeepSeek mỗi khi dịch chương của bộ truyện đó!
