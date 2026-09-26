# FB Video Watcher 🎬 & Universal Video Streamer

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20(64--bit)-0078D6?logo=windows)](https://github.com/Olinere/fb-video-watching/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-296%20Passed-brightgreen)](tests/)
[![RAM Usage](https://img.shields.io/badge/Memory-~40MB%20RAM-success)](#-kiến-trúc-tiết-kiệm-tài-nguyên--xài-xong-dọn)

> Ứng dụng xem video desktop siêu nhẹ, tối ưu hóa phần cứng vượt trội với lõi VLC Media Player nhúng. Hỗ trợ phát đa nền tảng (Facebook, YouTube, TikTok, Douyin, Bilibili, Instagram, Twitter/X và link direct video), chế độ PiP 16:9 / 9:16 thông minh, tùy biến phím tắt linh hoạt và hệ thống phụ đề đa định dạng chuyên nghiệp với khung Live Preview trực quan.

---

## 🚀 Tải về & Sử dụng nhanh (Khuyến nghị)

Người dùng thông thường **không cần cài đặt Python** hay gõ lệnh. Bạn chỉ cần tải bản `.exe` dựng sẵn:

👉 **Tải bản cài đặt sẵn mới nhất (.exe) tại: [Releases · Olinere/fb-video-watching](https://github.com/Olinere/fb-video-watching/releases)**

- **Yêu cầu:** Windows 10/11 64-bit.
- **Tiện ích đi kèm:** Nếu máy tính của bạn chưa có VLC Media Player, ứng dụng sẽ **tự động tải và cài đặt ngầm bản VLC 64-bit chính thức** từ VideoLAN trong lần đầu chạy.

---

## 🛠️ Dành cho Nhà phát triển (Chạy từ mã nguồn)

Nếu bạn muốn đóng góp hoặc chạy trực tiếp từ mã nguồn Python:

### 1. Yêu cầu môi trường
- Python 3.10 trở lên (64-bit).
- Hệ điều hành Windows 10/11.

### 2. Cài đặt & Khởi chạy

```powershell
# 1. Clone mã nguồn
git clone https://github.com/Olinere/fb-video-watching.git
cd fb-video-watching

# 2. Tạo môi trường ảo (khuyến nghị)
python -m venv .venv
.\.venv\Scripts\activate

# 3. Cài đặt các gói phụ thuộc
pip install -r requirements.txt

# 4. Khởi chạy ứng dụng
python main.py
```

---

## ✨ Tính năng nổi bật

### 🚀 1. Hiệu năng siêu nhẹ & Smart iGPU Offload (Gaming Mode)
- **Tiêu thụ cực ít tài nguyên (Kỷ lục ~40MB RAM):** Chỉ chiếm **~35–45MB RAM** khi phát 1080p hoặc sau khi tua video dài 10 tiếng (so với 1GB–2GB+ khi xem trên Chrome/Edge/Firefox), CPU nhàn rỗi chỉ **~0.4%**.
- **Cơ chế "Xài xong dọn" (Use & Clean Memory Lifecycle):** Tự động dọn Working Set qua Win32 API 64-bit sau mỗi lần tua/nhảy mốc thời gian (Debounce 2.5s), giữ cho tiến trình luôn gọn gàng.
- **Smart iGPU Offload (Gaming Mode cho Card kép):** Tự động phân tích vi xử lý và điều phối DirectX 11 runtime chuyển 100% tác vụ giải mã video sang iGPU (Intel UHD Graphics / AMD Radeon Graphics). Nhờ đó, card đồ họa rời (NVIDIA RTX / AMD Radeon) được giải phóng toàn bộ sức mạnh và VRAM để chơi game FPS cao mà không lo sụt khung hình.
- **Auto-Tuning thông minh:** Tự động nhận diện cấu hình CPU, GPU, RAM để tinh chỉnh kích thước bộ đệm mạng (Network caching 1000–5000ms) và số luồng giải mã tối ưu nhất.

### 📌 2. Chế độ Picture-in-Picture (PiP) đa tỷ lệ & Đa màn hình
- **Ghi nhớ vị trí đa màn hình (Multi-Monitor Persistence):** Lưu chính xác vị trí $(x, y)$ và kích thước $(w, h)$ độc lập cho từng tỉ lệ 16:9 và 9:16. Khi di chuyển PiP sang Màn hình 2, Màn hình 3... và tắt/bật lại, PiP giữ nguyên đúng vị trí người dùng đã đặt thay vì bị giật về góc màn hình chính. Tự động fallback an toàn nếu ngắt kết nối màn hình phụ.
- **Tự động hít mép màn hình (Snap Margin 24px):** Căn theo vùng làm việc thực tế (`rcWork`, trừ Taskbar) của màn hình đang chứa PiP.
- **Hỗ trợ 2 tỷ lệ chuẩn:** 16:9 (Ngang chuẩn) và 9:16 (Dọc chuẩn cho Reels, TikTok, Shorts). Tự động xoay PiP khi phát video dọc.
- **Zoom kích thước bằng con lăn chuột:** Lăn chuột trên video PiP để phóng to / thu nhỏ cửa sổ cực kỳ mượt mà.

### 🌐 3. Phát video đa nền tảng & Tích hợp Windows Custom URI (`fbvw://`)
- **Đa nền tảng:** Facebook (Reels, Watch, Group), YouTube, TikTok, Douyin, Bilibili, Instagram, Twitter/X và link trực tiếp (`.mp4`, `.m3u8`, `.mpd`).
- **Giao thức URI `fbvw://`:** Mở video từ trình duyệt web chỉ bằng 1 cú click:
  - `fbvw://play?url=...`: Mở app và phát ngay lập tức.
  - `fbvw://queue?url=...`: Âm thầm xếp video vào hàng đợi phát mà không ngắt quãng video đang xem.
  - Hỗ trợ chế độ riêng tư: `&privacy=1`.
- **Single-Instance IPC (Named Pipe):** Khi click nhiều link liên tiếp, Windows không mở thêm nhiều cửa sổ mà chuyển tiếp yêu cầu sang cửa sổ đang chạy.

### 🔒 4. Phân hệ Proxy & DNS Mã Hóa Cô Lập (In-App DoH)
- **Vượt chặn ISP độc lập:** Vượt chặn DNS Poisoning, SNI filter hoàn toàn cô lập trong tiến trình ứng dụng.
- **Tuyệt đối an toàn:** Không thay đổi Card mạng (Network Adapter), không can thiệp Windows Registry mạng, không cần quyền Administrator.
- **Mặc định TẮT / Direct:** Tôn trọng tối đa quyền kiểm soát của người dùng.
- **Hỗ trợ đa giao thức:** HTTP, HTTPS, SOCKS5, SOCKS5h kèm xác thực mật khẩu an toàn.
- **DNS-over-HTTPS:** Tích hợp Cloudflare (`1.1.1.1`), Google (`8.8.8.8`), Quad9, AdGuard với bộ đệm LRU $< 50\text{KB}$ RAM.

### 💬 5. Hệ thống phụ đề đa định dạng chuyên nghiệp
- **Hỗ trợ toàn diện:** `.srt`, `.vtt`, `.ass`, `.ssa`, `.sub`, `.smi`, `.sami`, `.idx`, `.txt`, `.lrc`, `.ttml`, `.dfxp`.
- **Kiểm tra tính hợp lệ (Format Validation):** Tự động lọc file lỗi, timestamp sai cú pháp.
- **Live Interactive Preview trong Cài đặt:** Tùy chỉnh trực quan phông chữ, cỡ chữ, màu sắc, viền chữ, khung nền và độ mờ đục với khung mô phỏng trực tiếp theo thời gian thực.

### 📑 6. Hàng đợi phát (Queue) & SmartTextParser
- **Bóc tách thông minh từ văn bản thô:** Dán cả bài viết Facebook dài dằng dặc, ứng dụng tự động bóc tách toàn bộ link video hợp lệ, giải mã Facebook Shim, gọt sạch tracking rác (`fbclid`, `si`, `utm_*`), và nhận diện ngữ cảnh (Tập 1, Tập 2...).
- **Lưu trữ & Khôi phục hàng đợi:** Tự động nhớ danh sách phát khi tắt/mở app (tuân thủ nghiêm ngặt khi bật Privacy Session).
- **Xuất danh sách:** Hỗ trợ xuất ra file `.txt`, `.json`, hoặc danh sách phát media tiêu chuẩn `.m3u`.

---

## ⌨️ Bảng phím tắt mặc định

Tất cả phím tắt dưới đây đều có thể tùy biến lại theo ý muốn trong **⚙ Cài đặt $\rightarrow$ Phím tắt**:

| Phím tắt | Chức năng | Mô tả chi tiết |
| :--- | :--- | :--- |
| `Space` | Tạm dừng / Tiếp tục phát | Bật / tắt trạng thái phát video |
| `Left` / `Right` | Tua lùi / Tua tới ngắn | Mặc định 5 giây (tùy chỉnh được) |
| `Shift + Left` / `Right` | Tua lùi / Tua tới trung bình | Mặc định 10 giây (tùy chỉnh được) |
| `Ctrl + Left` / `Right` | Tua lùi / Tua tới dài | Mặc định 30 giây (tùy chỉnh được) |
| `Up` / `Down` | Tăng / Giảm âm lượng | Mức thay đổi 5% mỗi lần nhấn |
| `m` | Tắt / Bật tiếng (Mute) | Chuyển đổi nhanh âm thanh |
| `[` / `]` | Giảm / Tăng tốc độ phát | Điều chỉnh tốc độ từ 0.25x đến 4.0x |
| `=` | Khôi phục tốc độ chuẩn | Đặt lại tốc độ phát về 1.0x |
| `f` hoặc `Double Click` | Bật / Tắt Toàn màn hình | Phóng to toàn màn hình đúng display |
| `p` | Bật / Tắt chế độ thu nhỏ PiP | Cửa sổ nổi không viền luôn trên cùng |
| `Ctrl + p` | Đổi tỉ lệ khung hình PiP (16:9 ↔ 9:16) | Chuyển đổi giữa chế độ ngang và dọc |
| `l` | Bật / Tắt lặp lại video | Lặp lại liên tục video đang phát |
| `a` | Đặt Điểm A (Lặp A-B) | Đánh dấu mốc bắt đầu đoạn lặp |
| `b` | Đặt Điểm B (Lặp A-B) | Đánh dấu mốc kết thúc và bắt đầu lặp |
| `c` | Xóa đoạn lặp A-B | Đưa chế độ phát về bình thường |
| `Ctrl + o` | Mở hộp thoại chọn file video | Mở file video có sẵn từ ổ đĩa máy tính |
| `Ctrl + h` | Mở hộp thoại Lịch sử xem video | Xem lại các video đã phát gần đây |
| `Ctrl + s` | Mở chức năng Tải video về máy | Tải video hoặc trích xuất âm thanh MP3 |
| `Ctrl + ,` | Mở cửa sổ Cài đặt ứng dụng | Tùy chỉnh chất lượng, phụ đề, phím tắt |
| `Ctrl + Shift + Q` | Bật / Tắt bảng Danh sách phát & Hàng đợi | Xem và quản lý danh sách video chờ phát |
| `PageDown` / `PageUp` | Chuyển video kế tiếp / trước đó | Điều khiển danh sách phát |
| `F12` hoặc `Ctrl + Shift + D`| Bật / Tắt bảng Devlog chẩn đoán | Xem chi tiết thông số kết nối và luồng |
| `Escape` | Thoát Toàn màn hình / Thoát PiP | Trở về cửa sổ giao diện chính |
| `Chuột phải vào video` | Mở Menu ngữ cảnh | Nạp phụ đề, chỉnh tỉ lệ, chọn chất lượng |

---

## 🧪 Kiểm thử tự động (Unit Tests)

Dự án sở hữu bộ kiểm thử tự động toàn diện bao gồm **29 test files với 296 unit tests vượt qua 100%**:

```powershell
.\.fbwenv\Scripts\python.exe -m unittest discover tests
```

```text
Ran 296 tests in 62.702s
OK
```

---

## 📄 Giấy phép (License)

Dự án này được phát hành dưới giấy phép **[GNU General Public License v3.0 (GPL-3.0)](LICENSE)**.

Bất kỳ ai cũng có quyền tự do sử dụng, nghiên cứu, chia sẻ và sửa đổi mã nguồn. Mọi sản phẩm phân phối phái sinh bắt buộc phải công khai toàn bộ mã nguồn theo cùng giấy phép GPL-3.0 và ghi nhận bản quyền tác giả gốc.
