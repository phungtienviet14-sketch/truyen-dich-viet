---
name: ui-ux-pro-max
description: >-
  Cung cấp tiêu chuẩn thiết kế UI/UX chất lượng cao (Design Intelligence).
  Áp dụng khi thiết kế hoặc cải tiến giao diện web/mobile, phối màu, typography,
  glassmorphism, micro-interactions và tối ưu trải nghiệm độc giả.
---

# UI/UX Pro Max Design Skill

Hướng dẫn quy chuẩn thiết kế giao diện đỉnh cao, hiện đại và chuẩn mực trải nghiệm người dùng (UX).

## 1. Nguyên Lý Thiết Kế Cốt Lõi (Core Principles)
- **Hierarchy & Contrast (Phân Cấp Thị Giác)**: Mỗi màn hình chỉ có 1 điểm nhấn chính (Primary Focus). Sử dụng độ đậm phông chữ (font weight), kích thước (font size) và độ tương phản màu sắc để hướng ánh nhìn người dùng.
- **Glassmorphism & Depth (Chiều Sâu Không Gian)**:
  - Sử dụng nền bán trong suốt: \g-base-100/90\ hoặc \g-slate-900/80\ kết hợp \ackdrop-blur-xl\.
  - Viền mỏng phát sáng: \order border-emerald-500/20\ hoặc \order-white/10\ để định hình viền thẻ.
  - Đổ bóng nhiều lớp (Multi-layer shadows): \shadow-2xl shadow-emerald-950/40\.
- **Typography Chuẩn Xuất Bản**:
  - Giao diện chung: Sans-serif hiện đại, nét thoáng (\Be Vietnam Pro\, \Plus Jakarta Sans\, \Inter\).
  - Giao diện đọc truyện: Serif trang nhã, giàu nhạc điệu, chống mỏi mắt (\Lora\, \Literata\, \Merriweather\).
  - Dãn dòng chuẩn: 1.8 - 2.0 cho văn bản dài, \letter-spacing: 0.01em\, thụt lề đầu dòng chuẩn sách (.8em\).

## 2. Hệ Thống Màu Sắc & Chủ Đề (Color System)
- **Màu Chủ Đạo (Brand Colors)**:
  - Primary (Tiên Hiệp Emerald): \#10b981\, \#059669\, \#047857\ tượng trưng cho sự huyền bí, thanh cao của tiên hiệp.
  - Secondary/Cyan (Linh Lực): \#06b6d4\, \#0891b2\.
  - Accent/Amber (Trà Đạo / Điểm Thưởng): \#f59e0b\, \#d97706\.
  - Danger/Heart (Yêu Thích): \#f43f5e\, \#e11d48\.
- **4 Chế Độ Đọc Chống Mỏi Mắt**:
  - **Sepia Giấy Cổ Phong**: Nền \#f4ecd8\, chữ \#3b2e1e\, viền \#e2d3b5\.
  - **Trắng Tinh Khôi**: Nền \#ffffff\, chữ \#1f2937\, viền \#e5e7eb\.
  - **Dark Slate Dịu Mắt**: Nền \#1e293b\, chữ \#e2e8f0\, viền \#334155\.
  - **OLED Đen Tuyệt Đối**: Nền \#0b0f19\, chữ \#cbd5e1\, viền \#1e293b\.

## 3. Quy Chuẩn Vi Tương Tác (Micro-Interactions)
- Phản hồi tức thời với âm thanh / hình ảnh (Visual feedback):
  - Nhấp nút Tim Yêu Thích -> Hiệu ứng nở hạt (Heart Burst) và tăng số đếm tức thì.
  - Nhấp Yêu Cầu Dịch -> Hiệu ứng Rocket Launching kèm nhấp nháy ánh sáng.
  - Nhấp Copy STK -> Đổi biểu tượng sang tích xanh và xuất hiện Toast Notification mượt mà.
