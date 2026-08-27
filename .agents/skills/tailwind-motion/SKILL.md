---
name: tailwind-motion
description: >-
  Quy chuẩn và thư viện hiệu ứng chuyển động, animation mượt mà bằng Tailwind CSS & CSS3.
  Sử dụng cho hiệu ứng hover 3D, floating widgets, shimmer, glowing gradients và page transitions.
---

# Tailwind Motion & Smooth Animation Skill

Tập hợp các hiệu ứng chuyển động mượt mà (60fps hardware-accelerated animations) cho website.

## 1. Bảng Hiệu Ứng Chuyển Động Chuẩn (Keyframe Presets)

### A. Float & Glow (Trôi nổi & Tỏa sáng mờ)
\\css
@keyframes floatGentle {
  0%, 100% { transform: translateY(0px); }
  50% { transform: translateY(-6px); }
}
@keyframes pulseGlow {
  0%, 100% { box-shadow: 0 0 15px rgba(16, 185, 129, 0.2); }
  50% { box-shadow: 0 0 25px rgba(16, 185, 129, 0.45); }
}
\
### B. Shimmer & Skeleton (Ánh sáng lướt qua)
\\css
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
\
### C. Spring Modal & Drawer (Lò xo mở hộp thoại)
\\css
@keyframes springIn {
  0% { opacity: 0; transform: scale(0.92) translateY(10px); }
  70% { opacity: 1; transform: scale(1.02) translateY(-2px); }
  100% { opacity: 1; transform: scale(1) translateY(0); }
}
\
### D. Heart Burst & Particle Splash
\\css
@keyframes heartBeat {
  0% { transform: scale(1); }
  25% { transform: scale(1.3) rotate(-5deg); }
  50% { transform: scale(0.95); }
  75% { transform: scale(1.15) rotate(3deg); }
  100% { transform: scale(1); }
}
\
## 2. Quy Tắc Áp Dụng Chuyển Động
- Không lạm dụng làm rối mắt: Thời gian chuyển động tối ưu là 200ms - 400ms với easing \cubic-bezier(0.16, 1, 0.3, 1)\.
- Tôn trọng thuộc tính hệ thống: Tự động vô hiệu hóa chuyển động nặng nếu người dùng bật \prefers-reduced-motion\.
