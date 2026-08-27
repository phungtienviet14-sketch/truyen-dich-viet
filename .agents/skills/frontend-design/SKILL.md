---
name: frontend-design
description: >-
  Tiêu chuẩn lập trình giao diện Frontend chuyên nghiệp, thẩm mỹ cao (Production-Grade UI).
  Áp dụng khi tạo dựng layout, card, button, modal, thanh điều hướng và tối ưu responsive.
---

# Frontend Design Standards

Quy chuẩn tạo lập giao diện người dùng sản xuất thực tế, loại bỏ phong cách AI chung chung và nâng tầm thẩm mỹ.

## 1. Loại Bỏ Sự Đơn Điệu (Eliminate Generic AI Slop)
- Không dùng các thẻ phẳng đơn điệu thiếu điểm nhấn hoặc phông mặc định không căn chỉnh.
- Sử dụng hiệu ứng chuyển màu tinh tế (Subtle Gradients): \g-gradient-to-br from-slate-900 via-slate-900/90 to-emerald-950/40\.
- Tạo chiều sâu thẻ sách bằng hiệu ứng phản chiếu ánh sáng và viền phát quang linh động khi hover.

## 2. Thiết Kế Responsive & Tối Ưu Mọi Màn Hình
- Mobile-first: Đảm bảo các nút bấm có kích thước tối thiểu 44x44px (touch target), thanh công cụ đọc sticky không che khuất nội dung.
- Floating Docks: Tận dụng thanh điều hướng nổi bo tròn (floating capsule navbar) trên di động.
- Tránh vỡ layout: Dùng \line-clamp-1\, \line-clamp-2\, \	runcate\ và tự động co dãn cột grid (\grid-cols-1 sm:grid-cols-2 lg:grid-cols-3\).

## 3. Quản Lý Trạng Thái Giao Diện (State & Feedback)
- Loading Skeletons mượt mà thay vì màn hình trống trơn.
- Toast thông báo dạng Glass Card nổi ở góc màn hình, tự trượt vào và tự mờ dần biến mất sau 3 giây.
- Empty states có hình minh họa và nút kêu gọi hành động (Call To Action) rõ ràng.
