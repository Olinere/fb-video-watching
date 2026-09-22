# FB Video Watcher 🎬 & Universal Video Streamer

> Ứng dụng xem video desktop siêu nhẹ, tối ưu hóa phần cứng vượt trội với lõi VLC Media Player nhúng. Hỗ trợ phát đa nền tảng (Facebook, YouTube, TikTok, Douyin, Bilibili, Instagram, Twitter/X và link direct video), chế độ PiP 16:9 / 9:16 thông minh, tùy biến phím tắt linh hoạt và hệ thống phụ đề đa định dạng chuyên nghiệp với khung Live Preview trực quan.

---

## ✨ Tính năng nổi bật

### 🚀 1. Hiệu năng siêu nhẹ & Auto-Tuner phần cứng
- **Tiêu thụ cực ít tài nguyên:** Chỉ chiếm ~100–150MB RAM (so với 1GB–2GB+ khi xem trên Chrome/Edge/Firefox).
- **Tận dụng tối đa GPU:** Tự động kích hoạt giải mã phần cứng qua DirectX 11 (`d3d11va`) hoặc DXVA2, giải phóng 100% CPU cho công việc khác hoặc chơi game mượt mà không lo sụt FPS.
- **Auto-Tuning thông minh:** Tự động nhận diện cấu hình CPU, GPU, RAM để tinh chỉnh kích thước bộ đệm mạng (Network caching 1000–5000ms) và số luồng giải mã tối ưu nhất.
- **Tự động cài đặt VLC 64-bit ngầm (Silent Auto-Installer):** Nếu máy tính chưa cài đặt VLC, ứng dụng tự động tải gói cài đặt chính thức từ VideoLAN và cài đặt ngầm với thanh tiến trình trực quan, người dùng không cần thao tác thủ công.

### 🌐 2. Phát video đa nền tảng (Universal Video Streaming)
- **Facebook:** Hỗ trợ đầy đủ Reels, Watch, Video bài viết, Group công khai/kín, video livestream, liên kết rút gọn `fb.watch`, `fb.gg`.
- **YouTube:** Hỗ trợ video chuẩn, YouTube Shorts, link chia sẻ `youtu.be`.
- **TikTok & Douyin:** Hỗ trợ video ngắn TikTok và Douyin nội địa.
- **Nền tảng khác:** Hỗ trợ Bilibili, Twitter / X, Instagram Reels.
- **Link Video trực tiếp:** Hỗ trợ phát trực tiếp các đường link file video (`.mp4`, `.webm`, `.mkv`), luồng stream HLS (`.m3u8`) và DASH (`.mpd`).
- **Tự động nhận diện Clipboard:** Khi copy link video bất kỳ và chuyển sang app, popup thông báo nhanh sẽ xuất hiện để bạn phát ngay chỉ với 1 cú click.

### 💬 3. Hệ thống phụ đề đa định dạng chuyên nghiệp (Subtitle System)
- **Đọc tất cả định dạng phụ đề hiện nay:** Hỗ trợ toàn diện `.srt`, `.vtt`, `.ass`, `.ssa`, `.sub`, `.smi`, `.sami`, `.idx`, `.txt`, `.lrc`, `.ttml`, `.dfxp`.
- **Kiểm tra tính hợp lệ nghiêm ngặt (Format Validation):** Tự động phát hiện lỗi file rỗng, file nhị phân, sai cú pháp mốc thời gian (timestamp) hoặc thiếu header chuẩn; hiển thị hộp thoại cảnh báo lỗi rõ ràng nếu file không đúng chuẩn.
- **Tùy biến hiển thị phụ đề toàn diện trong Cài đặt:**
  - **Phông chữ (Font family):** Lựa chọn giữa các font hiển thị đẹp mắt (Segoe UI, Arial, Roboto, Tahoma, Verdana, Trebuchet MS, Georgia, Times New Roman, Consolas).
  - **Cỡ chữ (Font size):** Linh hoạt từ cỡ 14 đến 48.
  - **Định dạng kiểu chữ:** Hỗ trợ in đậm (**Bold**), in nghiêng (*Italic*), và gạch chân (<u>Underline</u>).
  - **Màu sắc chữ (Text color):** Bảng chọn màu trực quan kèm mã HEX.
  - **Viền chữ (Border / Outline):** Tùy chỉnh màu viền và độ dày viền (từ không viền, mỏng, vừa đến dày).
  - **Khung nền phụ đề (Background Box):** Bật/tắt khung nền, chọn màu nền và thanh trượt độ trong suốt/độ đậm (Opacity 0–255).
  - **Khung xem trước trực tiếp (Live Interactive Preview):** Mô phỏng chính xác giao diện hiển thị của phụ đề trên nền video theo thời gian thực khi bạn điều chỉnh bất kỳ thông số nào.
  - **Nút khôi phục mặc định:** Đưa kiểu hiển thị phụ đề về trạng thái gốc chuẩn chỉ với 1 click.
- **Nạp nhanh phụ đề:** Nhấp chuột phải vào video và chọn **`💬 Nạp phụ đề...`** để gắn phụ đề ngay lập tức vào video đang phát.

### 📌 4. Chế độ Picture-in-Picture (PiP) đa tỷ lệ
- **Cửa sổ nổi không viền (Borderless Floating Window):** Luôn nổi trên cùng (Always-on-top), di chuyển mượt mà tới bất kỳ góc nào trên màn hình.
- **Tự động hít cạnh / góc màn hình (Snap Margin 24px):** Khi kéo cửa sổ PiP gần mép màn hình, cửa sổ sẽ tự động hít sát cạnh để tối ưu không gian hiển thị.
- **Hỗ trợ 2 tỷ lệ khung hình:**
  - **16:9 (Ngang chuẩn):** Phù hợp với phim ảnh, video YouTube, Facebook Watch thông thường.
  - **9:16 (Dọc chuẩn):** Phù hợp với Reels, TikTok, YouTube Shorts.
- **Tự động phát hiện video dọc:** Tự động chuyển PiP sang tỉ lệ 9:16 khi phát video TikTok, Reels, Shorts.
- **Zoom kích thước bằng con lăn chuột:** Lăn chuột trên video PiP để phóng to / thu nhỏ cửa sổ cực kỳ mượt mà.
- **Preset kích thước nhanh:** Menu chuột phải cung cấp các mức kích thước sẵn có: Nhỏ, Tiêu chuẩn, Lớn, Rất lớn.

### 🔁 5. Lặp đoạn video A-B (A-B Repeat Loop)
- Cho phép đánh dấu **Điểm A** và **Điểm B** trong video để phát lặp lại liên tục đoạn đó.
- Rất tiện lợi cho việc nghe nhạc, học ngoại ngữ, bắt chước phát âm hoặc phân tích các pha highlight trong video game/thể thao.
- Hiển thị thông báo OSD thời gian thực và tự động quay về Điểm A khi phát tới Điểm B.

### ⌨️ 6. Quản lý phím tắt linh hoạt (Custom Hotkey Manager)
- Cho phép người dùng tùy chỉnh toàn bộ phím tắt trong tab **Phím tắt** của Cài đặt.
- Hỗ trợ phím đơn (`Space`, `m`, `f`), phím tổ hợp (`Ctrl+H`, `Shift+Left`), hoặc gán nhiều phím thay thế cho cùng một thao tác (ví dụ: `Space; k`).
- Tự động đồng bộ và hiển thị phím tắt mới ngay trên Menu chuột phải sau khi lưu mà không cần khởi động lại ứng dụng.

### 📜 7. Lịch sử xem SQLite WAL & Tự động xem tiếp (Resume Playback)
- Lưu lại danh sách các video đã xem vào cơ sở dữ liệu SQLite cấu hình chế độ Write-Ahead Logging (WAL) giúp ghi chép tức thì, không gây đơ lag giao diện.
- Tự động ghi nhớ thời điểm bạn đang xem dở và hỏi/tiếp tục phát đúng đoạn đó khi bạn mở lại video (`Resume Playback`).
- Hộp thoại **Lịch sử xem** (`Ctrl + H`) hỗ trợ tìm kiếm, lọc theo ngày, xem số lần phát và xóa lịch sử thuận tiện.

### 🛡️ 8. Chuyển nguồn ổn định
- Khi chuyển từ video Telegram đang pause sang YouTube hoặc nguồn khác, VLC được dừng trước rồi proxy Telegram được đóng bất đồng bộ.
- Các socket proxy đang stream được đóng chủ động; request handler chạy daemon để không giữ ứng dụng hoặc làm cửa sổ rơi vào trạng thái **Not Responding**.
- Cấu hình network buffer và Auto-Tuner của người dùng không bị thay đổi.

### ⬇️ 9. Tải video & Âm thanh MP3 đa luồng
- Tích hợp bộ tải video đa luồng với thanh hiển thị tiến trình phần trăm (%), dung lượng, tốc độ tải và thời gian còn lại (ETA).
- Hỗ trợ lựa chọn tải toàn bộ **Video** hoặc chỉ trích xuất **Âm thanh MP3**.
- Hiển thị thông báo **Windows Toast Notification** nguyên bản khi quá trình tải hoàn tất, kèm nút mở nhanh thư mục chứa file.

### 🎨 10. Giao diện Fluent Design & Hộp thoại Cài đặt tức thì
- Thiết kế bo góc, đổ bóng mềm mại theo phong cách Fluent Design trên Windows 11.
- Hỗ trợ chế độ **Sáng (Light)**, **Tối (Dark)** hoặc **Theo hệ thống (System)**, tự động nhuộm màu thanh tiêu đề Windows (Title Bar).
- **Hộp thoại Cài đặt (SettingsDialog) không khóa giao diện (Non-modal):** Bạn có thể vừa mở Cài đặt vừa xem/tạm dừng video chính.
- **Chuyển tab tức thì (0ms latency):** Công nghệ Stacked Canvas giữ 5 tab (Cấu hình chung, Phím tắt, Phụ đề, Giới thiệu & Bản quyền, Thông tin hệ thống) luôn sẵn sàng trong bộ nhớ, loại bỏ hoàn toàn độ trễ khi chuyển đổi giữa các tab.

### 🛠️ 11. Bảng Devlog chẩn đoán thời gian thực
- Nhấn phím tắt **`F12`** hoặc **`Ctrl + Shift + D`** (hoặc tick ô **`[ ] Devlog`** ở góc dưới) để mở bảng điều khiển kỹ thuật.
- Hiển thị log thời gian thực: phân giải luồng, codec, buffer, tốc độ bitrate.
- **⧉ Tách rời (Detach):** Biến bảng Devlog thành cửa sổ độc lập để kéo sang màn hình phụ.
- **⧈ Gắn lại (Dock):** Gắn lại Devlog vào cạnh phải của ứng dụng.
- Công cụ lọc theo cấp độ (`Tất cả`, `INFO+`, `WARNING+`, `ERROR+`), xóa log và sao chép vào clipboard.

### 🔄 12. Tự động cập nhật trực tiếp trong ứng dụng (In-App Auto-Update)
- Tự động kiểm tra phiên bản mới từ GitHub Releases khi khởi động hoặc thủ công qua tab **Giới thiệu & Bản quyền**.
- Tải gói cập nhật ngầm với thanh hiển thị tiến trình phần trăm (%) và kích thước tải.
- **Cơ chế Rename-then-Copy:** Vượt qua giới hạn khóa file đang chạy trên Windows (hỗ trợ hoàn hảo cả khi file thực thi nằm trong thư mục Desktop/OneDrive).
- **Cách ly môi trường PyInstaller:** Loại bỏ biến môi trường `_MEIPASS2` của tiến trình cũ, ngăn chặn triệt để lỗi không nạp được `python310.dll` khi khởi động tiến trình mới.
- **Tự động khôi phục phiên phát video:** Sau khi cập nhật và mở lại, ứng dụng tự động tải lại URL video đang xem dở, tua đến đúng vị trí thời gian và khôi phục trạng thái phát ban đầu.

### 🖥️ 13. Toàn màn hình đa màn hình thông minh (Multi-Monitor Fullscreen)
- Tự động nhận diện chính xác màn hình mà cửa sổ ứng dụng đang hiện diện thông qua Win32 API `MonitorFromWindow` (`MONITOR_DEFAULTTONEAREST`).
- Khi bật chế độ Toàn màn hình (`F11`, `f` hoặc double-click), video sẽ mở tràn viền đúng trên màn hình người dùng đang thao tác (kể cả màn hình phụ), không bị nhảy về màn hình chính `(0, 0)`.
- Khi thoát toàn màn hình, cửa sổ trở về đúng vị trí và kích thước trước đó trên màn hình tương ứng.

### ℹ️ 14. Tab Giới thiệu & Bản quyền & Kết nối Cộng đồng Discord
- Cung cấp thông tin phiên bản hiện tại, trạng thái phát hành và bản quyền phần mềm.
- Tích hợp nút **Tham gia Discord** trực quan với logo thương hiệu chuẩn, mở nhanh kênh hỗ trợ cộng đồng: `https://discord.gg/9gM5FAXDrC`.
- Tích hợp nút **Kiểm tra bản cập nhật** và liên kết đến kho lưu trữ GitHub chính thức.

---

## ⌨️ Bảng phím tắt mặc định

Tất cả phím tắt dưới đây đều có thể tùy biến lại theo ý muốn trong mục **⚙ Cài đặt $\rightarrow$ Phím tắt**:

| Phím tắt mặc định | Thao tác điều khiển | Ghi chú |
|---|---|---|
| `Space` hoặc `k` | Phát / Tạm dừng video | Click chuột trái vào video cũng có tác dụng tương tự |
| `←` | Tua lùi ngắn (mặc định 5s) | Tùy chỉnh bước tua: 3s, 5s, 10s, 15s, 30s |
| `→` | Tua tới ngắn (mặc định 5s) | Tùy chỉnh bước tua: 3s, 5s, 10s, 15s, 30s |
| `Shift + ←` | Tua lùi dài (mặc định 30s) | Tùy chỉnh bước tua: 10s, 15s, 30s, 60s, 90s |
| `Shift + →` | Tua tới dài (mặc định 30s) | Tùy chỉnh bước tua: 10s, 15s, 30s, 60s, 90s |
| `↑` | Tăng âm lượng (+5%) | Tối đa 150% âm lượng |
| `↓` | Giảm âm lượng (-5%) | |
| `m` | Bật / Tắt tiếng (Mute) | |
| `f` hoặc `F11` | Bật / Tắt toàn màn hình | Double-click chuột trái vào video cũng chuyển toàn màn hình |
| `p` | Bật / Tắt chế độ thu nhỏ PiP | Cửa sổ nổi không viền luôn trên cùng |
| `Ctrl + p` | Đổi tỷ lệ khung hình PiP (16:9 ↔ 9:16) | Chuyển đổi giữa chế độ ngang và dọc |
| `[` | Đặt điểm A (Lặp đoạn A-B) | Bắt đầu vòng lặp |
| `]` | Đặt điểm B (Lặp đoạn A-B) | Hoàn thành và kích hoạt vòng lặp |
| `Ctrl + r` | Hủy lặp đoạn A-B (Reset loop) | |
| `Ctrl + h` | Mở hộp thoại Lịch sử xem video | Xem lại các video đã phát gần đây |
| `Ctrl + s` | Mở chức năng Tải video về máy | Tải video hoặc trích xuất âm thanh MP3 |
| `Ctrl + ,` | Mở cửa sổ Cài đặt ứng dụng | Tùy chỉnh chất lượng, phụ đề, phím tắt |
| `F12` hoặc `Ctrl + Shift + D` | Bật / Tắt bảng Devlog chẩn đoán | Xem chi tiết thông số kết nối và luồng |
| `Escape` | Thoát Toàn màn hình / Thoát PiP | Hoặc hủy tiêu điểm ô nhập liệu |
| `Chuột phải vào video` | Mở Menu ngữ cảnh | Truy cập nhanh mọi tính năng và nạp phụ đề |

---

## 📋 Yêu cầu hệ thống

- **Hệ điều hành:** Windows 10 hoặc Windows 11 (64-bit).
- **VLC Media Player:** Bản 64-bit (nếu chưa có, ứng dụng sẽ tự động tải và cài đặt ngầm).
- **Phần cứng:** Tối thiểu 2GB RAM, card đồ họa hỗ trợ DirectX 11.

### Kiến trúc tiết kiệm tài nguyên

Ứng dụng dùng VLC/libVLC làm lõi phát thay vì nhúng browser. Playlist được đọc
ở chế độ metadata phẳng và giới hạn số entry; chỉ video đang phát mới được
resolve direct stream. Queue không giữ stream URL, HTTP header, cookie hay
format list. Tác vụ mạng chạy trên worker, callback quay về Tkinter qua
`after()`, còn bộ định thời UI giảm tần suất khi video đang dừng/tạm dừng.

Queue, Chapters và Privacy Session đều là các module độc lập. Queue/Chapters
chỉ giữ metadata nhỏ; panel có thể đóng để video chiếm toàn bộ diện tích. Khi
bật Privacy Session, history, resume, last URL và queue content không được ghi
xuống đĩa trong phiên đó.

Có thể truyền nguồn từ command line hoặc URI `fbvw://play?url=...` /
`fbvw://queue?url=...`; dữ liệu đi qua cùng pipeline với URL nhập trong giao
diện. Dùng `--privacy` để bật phiên riêng tư runtime.

---

## 🚀 Hướng dẫn cài đặt & Khởi chạy

### Cách 1: Sử dụng file `.exe` đóng gói sẵn (Khuyên dùng)
1. Mở thư mục **`dist`** trong dự án.
2. Nhấp đúp chuột vào file **`FB-Video-Watcher.exe`** để chạy ngay mà không cần cài đặt Python.

### Cách 2: Chạy từ mã nguồn Python (Dành cho lập trình viên)
1. Mở terminal tại thư mục gốc của dự án.
2. Kích hoạt môi trường ảo Python đã chuẩn bị sẵn:
   - **PowerShell:**
     ```powershell
     .\.fbwenv\Scripts\Activate.ps1
     ```
   - **Command Prompt (CMD):**
     ```cmd
     .\.fbwenv\Scripts\activate.bat
     ```
3. Chạy ứng dụng:
   ```bash
   python main.py
   ```
   *(Hoặc nhấp đúp vào file `run.bat`)*

### Cách 3: Tự build lại file `.exe` mới
Nếu bạn có thay đổi mã nguồn và muốn đóng gói lại:
1. Nhấp đúp vào file **`build.bat`** ở thư mục gốc.
2. Script sẽ tự động đóng gói bằng PyInstaller và tạo file thực thi mới tại `dist\FB-Video-Watcher.exe`.

---

## ⚙️ Hướng dẫn sử dụng các tính năng chi tiết

### 1. Xem video Facebook & Đa nền tảng
1. Sao chép liên kết video (Facebook Watch, Reels, YouTube, TikTok, Bilibili, link file `.mp4`...).
2. Dán link vào ô URL và nhấn **▶ Phát** (hoặc nhấn nút **📋 Dán & Phát** để tự dán và phát ngay).
3. Sử dụng thanh trượt để tua, chỉnh âm lượng hoặc chọn tốc độ phát từ `0.25x` đến `2.0x`.
4. Muốn nhảy đến thời điểm cụ thể, nhập vào ô **Nhảy tới:** (ví dụ: `1:45`, `01:20:00`, `90s`, `1h30m`) rồi nhấn **Enter** hoặc nút **→ Nhảy**.

### 2. Nạp và tinh chỉnh phụ đề (Subtitles)
- **Cách 1 (Nhanh):** Nhấp chuột phải lên bề mặt video $\rightarrow$ chọn **`💬 Nạp phụ đề...`** $\rightarrow$ chọn file phụ đề từ máy tính.
- **Cách 2 (Chi tiết):** Nhấn **⚙ Cài đặt** $\rightarrow$ chuyển sang tab **Phụ đề**:
  - Nhấn **Chọn file...** để nạp phụ đề (hệ thống sẽ tự động kiểm tra định dạng và báo lỗi nếu file hỏng).
  - Tùy chỉnh Font, Cỡ chữ, In đậm, In nghiêng, Gạch chân.
  - Chọn màu chữ, màu viền, độ dày viền, màu nền và độ đậm nhạt của khung nền.
  - Quan sát kết quả ngay tức thì tại ô **Xem trước trực tiếp (Live Preview)** phía bên phải.
  - Nhấn **Lưu & Áp dụng** để lưu lại cho mọi lần xem video sau này.

### 3. Xem video riêng tư / Nhóm kín (Cookies)
1. Cài tiện ích trích xuất cookie trên trình duyệt (ví dụ: *Get cookies.txt LOCALLY* trên Chrome/Edge).
2. Đăng nhập tài khoản trên trình duyệt và xuất cookie ra file `cookies.txt`.
3. Vào **⚙ Cài đặt** $\rightarrow$ mục **Video riêng tư & Cookies**, chọn file `cookies.txt` vừa xuất. Ứng dụng sẽ tự động sử dụng cookie này để phân giải các video trong nhóm kín hoặc bài đăng riêng tư.

### 4. Tải video và tách nhạc MP3
- Nhấn vào nút **⬇ Tải về** trên thanh công cụ (hoặc phím tắt `Ctrl + S`).
- Nhấp chuột phải vào nút **⬇ Tải về** để chọn nhanh giữa **Tải Video** hoặc **Tải riêng âm thanh MP3**.
- Xem tiến trình tải trực tiếp trên nút bấm và thanh trạng thái dưới cùng.

---

## 🧪 Kiểm thử tự động (Unit Tests)

Dự án duy trì bộ kiểm thử tự động cho toàn bộ source hiện có:
```bash
.\.fbwenv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Các test có giao diện dùng root withdrawn; test fullscreen cũng không chiếm
desktop khi chạy từ terminal. Nếu muốn kiểm tra riêng proxy:

```powershell
.\.fbwenv\Scripts\python.exe -m unittest tests.test_stream_proxy -v
```
Bộ kiểm thử bao gồm:
- **Tự động cập nhật & xử lý môi trường:** `test_updater.py`
- **Tiện ích hệ thống & đa màn hình Win32:** `test_platform_utils.py`
- **Hệ thống phím tắt tùy biến:** `test_hotkeys.py`, `test_space_key.py`
- **Kiểm tra tính hợp lệ & định dạng phụ đề:** `test_subtitle.py`
- **Trích xuất & phân giải luồng đa nền tảng:** `test_url_resolver.py`, `test_extractors.py`
- **Ghi nhớ URL, OSD & khôi phục phát:** `test_url_memory_and_osd.py`, `test_resume_loop_download.py`
- **Lịch sử xem SQLite WAL & Cài đặt:** `test_history.py`, `test_settings.py`
- **Bảng Devlog chẩn đoán:** `test_devlog.py`
- **Auto-Tuner & nhận diện phần cứng:** `test_auto_tune.py`, `test_system_info.py`
- **Chuyển đổi thời gian & Stream Proxy:** `test_timestamp.py`, `test_stream_proxy.py`, `test_extended_features.py`

## 🐛 Xử lý lỗi thường gặp

### Ứng dụng Not Responding khi chuyển Telegram sang YouTube

Phiên bản hiện tại dừng VLC trước khi đóng local Telegram proxy. Proxy đóng
socket stream trên background thread, vì vậy thao tác chuyển video không khóa
Tkinter main thread. Nếu vẫn gặp lỗi, mở Devlog bằng `F12` và gửi log cùng URL
gốc; không cần tắt tiến trình bằng Explorer ngay lập tức.

---

## 👨‍💻 Tác giả & Giấy phép (Author & License)

- **Tác giả:** **P A U L / JustFun**
- **Giấy phép:** **Freeware** (Phần mềm miễn phí sử dụng cho mục đích cá nhân).
- **Cộng đồng Discord:** [Tham gia Discord Server](https://discord.gg/9gM5FAXDrC) để thảo luận, báo lỗi và nhận hỗ trợ kỹ thuật trực tiếp.
- **Mã nguồn GitHub:** [https://github.com/Olinere/fb-video-watching](https://github.com/Olinere/fb-video-watching)
