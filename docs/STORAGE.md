# Dung lượng lưu trữ và cơ chế Neon

Đo thật ngày 28/08/2026 trên thư viện 149 truyện / 412.177 chương.

## 1. Câu hỏi: tạo nhiều database Neon để lưu thêm được không?

Câu trả lời phụ thuộc vào việc "nhiều database" nghĩa là gì. Neon có ba tầng, và **chỉ một tầng thực sự nhân thêm dung lượng**.

| Tầng | Hạn mức gói Free | Có nhân thêm dung lượng? |
| --- | --- | --- |
| **Database** trong một branch | Không giới hạn số lượng | **Không.** Mọi database dùng chung dung lượng của project |
| **Branch** trong một project | 10 branch/project | **Không.** Branch là copy-on-write, tính vào cùng hạn mức |
| **Project** | 100 project/tài khoản | **Có.** Mỗi project có 0,5 GB riêng |

Nguồn: [Neon plans](https://neon.com/docs/introduction/plans). Tài khoản này hiện đã có 4 project.

Nghĩa là: `CREATE DATABASE` thêm trong project `truyen-dich-viet` **không giúp gì cả** — vẫn chung 0,5 GB. Muốn thêm dung lượng thật thì phải tạo **project mới**, và mỗi project là một Postgres tách biệt: chuỗi kết nối riêng, compute riêng, **không JOIN được với nhau**.

### Hai giới hạn không thoát được bằng cách chia project

- **Băng thông mạng 5 GB/tháng tính trên cả tài khoản**, không phải trên từng project. Chia bao nhiêu project cũng không tăng.
- **100 CU-hour/tháng cho mỗi project** — cái này thì có nhân lên, là điểm cộng.

## 2. Hiện trạng đo được

Bảng `chapters`, tổng 185,5 MB:

| Thành phần | Dung lượng |
| --- | --- |
| Index | **82,7 MB** |
| Heap (dòng dữ liệu) | 61,7 MB |
| TOAST (nội dung chương) | 41,1 MB |

**Index chiếm nhiều hơn cả nội dung truyện.** Đây là chỗ cần xử lý trước khi nghĩ tới việc mua thêm dung lượng.

### Chi tiết index

| Index | Dung lượng | Lượt quét | Nhận xét |
| --- | --- | --- | --- |
| `uq_chapter_source` (novel_id, url) | 36,2 MB | 412.345 | Dùng nhiều, nhưng URL dài nên rất tốn |
| `uq_chapter_index` (novel_id, chapter_index) | 9,0 MB | 2 | Ràng buộc unique, cần giữ |
| `ix_novel_chapter_index` (novel_id, chapter_index) | 9,0 MB | 166 | **Trùng hoàn toàn với dòng trên** |
| `ix_chapters_id` | 9,0 MB | 13.002 | **Trùng với khoá chính** |
| `chapters_pkey` | 9,0 MB | 0 | Trùng với dòng trên |
| `ix_chapters_chapter_index` | 4,0 MB | 48 | Hiếm khi truy vấn mà không kèm novel_id |
| `ix_chapters_status` | 3,2 MB | 260 | Dùng cho hàng đợi dịch |
| `ix_chapters_novel_id` | 3,1 MB | 978 | Là tiền tố trái của `uq_chapter_index` |

Ít nhất **21 MB trùng lặp thuần tuý** (`ix_novel_chapter_index` + `ix_chapters_id` + `ix_chapters_novel_id`), và con số này lớn dần theo số chương. Nguyên nhân trong `app/models.py`: đặt `index=True` trên cột đã là `primary_key`, và khai báo `Index()` trùng với `UniqueConstraint()` cùng cột.

### Nén

| Cách | Tỷ lệ | KB/chương |
| --- | --- | --- |
| Không nén (logic) | 1,00x | 8,8 |
| **TOAST `pglz` (đang dùng)** | **1,35x** | **6,5** |
| gzip từng chương, đọc độc lập được | 1,96x | 4,5 |
| gzip toàn khối | 2,50x | 3,5 |
| lzma / bz2 toàn khối | 3,35x / 3,49x | 2,6 / 2,5 |

Postgres đã tự nén sẵn 1,35x. Nén ở tầng ứng dụng chỉ lời thêm khoảng **1,45 lần** so với hiện tại, không phải 2x như con số thô gợi ý.

## 3. Các phương án, kèm số thật

Nếu lưu raw cho toàn bộ 412.177 chương: khoảng **2,7 GB** (theo 6,5 KB/chương trên đĩa) — gấp hơn 5 lần gói Free.

| Phương án | Lợi | Chi phí thật |
| --- | --- | --- |
| **Dọn index trùng** | Thu hồi ~21 MB ngay, và tỷ lệ thuận khi thư viện lớn | Thấp: sửa `models.py`, migration bỏ index |
| **Không lưu raw đại trà** | Bỏ hẳn 2,7 GB | Không mất chức năng: `dispatcher` vốn tự nạp raw lúc dịch. Mất lớp phòng vệ khi nguồn biến mất |
| **Nén ở tầng ứng dụng** | 2,7 GB xuống ~1,9 GB | Vẫn vượt hạn mức; mất khả năng tìm kiếm toàn văn trong nội dung |
| **Tách theo loại dữ liệu, 2 project** | Metadata (144 MB) ở project A; nội dung ở project B | Nội dung chỉ truy cập theo khoá chính nên **không cần JOIN** — đây là ranh giới chia hợp lý nhất |
| **Chia nhỏ theo truyện (sharding)** | Nhân dung lượng tuỳ ý | **Làm hỏng bảng xếp hạng và tìm kiếm**: cả hai truy vấn trên toàn bộ bảng `novels`. Phải gom kết quả từ nhiều shard |
| **Object storage (Cloudflare R2)** | 10 GB miễn phí, không tính phí egress | Đúng công cụ cho blob; thêm một phụ thuộc vận hành |

## 4. Khuyến nghị

Theo thứ tự nên làm:

1. **Dọn index trùng trước.** Rẻ nhất, không đổi kiến trúc, và hiện đang lãng phí nhiều hơn cả phần nội dung đang lưu.
2. **Xem lại có thật sự cần lưu raw đại trà không.** Raw là lớp phòng vệ, không phải điều kiện để đọc hay để dịch. Cân nhắc chỉ lưu raw cho truyện đã dịch hoặc được ưu tiên.
3. **Nếu vẫn cần thêm dung lượng: tách theo loại dữ liệu, không chia theo truyện.** Nội dung chương chỉ được đọc theo `chapter_id`, không bao giờ JOIN hay tìm kiếm — chia ở đó không phá vỡ tính năng nào. Chia theo truyện thì phá bảng xếp hạng và tìm kiếm.
4. **Cân nhắc R2 thay vì project Neon thứ hai** nếu đã đi tới bước 3: 10 GB miễn phí, và đó là đúng loại kho cho dữ liệu chỉ đọc theo khoá.

Đừng quên trần **5 GB băng thông/tháng cho cả tài khoản** — không phương án chia nào ở trên nới được giới hạn này.

## 5. Chốt chặn đang hoạt động

`CRAWLER_RAW_BUDGET_MB` (mặc định 400) dừng lưu nội dung raw khi database chạm ngưỡng, nhưng **vẫn tiếp tục đồng bộ mục lục** — vì mục lục là thứ khiến truyện xuất hiện trong thư viện và rẻ hơn 10 lần. Xem `_fetch_raw()` trong `app/crawler/auto_updater.py`.

## 6. Nhiều tài khoản Neon?

Không cần, và không nên.

**Không cần:** một tài khoản đã cho 100 project, mỗi project 0,5 GB — tối đa khoảng 50 GB. Nhu cầu lưu raw toàn bộ là ~2,7 GB, tức khoảng 6 project. Còn rất xa trần của một tài khoản.

**Không nên:** tạo nhiều tài khoản nhằm lách hạn mức là hành vi nhà cung cấp thường xử lý bằng cách khoá tài khoản, đồng nghĩa mất dữ liệu. Rủi ro lớn hơn nhiều so với thứ thu được.

Và nó **không giải quyết được nút thắt thật**: 5 GB băng thông mỗi tháng tính trên cả tài khoản. Nếu trang phục vụ nội dung chương trực tiếp từ Neon, đây mới là trần chạm trước — không phải dung lượng lưu trữ.
