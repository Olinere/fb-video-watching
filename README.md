# FB Video Watcher 🎬 & Universal Stream Player

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20(64--bit)-0078D6?logo=windows)](https://github.com/Olinere/fb-video-watching/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-413%20Passed-brightgreen)](tests/)
[![RAM Usage](https://img.shields.io/badge/Memory-~40MB%20RAM-success)](#-tại-sao-ứng-dụng-làm-được-như-vậy-deep-technical-explanation)

> **FB Video Watcher (FBVW)** là trình phát video desktop thế hệ mới dành cho hệ điều hành Windows (64-bit). Ứng dụng giải quyết triệt để vấn đề "ngốn RAM, nóng máy và tụt FPS khi chơi game" của trình duyệt web bằng cách kết hợp **Lõi giải mã phần cứng libVLC (Direct3D 11)**, **Động cơ phân giải luồng thông minh yt-dlp & Universal Web Crawler**, **In-App Local Stream Proxy**, và **Giao diện Windows 11 Fluent Design** hiện đại.

<img width="1911" height="811" alt="image" src="https://github.com/user-attachments/assets/f2791d7f-b796-40ef-92b2-8bce31872ef2" />

---

## 📑 Mục lục
1. [Ứng dụng làm được những gì? (Capabilities & Features)](#-ứng-dụng-làm-được-những-gì-capabilities--features)
2. [Lõi công nghệ (Core Architecture)](#-lõi-công-nghệ-core-architecture)
3. [Tại sao ứng dụng làm được như vậy? (Deep Technical Explanation)](#-tại-sao-ứng-dụng-làm-được-như-vậy-deep-technical-explanation)
4. [Hướng dẫn sử dụng (User Guide)](#-hướng-dẫn-sử-dụng-user-guide)
   - [Dành cho người dùng phổ thông (Bản .exe cài sẵn)](#1-dành-cho-người-dùng-phổ-thông-khuyến-nghị)
   - [Dành cho lập trình viên (Chạy từ mã nguồn)](#2-dành-cho-nhà-phát-triển-chạy-từ-mã-nguồn)
   - [Bảng phím tắt điều khiển](#3-bảng-phím-tắt-mặc-định-hotkeys)
5. [Đảm bảo chất lượng & Kiểm thử tự động](#-đảm-bảo-chất-lượng--kiểm-thử-tự-động-unit-tests)
6. [Giấy phép (License)](#-giấy-phép-license)

---

## 🎯 Ứng dụng làm được những gì? (Capabilities & Features)

### 1. 🌐 Phát video trực tuyến từ mọi nguồn web (Universal Online Streaming)
- **Nền tảng mạng xã hội & video phổ biến:**
  - **YouTube:** Phát video tiêu chuẩn, YouTube Shorts, YouTube Live. Tự động biên dịch Master Manifest HLS `.m3u8` kết hợp đồng bộ âm thanh và hình ảnh, tua tức thì (instant seek) không lệch tiếng.
  - **Facebook:** Phát Facebook Watch, Facebook Reels, video trong bài viết cá nhân, Fanpage, Group công khai lẫn Group kín (hỗ trợ file Cookies).
  - **TikTok & Douyin:** Phát video ngắn, tự động nhận diện khung hình dọc để mở rộng giao diện phù hợp.
  - **Bilibili, Dailymotion, Vimeo, v.v.:** Bóc tách luồng phát gốc chất lượng cao nhất (1080p, 2K, 4K).
- **Trình bóc tách web phổ quát (Universal Mechanism-Driven Web Extractor):**
  - Xem video trên **bất kỳ website nào** (web phim, anime, giải trí, cyberlocker...): tự động crawl sâu xuyên qua các lớp bảo vệ JavaScript động, iframe lồng nhau, bộ nén Dean Edwards (`eval(function(p,a,c,k,e,d)...)`), Google Blogger `c-wiz` RPC protocol, và các endpoint AJAX CMS động (`/api/player`, `/get.video.php`).
- **Luồng stream trực tiếp & Tệp đa phương tiện:**
  - Nhận diện và phát trực tiếp các định dạng luồng: HLS (`.m3u8`), DASH (`.mpd`), Direct MP4, WebM, FLV.
  - Phát video trực tiếp từ **Telegram Channel / Group** thông qua streaming từng phần mà không cần tải cả tệp hàng gigabyte về ổ cứng.
  - Phát toàn bộ các tệp video offline có sẵn trên máy tính (MP4, MKV, AVI, MOV, TS, WMV...).

### 2. ⚡ Tích hợp giao thức hệ thống `fbvw://`
- **Giao thức URI hệ thống:** Hỗ trợ lệnh gọi từ bên thứ ba, script tự động hoặc command line qua `fbvw://play?url=<link>` và `fbvw://queue?url=<link>`. Tự động kích hoạt cửa sổ ứng dụng và nạp phát video tức thì.

### 3. 📌 Chế độ Picture-in-Picture (PiP) thông minh đa màn hình
- **Ghi nhớ tọa độ & kích thước độc lập:** Tự động lưu vị trí $(x, y)$ và kích thước $(w, h)$ riêng biệt cho cả 2 chế độ: **16:9** (video ngang thông thường) và **9:16** (video dọc Reels / Shorts / TikTok).
- **Hỗ trợ đa màn hình chuẩn xác:** Đưa PiP sang màn hình phụ thứ hai hoặc thứ ba; khi bật/tắt hoặc khởi động lại, cửa sổ nổi luôn xuất hiện chính xác tại màn hình đó.
- **Hít mép làm việc (Snap Margin 24px):** Tự động bám dính vào các cạnh màn hình mà không che lấp Taskbar.
- **Thao tác nhanh:** Phóng to / thu nhỏ linh hoạt bằng cách cuộn con lăn chuột trên video PiP.

### 4. 💬 Hệ thống phụ đề 3-trong-1 chuyên sâu
1. **Phụ đề tệp cục bộ:** Hỗ trợ 12 định dạng phụ đề (`.srt`, `.vtt`, `.ass`, `.ssa`, `.sub`, `.smi`, `.sami`, `.idx`, `.txt`, `.lrc`, `.ttml`, `.dfxp`). Có bảng xem trước trực quan (**Live Interactive Preview**) cho phép chỉnh font chữ, kích cỡ, màu chữ, viền chữ, và hộp nền mờ.
2. **Phụ đề nền tảng trực tuyến:** Tự động trích xuất phụ đề gốc hoặc phụ đề dịch sẵn từ YouTube và Facebook thông qua API TimedText siêu tốc, đồng bộ chuẩn xác từng mili-giây.
3. **Phụ đề dịch bằng AI thời gian thực:** Tích hợp API dịch thuật chuẩn OpenAI (tương thích OpenAI GPT-4o-mini, Google Gemini, Groq, DeepSeek, Ollama local...). Tự động chia lô batch thông minh, giữ nguyên timestamp và cấu trúc cue mà không làm lệch nhịp video.

### 5. 📑 Hàng đợi thông minh & Phân tích văn bản (SmartTextParser)
- Cho phép dán nguyên cả đoạn văn bản bài viết dài dặc (ví dụ bài chia sẻ phim trên Facebook), ứng dụng tự động bóc tách tất cả các liên kết video hợp lệ, giải mã URL chuyển tiếp Facebook Shim (`l.facebook.com`), loại bỏ toàn bộ mã theo dõi rác (`fbclid`, `si`, `utm_*`), và nhận diện số thứ tự tập phim.
- Tự động lưu trữ hàng đợi vào đĩa và khôi phục nguyên vẹn trạng thái danh sách phát khi mở lại ứng dụng.

### 6. 📥 Tải video & trích xuất âm thanh (Downloader)
- Tích hợp công cụ tải media trực tiếp về máy tính: cho phép lựa chọn chất lượng tải (từ 360p đến 4K) hoặc trích xuất riêng bản âm thanh MP3 chất lượng cao.

---

## 🏛️ Lõi công nghệ (Core Architecture)

Kiến trúc của **FB Video Watcher** được thiết kế phân tầng triệt để, đảm bảo tính trừu tượng hóa cao và độc lập giữa các module:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    TẦNG GIAO DIỆN (Windows 11 Fluent UI)                         │
│   Tkinter + sv-ttk │ PiP Multi-Monitor │ Context Menu │ OSD & Skeleton Overlay  │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────┴────────────────────────────────────────┐
│               TẦNG ĐIỀU PHỐI & PHÂN GIẢI LUỒNG (Universal Resolver)             │
│   yt-dlp + yt-dlp-ejs │ Universal Generic Web Crawler (BFS 6 Tầng)              │
│   Google Blogger c-wiz Decoder │ External Script Bundle AST Prober              │
│   Idempotency Guard & Stale Future Filter (Chống Race Condition)                │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────┴────────────────────────────────────────┐
│             TẦNG MẠNG & AN TOÀN TRUYỀN THÔNG (In-App Network Shield)            │
│   Local Stream Proxy (127.0.0.1) │ Sub-segment Manifest Rewriter                │
│   In-App DoH DNS Interceptor (Google/Cloudflare RFC 8427 - Zero OS pollution)   │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │ (HLS / DASH / MP4 stream)
┌────────────────────────────────────────▼────────────────────────────────────────┐
│                     LÕI PHÁT NATIVE (libVLC 64-bit Engine)                      │
│   Direct3D 11 HWND Embedding │ Multi-GPU AutoTuner (iGPU QuickSync Offload)     │
│   Win32 Memory Working Set Recycler ("Xài xong dọn" ~40MB RAM)                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

1. **Lõi giải mã libVLC 64-bit (VideoLAN Engine):**
   - Trực tiếp nhúng bề mặt render DirectX Direct3D 11 của thư viện `libvlc.dll` vào HWND của cửa sổ Tkinter thông qua Win32 API.
   - Giải mã phần cứng native mọi codec video phức tạp nhất: H.264, H.265/HEVC, AV1, VP9, 10-bit HDR mà không phụ thuộc vào codec cài trên hệ điều hành.
2. **In-App Local Stream Proxy (127.0.0.1):**
   - Máy chủ HTTP Stream Proxy nội bộ chạy ngầm trên tiến trình loopback, đóng vai trò trạm trung chuyển dữ liệu media.
   - Tự động vượt qua các cơ chế chống hotlink (Anti-Hotlink, CORS, Referer validation) và chia tách luồng HLS đa phân đoạn.
3. **In-App DoH DNS Interceptor:**
   - Bộ chặn DNS bảo mật qua HTTPS (DoH) hoạt động cục bộ ngay tại hàm `socket.getaddrinfo` bên trong tiến trình Python.
   - Tích hợp sẵn danh sách IP gốc (Anycast Bootstrap IPs: `8.8.8.8`, `1.1.1.1`) giúp phân giải tên miền bị nhà mạng chặn mà không cần cài đặt VPN, không sửa card mạng Windows và không yêu cầu quyền Administrator.
4. **Bộ điều phối tài nguyên AutoTuner & Smart iGPU Offload:**
   - Tự động nhận diện phần cứng thực tế (CPU P-cores/E-cores, Card Onboard, Card Rời, dung lượng RAM).
   - Tự động tính toán số luồng giải mã và bộ đệm mạng tối ưu (`--network-caching`).
5. **Win32 Memory Working Set Recycler:**
   - Cơ chế dọn dẹp chủ động: Thu hồi toàn bộ bộ nhớ nhàn rỗi (`EmptyWorkingSet`) định kỳ và ngay sau khi kết thúc các tác vụ nặng (tua video, resolve stream).

---

## 🔬 Tại sao ứng dụng làm được như vậy? (Deep Technical Explanation)

### 1. Vì sao xem video chỉ tốn ~40MB – 70MB RAM (trong khi trình duyệt ngốn 1.5GB – 3.0GB+)?
- **Hạn chế của trình duyệt web:** Khi bạn mở một video trên Chrome hay Edge, trình duyệt phải khởi chạy hàng chục tiến trình con: tiến trình render toàn bộ cây DOM khổng lồ của website, engine JavaScript V8 liên tục chạy các đoạn mã theo dõi và quảng cáo, tiến trình GPU compositing, bộ nhớ cache hình ảnh trang... Kết quả là chỉ một tab video có thể ngốn tới vài GB RAM.
- **Giải pháp của FB Video Watcher:** Ứng dụng bóc tách **duy nhất luồng video thô** (`.m3u8` hoặc `.mp4`) từ trang web và truyền thẳng tới bộ giải mã C native của libVLC. Hoàn toàn không nạp DOM HTML, không chạy quảng cáo web, không giữ script rác trong bộ nhớ. Sau mỗi lần phân giải hoặc tua video, hàm `gc.collect()` và Win32 `EmptyWorkingSet` được kích hoạt để trả lại toàn bộ trang nhớ vật lý nhàn rỗi cho hệ điều hành.

### 2. Vì sao chơi game nặng mượt mà, không bị sụt FPS hay giật lag khi đang xem video?
- Khi bạn vừa chơi game đồ họa 3D (dùng card rời NVIDIA RTX / AMD Radeon) vừa mở video trên trình duyệt, trình duyệt sẽ tranh chấp tài nguyên GPU và VRAM của card rời để giải mã video, dẫn đến hiện tượng drop FPS hoặc crash driver đồ họa.
- **FB Video Watcher sử dụng cơ chế Smart iGPU Offload:** Thuật toán `AutoTuner` quét các adapter màn hình qua DirectX DXGI C-API. Khi phát hiện cấu hình Dual GPU (Card Onboard + Card Rời), ứng dụng tự động điều phối toàn bộ tải giải mã video sang bộ xử lý phần cứng **Intel QuickSync Video** trên iGPU (Intel UHD Graphics) hoặc AMD Radeon Graphics. Card đồ họa rời (RTX 4060, v.v.) hoàn toàn được giải phóng (tải video decode = 0.0%, VRAM chiếm dụng < 25MB), dành trọn vẹn 100% công lực cho game và đồ họa.

### 3. Vì sao ứng dụng phát được "mọi website" mà không bị chặn Anti-Hotlink hay nhà mạng chặn?
- **Vượt tường lửa & Chặn nhà mạng:** Thông thường nhà mạng áp dụng kỹ thuật đầu độc DNS (DNS Poisoning) đối với các website bị chặn. Ứng dụng tích hợp bộ giải mã DNS-over-HTTPS (DoH RFC 8427) độc lập. DoH mã hóa các truy vấn DNS thành các gói tin HTTPS thông thường gửi thẳng tới máy chủ Google/Cloudflare qua IP Bootstrap Anycast, vượt qua 100% các bộ lọc của ISP.
- **Vượt rào Anti-Hotlink bằng StreamProxy nội bộ:** Rất nhiều website đặt cơ chế kiểm tra `Referer` và `User-Agent`, nếu phát hiện link được gọi từ ứng dụng ngoài sẽ lập tức trả về lỗi HTTP 403 Forbidden. `StreamProxyServer` cục bộ tại `127.0.0.1` tự động giả lập lại chính xác toàn bộ header của trình duyệt gốc, nạp từng chunk `.ts` hoặc HTTP Range `.mp4` và chuyển tiếp an toàn cho VLC.

### 4. Vì sao giao diện luôn mượt mà 60fps, không bao giờ bị Not Responding?
- **Khử bỏ hoàn toàn I/O đồng bộ trên UI Thread:** Mọi tác vụ tốn thời gian (kết nối mạng qua yt-dlp, cào dữ liệu qua BFS crawler, tải phụ đề AI, dọn checkpoint SQLite WAL) đều được offload 100% sang hồ chứa luồng nền `DaemonThreadPoolExecutor`.
- **Cơ chế Idempotency Guard & Stale Future Guard:** Khi người dùng click / nhấn Enter liên tiếp hoặc tín hiệu phát được gửi đến dồn dập, Idempotency Guard nhận diện cùng một URL đang resolve để giữ nguyên tác vụ in-flight, không hủy ngắt quãng. Stale Guard ngăn chặn việc các tác vụ cũ nạp đè vào VLC, triệt tiêu hoàn toàn nguy cơ vỡ swapchain Direct3D 11.

---

## 📖 Hướng dẫn sử dụng (User Guide)

### 1. Dành cho người dùng phổ thông (Khuyến nghị)
Người dùng thông thường **không cần cài đặt Python** hay gõ bất kỳ dòng lệnh nào:

1. Tải bản cài đặt sẵn mới nhất tại: **[Releases](https://github.com/Olinere/fb-video-watching/releases)**.
2. Tải về file `.exe` duy nhất (ví dụ: `FB-Video-Watcher.exe`).
3. Khởi chạy ứng dụng:
   - Ứng dụng tự động kiểm tra xem máy tính của bạn đã có VLC Media Player 64-bit chưa.
   - Nếu chưa có, ứng dụng sẽ hiện thông báo và **tự động tải cài đặt bản VLC 64-bit chính thức an toàn từ VideoLAN**.
4. Dán bất kỳ liên kết video nào vào ô nhập liệu và bấm **Phát** (hoặc nhấn phím `Enter`).

---

### 2. Dành cho nhà phát triển (Chạy từ mã nguồn)

```powershell
# 1. Clone kho lưu trữ mã nguồn
git clone https://github.com/Olinere/fb-video-watching.git
cd fb-video-watching

# 2. Khởi tạo và kích hoạt môi trường ảo Python 3.10+
python -m venv .fbwenv
.\.fbwenv\Scripts\activate

# 3. Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt

# 4. Khởi chạy ứng dụng
python main.py
```

---

### 3. Bảng phím tắt mặc định (Hotkeys)

*Toàn bộ phím tắt đều có thể tùy biến lại theo ý muốn trong **⚙ Cài đặt $\rightarrow$ Phím tắt**:*

| Phím tắt | Thao tác | Mô tả chi tiết |
| :--- | :--- | :--- |
| `Space` hoặc `k` | **Phát / Tạm dừng** | Chuyển đổi trạng thái tạm dừng hoặc tiếp tục video |
| `Left` / `Right` hoặc `j` / `l` | **Tua ngắn** | Tua lùi hoặc tua tới 5 giây (mặc định) |
| `Shift + Left` / `Right` | **Tua vừa** | Tua lùi hoặc tua tới 10 giây |
| `Ctrl + Left` / `Right` | **Tua dài** | Tua lùi hoặc tua tới 30 giây |
| `Up` / `Down` | **Tăng / Giảm âm lượng** | Điều chỉnh âm lượng tăng giảm theo từng bước 5% |
| `m` | **Tắt / Bật tiếng (Mute)** | Chuyển nhanh chế độ im lặng |
| `[` / `]` | **Giảm / Tăng tốc độ** | Thay đổi tốc độ phát từ 0.25x đến 4.0x |
| `=` | **Tốc độ chuẩn 1.0x** | Đặt lại tốc độ phát về mức bình thường |
| `f` hoặc `F11` | **Toàn màn hình (Fullscreen)** | Bật / tắt toàn màn hình đúng màn hình hiển thị |
| `p` | **Cửa sổ nổi (PiP)** | Bật / tắt chế độ Picture-in-Picture luôn nổi trên cùng |
| `Shift + P` | **Đổi tỉ lệ PiP** | Chuyển đổi tỉ lệ PiP giữa 16:9 (ngang) và 9:16 (dọc) |
| `Ctrl + L` | **Lặp lại (Loop)** | Bật / tắt chế độ phát lặp lại video hiện tại |
| `Ctrl + B` | **Lặp đoạn A-B** | Đánh dấu mốc bắt đầu A, mốc kết thúc B và hủy lặp |
| `Ctrl + O` | **Mở tệp tệp tin** | Chọn và phát video offline từ ổ cứng máy tính |
| `Ctrl + H` | **Lịch sử xem video** | Mở bảng xem lại lịch sử các video đã phát |
| `Ctrl + S` | **Tải video / Âm thanh** | Mở hộp thoại tải media về máy |
| `Ctrl + Shift + Q` | **Hàng đợi phát (Queue)** | Mở thanh danh sách hàng đợi phát video |
| `Ctrl + ,` | **Cài đặt (Settings)** | Mở hộp thoại cài đặt mạng, phụ đề, âm thanh, video |
| `F12` hoặc `Ctrl + Shift + D` | **DevLog & Chẩn đoán** | Bật / tắt bảng chẩn đoán lỗi thời gian thực |
| `Escape` | **Thoát toàn màn hình / PiP** | Đưa trình phát về cửa sổ làm việc thông thường |

---

## 🧪 Đảm bảo chất lượng & Kiểm thử tự động (Unit Tests)

Dự án sở hữu bộ kiểm thử tự động toàn diện với **413 unit tests phủ kín 43 test suites**, kiểm soát chặt chẽ từ giải mã video, hàng đợi, phụ đề cho tới xử lý luồng mạng:

```powershell
# Chạy toàn bộ 413 unit tests trong môi trường ảo
.\.fbwenv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

```text
Ran 413 tests in 132.008s
OK
```

---

## 📄 Giấy phép (License)

Dự án được phân phối dưới giấy phép mã nguồn mở **[GNU General Public License v3.0 (GPL-3.0)](LICENSE)**.  
Mọi dòng mã nguồn đều công khai, minh bạch, phi thương mại và phục vụ cộng đồng người dùng.
