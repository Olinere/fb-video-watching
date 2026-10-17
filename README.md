# FB Video Watcher 🎬 & Universal Stream Player

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20(64--bit)-0078D6?logo=windows)](https://github.com/Olinere/fb-video-watching/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-390%20Passed-brightgreen)](tests/)
[![RAM Usage](https://img.shields.io/badge/Memory-~40MB%20RAM-success)](#-1-hiệu-năng-kỷ-lục-40mb-ram--smart-igpu-gaming-mode)

> **FB Video Watcher (FBVW)** là trình phát video desktop thế hệ mới dành cho Windows. Ứng dụng giải quyết triệt để vấn đề "ngốn RAM và giật lag" của trình duyệt khi xem video online bằng cách kết hợp **Lõi giải mã phần cứng libVLC (Direct3D 11)**, **Động cơ bóc tách luồng trực tuyến yt-dlp** và **Giao diện Windows 11 Fluent Design** hiện đại.

---

## 💡 Động cơ & Kiến trúc Cốt lõi (Core Architecture)

**FB Video Watcher** được xây dựng trên một kiến trúc tích hợp sâu gồm 3 tầng:

```
┌────────────────────────────────────────────────────────────────────────┐
│               GIAO DIỆN FLUENT DESIGN (Windows 11 Modern UI)            │
│    Tkinter + sv-ttk │ PiP Multi-Monitor │ Context Menu │ Live Preview   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┴───────────────────────────────┐
    │              ĐỘNG CƠ TRUY XUẤT LUỒNG TRỰC TUYẾN               │
    │  yt-dlp + yt-dlp-ejs │ Custom Resolvers & Stream Adapters      │
    │  In-App Local Stream Proxy (127.0.0.1) + DoH DNS Interceptor   │
    └───────────────────────────────┬───────────────────────────────┘
                                    │ (Direct Stream / HLS / DASH)
    ┌───────────────────────────────▼───────────────────────────────┐
    │                 LÕI PHÁT NATIVE (libVLC 64-bit)                │
    │  Direct3D 11 Hardware Acceleration │ Multi-format Decoders    │
    │  Smart iGPU Offload (Tách tải sang Card On, nhường Card Rời)  │
    └───────────────────────────────────────────────────────────────┘
```

### 1. 🎞️ Lõi giải mã: libVLC 64-bit (VideoLAN Engine)
- Nhúng trực tiếp bề mặt render Direct3D 11 của **libVLC** vào cửa sổ ứng dụng qua Win32 API (`set_hwnd`).
- Thừa hưởng toàn bộ sức mạnh giải mã trâu bò của VLC: hỗ trợ mọi định dạng (MP4, MKV, AVI, WebM, FLV, TS, H.264, H.265/HEVC, AV1, 10-bit HDR, 4K/60fps), không drop khung hình, không phụ thuộc vào codec hệ thống.
- **Tự động thiết lập:** Nếu máy bạn chưa có VLC, ứng dụng sẽ **tự động tải ngầm và cài đặt bản VLC 64-bit chính thức** từ VideoLAN trong lần đầu chạy.

### 2. 🌐 Động cơ trực tuyến: yt-dlp + Custom Resolvers + In-App Stream Proxy
- Tích hợp sâu **yt-dlp**, bộ giải mã JavaScript **yt-dlp-ejs** kết hợp các bộ bóc tách và phân giải luồng trực tuyến:
  - Tự động bóc tách và phát trực tiếp video từ web (Facebook Watch, Reels, video bài viết, YouTube, cùng các nền tảng video phổ biến).
  - Tự động nhận diện variant HLS (`.m3u8`), DASH (`.mpd`), video direct link (`.mp4`), đồng bộ luồng âm thanh và phụ đề trực tiếp.
- **Local Stream Proxy nội bộ (127.0.0.1):** Tự động xử lý Referer spoofing, HTTP Range request và phân phối playlist phân đoạn đa tầng.
- **In-App DoH DNS Interceptor:** Tích hợp bộ giải mã DNS qua HTTPS (Cloudflare, Google) cô lập trong ứng dụng, vượt tường lửa và chặn nhà mạng an toàn 100% mà không can thiệp vào cài đặt mạng Windows hay đòi quyền Admin.

### 3. ⚡ Bộ tối ưu tài nguyên Win32 & Smart iGPU Offload
- **Cơ chế "Xài xong dọn":** Tự động thu hồi Working Set sau mỗi lần tua video, giữ RAM luôn dao động ở mức không tưởng: **~40MB – 70MB RAM**.
- **Smart iGPU Offload (Gaming Mode):** Tự động phát hiện cấu hình Dual GPU (Card Onboard + Card Rời). Điều phối toàn bộ tác vụ giải mã video sang **iGPU** (Intel UHD / AMD Radeon Graphics), giải phóng 100% sức mạnh và VRAM của **card rời** (NVIDIA RTX / AMD Radeon) để bạn thoải mái chơi game nặng mà không lo sụt FPS.

---

## 🚀 Tải về & Sử dụng nhanh (Khuyến nghị)

Người dùng thông thường **không cần cài đặt Python** hay gõ lệnh. Chỉ cần tải bản `.exe` duy nhất:

👉 **Tải bản cài đặt sẵn mới nhất tại: [Release](https://github.com/Olinere/fb-video-watching/releases)**

- **Hệ điều hành:** Windows 10 / Windows 11 (64-bit).
- **Khởi động:** Giải nén và mở `FB-Video-Watcher.exe`. Ứng dụng tích hợp sẵn Single Instance: click đúp nhiều lần chỉ kích hoạt đưa cửa sổ đang chạy lên trên cùng, không mở thừa tiến trình.
- **Tự động cài đặt VLC:** Nếu máy tính chưa có libVLC, ứng dụng sẽ hiện hộp thoại thông báo và tự động tải cài đặt bản VLC 64-bit chính thức an toàn từ VideoLAN.

---

## 🛠️ Dành cho Nhà phát triển (Chạy từ mã nguồn)

```powershell
# 1. Clone kho mã nguồn
git clone https://github.com/Olinere/fb-video-watching.git
cd fb-video-watching

# 2. Tạo và kích hoạt môi trường ảo Python 3.10+
python -m venv .fbwenv
.\.fbwenv\Scripts\activate

# 3. Cài đặt các gói thư viện phụ thuộc
pip install -r requirements.txt

# 4. Khởi chạy ứng dụng
python main.py
```

### Đóng gói ứng dụng thành file `.exe` độc lập:
```powershell
.\build.bat
```
*(File thực thi hoàn chỉnh sẽ được tạo tại thư mục `dist\FB-Video-Watcher.exe`)*

---

## ✨ Chi tiết các tính năng nổi bật

### 🚀 1. Hiệu năng kỷ lục ~40MB RAM & Smart iGPU Gaming Mode
- **Bộ nhớ siêu nhẹ:** Ổn định ở mức **~40MB RAM** khi phát 1080p và sau khi tua video dài nhiều tiếng.
- **Smart iGPU Offload:** Tự động phát hiện vi xử lý và card màn hình. Toàn bộ giải mã video được chuyển sang chip đồ họa tích hợp iGPU (Intel UHD Graphics / AMD Radeon Graphics). Card rời NVIDIA RTX / AMD Radeon được giữ nguyên 100% VRAM và xung nhịp phục vụ Render / Game AAA.
- **Auto-Tuning thích ứng:** Tự động cấu hình bộ đệm mạng (`network-caching=3000ms`, `file-caching=1500ms`), số luồng giải mã theo số nhân CPU thực tế.

### 📌 2. Chế độ Picture-in-Picture (PiP) thông minh
- **Bộ nhớ vị trí đa màn hình (Multi-Monitor Persistence):** Lưu chính xác vị trí $(x, y)$ và kích thước $(w, h)$ độc lập cho từng tỉ lệ **16:9** (video ngang) và **9:16** (video dọc Reels / TikTok / Shorts). Di chuyển PiP sang màn hình phụ, tắt đi bật lại vẫn nằm đúng vị trí.
- **Hít mép thông minh (Snap Margin 24px):** Tự động bám mép màn hình làm việc (`rcWork`), không đè lên Taskbar.
- **Zoom kích thước bằng con lăn chuột:** Lăn chuột trên video PiP để phóng to / thu nhỏ tức thì.

### 🌐 3. Trình bóc tách link & Phân hệ Stream Proxy
- **Hỗ trợ phát đa nguồn trực tuyến:** Tự động phân giải các nguồn video Facebook (Reels, Watch, Video bài viết), YouTube, cùng các trang video hỗ trợ bởi `yt-dlp` và link stream trực tiếp (`.mp4`, `.m3u8`, `.mpd`).
- **Giao thức URI `fbvw://` & Microsoft Edge / Chrome Extension:**
  - `fbvw://play?url=...`: Mở app và phát ngay lập tức.
  - `fbvw://queue?url=...`: Thêm vào hàng đợi phát mà không gián đoạn video hiện tại.
  - Đi kèm Extension Chromium trong thư mục `extension/`: Click chuột phải vào bất kỳ video/link nào trên trình duyệt để "Phát bằng FB Video Watcher".

### 💬 4. Hệ thống phụ đề chuyên sâu 3-trong-1
1. **Phụ đề tệp cục bộ:** Hỗ trợ 12 định dạng (`.srt`, `.vtt`, `.ass`, `.ssa`, `.sub`, `.smi`, `.sami`, `.idx`, `.txt`, `.lrc`, `.ttml`, `.dfxp`). Có bảng **Live Interactive Preview** chỉnh font chữ, cỡ chữ, màu sắc, viền, hộp nền trực quan.
2. **Phụ đề trực tuyến nền tảng:** Tự động lấy phụ đề gốc hoặc phụ đề dịch tự động trực tiếp từ YouTube / Facebook qua TimedText API siêu tốc, hoàn toàn miễn phí.
3. **Phụ đề dịch bằng AI (OpenAI API Standard):** Tích hợp dịch phụ đề thời gian thực theo chuẩn OpenAI API. Tương thích với OpenAI (GPT-4o-mini), Google Gemini, Groq (siêu tốc), DeepSeek, Ollama local. Tự động chia lô (batch 50 cues) giữ nguyên timestamp, không lệch video.

### 📑 5. Hàng đợi thông minh & Phân tích văn bản (SmartTextParser)
- Dán cả bài viết Facebook dài dằng dặc, ứng dụng tự động bóc tách toàn bộ link video hợp lệ, giải mã Facebook Shim redirect, lọc sạch rác tracking (`fbclid`, `si`, `utm_*`), nhận diện tên tập phim (Tập 1, Tập 2...).
- Tự động lưu và khôi phục hàng đợi khi tắt/mở lại app.

---

## ⌨️ Bảng phím tắt mặc định

*Mọi phím tắt đều có thể tùy biến lại theo sở thích trong **⚙ Cài đặt $\rightarrow$ Phím tắt**:*

| Phím tắt | Chức năng | Mô tả |
| :--- | :--- | :--- |
| `Space` | Tạm dừng / Tiếp tục | Bật / tắt trạng thái phát video |
| `Left` / `Right` | Tua lùi / Tua tới ngắn | Mặc định 5 giây |
| `Shift + Left` / `Right` | Tua lùi / Tua tới vừa | Mặc định 10 giây |
| `Ctrl + Left` / `Right` | Tua lùi / Tua tới dài | Mặc định 30 giây |
| `Up` / `Down` | Tăng / Giảm âm lượng | Bước thay đổi 5% |
| `m` | Bật / Tắt âm thanh (Mute) | Chuyển đổi nhanh tắt tiếng |
| `[` / `]` | Giảm / Tăng tốc độ | Điều chỉnh tốc độ từ 0.25x đến 4.0x |
| `=` | Tốc độ chuẩn 1.0x | Đặt lại tốc độ bình thường |
| `f` hoặc `Double Click` | Toàn màn hình | Bật / tắt toàn màn hình đúng display |
| `p` | Chế độ thu nhỏ PiP | Cửa sổ nổi không viền luôn trên cùng |
| `Ctrl + p` | Đổi tỉ lệ PiP (16:9 ↔ 9:16) | Chuyển đổi giữa chế độ ngang và dọc |
| `l` | Lặp lại video (Loop) | Lặp lại liên tục video đang phát |
| `a` / `b` / `c` | Lặp đoạn A-B | Đánh dấu điểm A, điểm B và hủy lặp A-B |
| `Ctrl + o` | Mở tệp video | Chọn và phát video từ ổ cứng máy tính |
| `Ctrl + h` | Lịch sử xem video | Xem lại các video đã phát gần đây |
| `Ctrl + s` | Tải video / Âm thanh MP3 | Tải media về máy tính |
| `Ctrl + ,` | Cài đặt ứng dụng | Cấu hình mạng, phụ đề, phím tắt, giao diện |
| `Ctrl + Shift + Q` | Bảng hàng đợi phát | Quản lý danh sách phát |
| `Escape` | Thoát Fullscreen / PiP | Trở về cửa sổ chính |
| `Chuột phải vào video` | Menu ngữ cảnh | Chọn audio track, subtitle, tỷ lệ khung hình |

---

## 🧪 Kiểm thử tự động (Unit Tests)

Dự án sở hữu bộ kiểm thử tự động toàn diện với **390 unit tests vượt qua 100%**:

```powershell
.\.fbwenv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

```text
Ran 390 tests in 201.043s
OK
```

---

## 📄 Giấy phép (License)

Dự án này được phát hành dưới giấy phép **[GNU General Public License v3.0 (GPL-3.0)](LICENSE)**.
Mọi mã nguồn đều công khai, minh bạch, phi thương mại và phục vụ cộng đồng.
