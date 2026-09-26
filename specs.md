# FB Video Watcher — Technical Specification

> **Mục tiêu:** Ứng dụng desktop nhẹ, chuyên xem video Facebook bằng VLC engine — thay thế trình duyệt vốn ngốn RAM khi xem video trên Facebook.

---

## 1. Tổng quan kiến trúc

```
┌─────────────────────────────────────────────────────────┐
│                    GUI (Tkinter)                        │
│  ┌──────────────────────────────────────────────────┐   │
│  │  URL Input Bar + Nút "Phát" + Nút "Dán & Phát"  │   │
│  ├──────────────────────────────────────────────────┤   │
│  │           VLC Video Surface (embed)              │   │
│  ├──────────────────────────────────────────────────┤   │
│  │  Transport Bar: Play/Pause │ Seek │ Volume │ FS  │   │
│  │  Timestamp Jump: [input mm:ss] → Nút "Nhảy"     │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────┬────────────────────────────────────────┘
                 │
    ┌────────────▼────────────┐
    │   Core Engine (Python)  │
    │  ┌───────────────────┐  │
    │  │   URL Resolver     │  │  ← yt-dlp (trích xuất direct stream URL)
    │  ├───────────────────┤  │
    │  │   VLC Controller   │  │  ← python-vlc (libvlc bindings)
    │  ├───────────────────┤  │
    │  │   History Manager  │  │  ← SQLite (lưu lịch sử xem)
    │  └───────────────────┘  │
    └─────────────────────────┘
```

### Ngôn ngữ & Runtime
- **Python 3.10+** (khuyến nghị 3.12)
- Chạy trên **Windows 10/11** (ưu tiên). Cross-platform là bonus, không bắt buộc.

---

## 2. Các thành phần kỹ thuật (Dependencies)

| Thành phần | Vai trò | Cài đặt |
|---|---|---|
| **yt-dlp** / **yt-dlp-ejs** | Phân giải URL Facebook/đa nền tảng → direct stream URL, giải mã JS challenge. | `pip install yt-dlp yt-dlp-ejs` |
| **python-vlc** | Python bindings cho libVLC — engine phát video (decode, render, audio). | `pip install python-vlc` |
| **VLC Media Player** | Động cơ libVLC 64-bit (tự động cài ngầm nếu thiếu). | VideoLAN hoặc Auto-Installer |
| **tkinter** | GUI framework — gọn nhẹ, có sẵn trong Python stdlib. | Có sẵn (stdlib) |
| **sv-ttk** | Theme Fluent Design Windows 11 cho Tkinter — giao diện hiện đại, tốn 0MB RAM. | `pip install sv-ttk` |
| **tkinterdnd2** | Kéo và thả file video trực tiếp vào cửa sổ phát. | `pip install tkinterdnd2` |
| **Pillow** | Tải và hiển thị ảnh thumbnail, logo Discord theo theme. | `pip install Pillow` |
| **psutil** | Auto-detect cấu hình phần cứng CPU, RAM cho Auto-Tuner. | `pip install psutil` |
| **pywin32** | Gọi Win32 APIs (DWM Dark Title Bar, Monitor bounds, Named Pipe IPC, AppUserModelID). | `pip install pywin32` |
| **telethon** / **cryptg** / **qrcode** | Phân giải và stream video từ kênh/nhóm Telegram trực tiếp. | `pip install telethon cryptg qrcode` |
| **curl-cffi** | Mô phỏng TLS browser fingerprint cho yt-dlp bóc tách YouTube n-sig. | `pip install curl-cffi` |
| **FFmpeg** | Ghép stream DASH tách rời và trích xuất MP3 (hỗ trợ Portable Add-on tải tự động). | Add-on hoặc cài riêng |

### Tại sao chọn các thành phần này?
- **yt-dlp** thay vì tự parse HTML: Facebook thay đổi cấu trúc trang liên tục, yt-dlp có cộng đồng cập nhật nhanh.
- **VLC/libvlc** thay vì ffplay hay mpv: VLC decode hardware acceleration tốt, hỗ trợ hầu hết codec, API embed vào window dễ dàng qua `set_hwnd()`.
- **Tkinter + sv-ttk** thay vì PyQt/Electron: Nhẹ nhất, giữ RAM ~100MB, giao diện chuẩn Windows 11 Fluent đẹp mắt mà không ngốn tài nguyên.

---

## 3. Luồng hoạt động chính (Main Flow)

```
User dán URL Facebook
        │
        ▼
┌─────────────────────────┐
│  1. Validate URL         │  Kiểm tra URL hợp lệ (regex match các pattern FB)
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  2. Resolve Stream URL   │  Gọi yt-dlp --get-url để lấy direct stream URL
│     (yt-dlp)             │  Nếu có nhiều format → chọn best quality ≤ 1080p
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  3. Feed to VLC Player   │  player.set_media(instance.media_new(stream_url))
│     (python-vlc)         │  player.play()
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  4. User Controls        │  Play/Pause, Seek, Volume, Timestamp Jump, Fullscreen
└─────────────────────────┘
```

---

## 4. Đặc tả chi tiết từng module

### 4.1 URL Resolver Module (`url_resolver.py`)

**Chức năng:** Nhận URL Facebook → trả về direct stream URL để VLC phát.

#### Các dạng URL Facebook cần hỗ trợ:
```
https://www.facebook.com/reel/123456789
https://www.facebook.com/watch/?v=123456789
https://www.facebook.com/username/videos/123456789
https://fb.watch/abc123
https://www.facebook.com/share/v/abc123/
https://www.facebook.com/story.php?story_fbid=...&id=...
https://www.facebook.com/username/posts/123456789  (post chứa video)
```

#### Hàm chính:
```python
def resolve_facebook_url(url: str, cookie_file: str | None = None) -> ResolvedVideo:
    """
    Args:
        url: URL Facebook gốc do user nhập.
        cookie_file: Đường dẫn tới file cookies.txt (Netscape format)
                     cho video riêng tư / cần đăng nhập.

    Returns:
        ResolvedVideo(
            stream_url: str,        # Direct URL để VLC phát
            title: str,             # Tiêu đề video (nếu có)
            duration: float | None, # Thời lượng (giây), None nếu live
            thumbnail: str | None,  # URL thumbnail
            is_live: bool,          # True nếu đang livestream
            formats: list[Format],  # Danh sách format khả dụng
            audio_url: str | None,  # Direct audio stream URL cho Facebook DASH split streams
        )

    Raises:
        URLValidationError: URL không phải Facebook
        VideoNotFoundError: Video không tồn tại hoặc bị xóa
        AuthRequiredError: Cần cookies để truy cập video riêng tư
        NetworkError: Lỗi mạng
    """
```

#### Chi tiết kỹ thuật:
- Sử dụng `yt_dlp.YoutubeDL` API (import trực tiếp, KHÔNG gọi subprocess) với các option:
  ```python
  ydl_opts = {
      'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
      'quiet': True,
      'no_warnings': True,
      'extract_flat': False,
      'cookiefile': cookie_file,  # None nếu không cần
      'socket_timeout': 15,
      'retries': 3,
      # Fake User-Agent để FB không chặn IP:
      'http_headers': {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      }
  }
  ```
- Validate URL bằng regex trước khi gọi yt-dlp (tránh gọi yt-dlp với URL không phải FB):
  ```python
  FB_URL_PATTERN = re.compile(
      r'https?://(?:www\.|m\.|mbasic\.)?facebook\.com/.+|'
      r'https?://fb\.watch/.+|'
      r'https?://fb\.gg/.+'
  )
  ```
- Thực hiện resolve trong **background thread** (không block GUI).
- Nếu yt-dlp trả về URL có thời hạn (expired token), cần re-resolve khi phát lại.
- **Timeout:** 15 giây cho resolve, hiển thị loading indicator trên GUI.

---

### 4.2 VLC Player Module (`vlc_player.py`)

**Chức năng:** Điều khiển phát video qua libVLC, embed vào Tkinter window.

#### Class chính:
```python
class VLCPlayer:
    def __init__(self, parent_frame: tk.Frame):
        """
        Khởi tạo VLC Instance và MediaPlayer, embed vào parent_frame.

        VLC Instance args:
            '--no-xlib'           # Tránh lỗi thread trên Linux
            '--quiet'             # Không log ra console
            '--network-caching=1000'  # Buffer 1 giây cho network stream
            '--file-caching=1000'
        """

    # --- Playback Control ---
    def play(self, stream_url: str, audio_url: str | None = None) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def toggle_play_pause(self) -> None: ...

    # --- Seeking & Timestamp ---
    def seek_to(self, time_ms: int) -> None:
        """Nhảy tới vị trí cụ thể (milliseconds). Dùng player.set_time(time_ms)."""

    def seek_to_timestamp(self, timestamp: str) -> None:
        """
        Nhảy tới timestamp dạng chuỗi.
        Hỗ trợ formats: "1:23:45", "23:45", "45", "1h23m45s"
        Parse → milliseconds → gọi seek_to()
        """

    def seek_relative(self, delta_seconds: int) -> None:
        """Tua tới/lui N giây. Vd: seek_relative(-10) = lùi 10 giây."""

    def get_position(self) -> int:
        """Trả về vị trí hiện tại (milliseconds)."""

    def get_duration(self) -> int:
        """Trả về tổng thời lượng (milliseconds)."""

    # --- Volume ---
    def set_volume(self, volume: int) -> None:
        """Đặt âm lượng (0–150). VLC cho phép >100 = amplification."""

    def get_volume(self) -> int: ...
    def toggle_mute(self) -> None: ...

    # --- Display ---
    def set_fullscreen(self, enabled: bool) -> None: ...
    def toggle_fullscreen(self) -> None: ...
    def set_playback_rate(self, rate: float) -> None:
        """Tốc độ phát: 0.25, 0.5, 1.0, 1.5, 2.0"""

    # --- State ---
    @property
    def state(self) -> str:
        """'playing' | 'paused' | 'stopped' | 'buffering' | 'error'"""

    # --- Events ---
    def on_time_changed(self, callback: Callable[[int], None]) -> None:
        """Register callback khi thời gian phát thay đổi (cập nhật seek bar)."""

    def on_end_reached(self, callback: Callable[[], None]) -> None:
        """Register callback khi video phát xong."""

    def on_error(self, callback: Callable[[str], None]) -> None:
        """Register callback khi có lỗi phát."""

    def release(self) -> None:
        """Giải phóng bộ nhớ (MediaPlayer và Instance). Cần thiết khi đổi URL mới hoặc đóng app."""
```

#### Lưu ý kỹ thuật quan trọng:
1. **Embed VLC vào Tkinter:**
   ```python
   # Windows
   player.set_hwnd(video_frame.winfo_id())
   ```
2. **Event handling:** VLC events chạy trên thread riêng → dùng `root.after()` để marshal callback về GUI thread.
3. **Network caching:** Set `--network-caching=1500` để buffer đủ cho streaming, tránh giật.
4. **Hardware acceleration:** Mặc định VLC đã bật hardware decoding (DXVA2 trên Windows). Không cần config thêm.
5. **Giữ reference & Chống Memory Leak:** Luôn giữ reference tới `vlc.Instance()` và `MediaPlayer` trong class attribute. Khi phát URL mới hoặc đóng app, BẮT BUỘC gọi `player.stop()` và giải phóng bằng `player.release()` nếu không sẽ bị rò rỉ RAM (Memory Leak).

---

### 4.3 GUI Module (`gui.py`)

**Chức năng:** Giao diện người dùng chính.

#### Layout (từ trên xuống):

```
╔══════════════════════════════════════════════════════════╗
║  🔗 [_____________URL Facebook______________] [▶ Phát]  ║  ← URL Bar
║     [📋 Dán & Phát]                                     ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║                                                          ║
║              [  Video Surface — VLC Render  ]            ║  ← 70-80% diện tích
║                                                          ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║  ▶/⏸  ⏮10s  ⏭10s  ══════════●══════════  02:34/15:00   ║  ← Transport Bar
║  🔊 ═══●═══  |  Tốc độ: [1x ▾]  |  ⛶ Fullscreen       ║
╠══════════════════════════════════════════════════════════╣
║  Nhảy tới: [__:__:__] [→ Nhảy]   Hoặc nhập giây: [___] ║  ← Timestamp Jump
╠══════════════════════════════════════════════════════════╣
║  📜 Title: "Tên video..."    ⏱ Thời lượng: 15:00       ║  ← Info Bar
╚══════════════════════════════════════════════════════════╝
```

#### Thành phần GUI chi tiết:

| Widget | Loại | Chức năng |
|---|---|---|
| URL Input | `tk.Entry` | Nhập/dán URL Facebook |
| Nút "Phát" | `tk.Button` | Resolve URL và phát video |
| Nút "Dán & Phát" | `tk.Button` | Lấy URL từ clipboard → tự động phát (shortcut) |
| Video Surface | `tk.Frame` | Container cho VLC render video vào |
| Play/Pause | `tk.Button` | Toggle phát/dừng |
| Seek Bar | `tk.Scale` (horizontal) | Thanh trượt tua video |
| Volume Slider | `tk.Scale` | Điều chỉnh âm lượng |
| Time Label | `tk.Label` | Hiển thị `current / total` (mm:ss) |
| Timestamp Input | `tk.Entry` | Nhập timestamp (hh:mm:ss hoặc mm:ss hoặc giây) |
| Nút "Nhảy" | `tk.Button` | Gọi `seek_to_timestamp()` |
| Speed Dropdown | `tk.OptionMenu` | Chọn tốc độ: 0.25x, 0.5x, 1x, 1.5x, 2x |
| Fullscreen | `tk.Button` | Toggle fullscreen |
| Info Bar | `tk.Label` | Hiển thị title video, thời lượng |

#### Keyboard Shortcuts:

| Phím | Hành động |
|---|---|
| `Space` | Play / Pause |
| `←` / `→` | Tua lùi/tới 5 giây |
| `Shift+←` / `Shift+→` | Tua lùi/tới 30 giây |
| `↑` / `↓` | Tăng/giảm volume 5% |
| `M` | Mute / Unmute |
| `F` hoặc `F11` | Toggle Fullscreen |
| `Ctrl+V` | Dán URL từ clipboard vào ô input |
| `Ctrl+Shift+V` | Dán URL & tự động phát (shortcut "Dán & Phát") |
| `Escape` | Thoát fullscreen |
| `P` | Bật / tắt chế độ thu nhỏ PiP (Picture-in-Picture) |
| `Chuột phải` | Mở menu ngữ cảnh nhanh (PiP, phát, tua, âm lượng, cài đặt) |
| `[` / `]` | Giảm / tăng tốc độ phát |
| `Ctrl+,` | Mở cửa sổ Settings |

#### Xử lý UI States:

| State | Hiển thị |
|---|---|
| **Idle** | URL input trống, video surface hiện logo/placeholder |
| **Loading** | Hiện spinner/text "Đang tải…" trên video surface, disable nút Phát |
| **Playing** | Video đang phát, seek bar cập nhật real-time |
| **Paused** | Nút chuyển thành ▶, video dừng |
| **Error** | Hiện thông báo lỗi (URL sai, video bị xóa, cần login…) |
| **Buffering** | Hiện "Đang buffer…" overlay |

#### Settings Panel (Cửa sổ cài đặt):

Mở bằng nút **⚙ Settings** trên GUI hoặc phím tắt `Ctrl+,`. Hiển thị dạng **Toplevel window** (cửa sổ phụ).

```
╔═══════════════════════ Cài đặt ═══════════════════════╗
║                                                        ║
║  ── Video ──────────────────────────────────────────── ║
║  Chất lượng tối đa:    [1080p ▾]  (360p/480p/720p/1080p/Tốt nhất)  ║
║  Tốc độ phát mặc định: [1.0x  ▾]  (0.25x → 2.0x)     ║
║                                                        ║
║  ── Âm thanh ───────────────────────────────────────── ║
║  Âm lượng mặc định:    [═══════●══] 80%               ║
║                                                        ║
║  ── Streaming ──────────────────────────────────────── ║
║  Network buffer:       [3000 ▾] ms  (1000/2000/3000/5000)  ║
║  Hardware decode:      [✓] Bật (DXVA2)                 ║
║  Decode threads:       [4 ▾]  (1/2/4/Auto)             ║
║                                                        ║
║  ── Giao diện ──────────────────────────────────────── ║
║  Chế độ nền (Theme):   [Hệ thống ▾]  (Sáng/Tối/Hệ thống)║
║  Tua ngắn (←→):       [5  ] giây                      ║
║  Tua dài (Shift+←→):  [30 ] giây                      ║
║  Always on top:        [✗]                              ║
║                                                        ║
║  ── Nâng cao ───────────────────────────────────────── ║
║  File cookies:         [____đường_dẫn____] [Chọn...]   ║
║  Cập nhật yt-dlp:      [🔄 Cập nhật ngay]              ║
║                                                        ║
║            [ Lưu & Đóng ]    [ Hủy ]                   ║
╚════════════════════════════════════════════════════════╝
```

#### Danh sách settings hiển thị trên GUI:

| Setting | Widget | Giá trị | Mặc định | Ghi chú |
|---|---|---|---|---|
| **Chất lượng tối đa** | `OptionMenu` | `360`, `480`, `720`, `1080`, `0` (tốt nhất) | `1080` | Map sang `MAX_VIDEO_HEIGHT`, `0` = không giới hạn |
| **Tốc độ phát mặc định** | `OptionMenu` | `0.25` → `2.0` | `1.0` | Áp dụng cho video tiếp theo |
| **Âm lượng mặc định** | `Scale` (slider) | `0` – `150` | `80` | >100 = khuếch đại âm thanh |
| **Network buffer** | `OptionMenu` | `1000`, `2000`, `3000`, `5000` ms | `3000` | Tăng nếu mạng yếu / vừa chơi game |
| **Hardware decode** | `Checkbutton` | Bật / Tắt | Bật | Tắt nếu gặp lỗi hiển thị |
| **Decode threads** | `OptionMenu` | `1`, `2`, `4`, `Auto` | `4` | `Auto` = VLC tự quyết định |
| **Theme (Chế độ nền)** | `OptionMenu` | `light`, `dark`, `system` | `system` | Giao diện cho app |
| **Tua ngắn** | `Spinbox` | `1` – `30` giây | `5` | Thời gian tua khi nhấn ←→ |
| **Tua dài** | `Spinbox` | `10` – `120` giây | `30` | Thời gian tua khi nhấn Shift+←→ |
| **Always on top** | `Checkbutton` | Bật / Tắt | Tắt | Giữ cửa sổ luôn trên cùng (hữu ích khi game windowed) |
| **File cookies** | `Entry` + `Button` | Đường dẫn file | *(trống)* | Dùng `filedialog.askopenfilename()` để chọn |
| **Cập nhật yt-dlp** | `Button` | — | — | Chạy `yt_dlp.update.run_update()` trên thread riêng |

#### Lưu trữ settings: JSON file

File: `~/.fb-video-watcher/settings.json`

```python
# Cấu trúc settings.json
DEFAULT_SETTINGS = {
    "video": {
        "max_height": 1080,          # 360 | 480 | 720 | 1080 | 0 (best)
        "default_speed": 1.0,        # 0.25 → 2.0
    },
    "audio": {
        "default_volume": 80,        # 0-150
    },
    "streaming": {
        "network_caching": 3000,     # ms
        "hardware_decode": True,     # DXVA2
        "decode_threads": 4,         # 1 | 2 | 4 | 0 (auto)
    },
    "ui": {
        "theme": "system",           # "light" | "dark" | "system"
        "seek_short": 5,             # giây
        "seek_long": 30,             # giây
        "always_on_top": False,
    },
    "advanced": {
        "cookie_file": "",           # đường dẫn tới cookies.txt
    }
}
```

#### Logic load/save:
```python
class SettingsManager:
    def __init__(self, config_dir: Path):
        self.settings_file = config_dir / "settings.json"
        self.settings = self._load()

    def _load(self) -> dict:
        """Load settings từ file. Nếu chưa có → dùng DEFAULT_SETTINGS."""
        if self.settings_file.exists():
            with open(self.settings_file, 'r') as f:
                saved = json.load(f)
            # Merge với default (đề phòng settings mới thêm ở bản update)
            return self._deep_merge(DEFAULT_SETTINGS, saved)
        return copy.deepcopy(DEFAULT_SETTINGS)

    def save(self) -> None:
        """Ghi settings ra file JSON."""
        with open(self.settings_file, 'w') as f:
            json.dump(self.settings, f, indent=2, ensure_ascii=False)

    def get(self, *keys) -> Any:
        """Truy cập nested key. Vd: get('video', 'max_height') → 1080"""
        val = self.settings
        for k in keys:
            val = val[k]
        return val

    def set(self, *keys_and_value) -> None:
        """Gán nested key. Vd: set('video', 'max_height', 720)"""
        *keys, value = keys_and_value
        d = self.settings
        for k in keys[:-1]:
            d = d[k]
        d[keys[-1]] = value
```

> [!IMPORTANT]
> - Settings phải **áp dụng ngay** khi nhấn "Lưu & Đóng" — không cần restart app.
> - Một số settings cần rebuild VLC Instance (ví dụ: thay đổi `network_caching`, `hardware_decode`). Khi thay đổi những settings này → hiện thông báo "Sẽ áp dụng cho video tiếp theo".
> - Settings khác (volume, seek, always_on_top) → áp dụng lập tức.

---

### 4.4 History Manager Module (`history.py`) *(Optional nhưng khuyến nghị)*

**Chức năng:** Lưu lịch sử video đã xem, hỗ trợ tiếp tục xem từ vị trí dừng.

#### Database: SQLite (`~/.fb-video-watcher/history.db`)

```sql
CREATE TABLE watch_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,              -- URL Facebook gốc
    title         TEXT,                        -- Tiêu đề video
    duration_ms   INTEGER,                    -- Tổng thời lượng (ms)
    last_position INTEGER DEFAULT 0,          -- Vị trí xem cuối (ms) — để resume
    watch_count   INTEGER DEFAULT 1,          -- Số lần xem
    first_watched TEXT DEFAULT (datetime('now')),
    last_watched  TEXT DEFAULT (datetime('now')),
    thumbnail_url TEXT                        -- URL thumbnail (cache riêng nếu cần)
);
```

#### Tính năng:
- **Auto-save position:** Khi pause/stop/đóng app → lưu `last_position`.
- **Resume playback:** Khi mở lại URL đã xem → hỏi "Tiếp tục từ 05:23?" (dialog).
- **History list:** Panel bên hoặc menu hiển thị danh sách video đã xem (title + thumbnail + ngày).

---

### 4.5 Theme Manager Module (`theme.py`)

**Chức năng:** Trừu tượng hóa việc quản lý màu sắc giao diện (Light Mode / Dark Mode) để không bị fix cứng vào code GUI. Cho phép thay đổi theme trực tiếp từ Settings.

#### Hướng tiếp cận (Abstraction):
Để giữ nguyên tắc siêu nhẹ và giao diện hiện đại chuẩn Windows 11 Fluent Design, ứng dụng sử dụng thư viện **`sv-ttk`** kết hợp với bảng màu và DWM native title bar trong `theme.py`. `gui.py` chỉ sử dụng các widget chuẩn `ttk`, việc tạo kiểu (styling), bo góc, đổ bóng và đổi dark/light mode được quản lý 100% tự động bởi `ThemeManager`.

#### Interface thiết kế:

```python
import sys
import tkinter as tk
from tkinter import ttk

class ThemeManager:
    """Quản lý và áp dụng màu sắc, sv-ttk Fluent theme cho toàn bộ ứng dụng."""
    
    PALETTES = {
        "light": {"bg": "#f3f3f3", "fg": "#1a1a1a", ...},
        "dark": {"bg": "#202020", "fg": "#f0f0f0", ...}
    }

    def __init__(self, root: tk.Tk, user_theme: str = "system"):
        self.root = root
        self.current_theme = "dark"
        self.apply_theme(user_theme)

    def apply_theme(self, mode: str) -> None:
        """
        Áp dụng chế độ: 'light', 'dark' hoặc 'system'.
        Kích hoạt sv-ttk Fluent theme, cập nhật root background và DWM dark titlebar.
        """
        if mode == "system":
            self.current_theme = self._detect_system_theme()
        else:
            self.current_theme = mode

        # Kích hoạt sv-ttk theme (Fluent Windows 11)
        try:
            import sv_ttk
            sv_ttk.set_theme(self.current_theme)
        except Exception:
            self._apply_ttk_styles()

        self._apply_windows_dark_titlebar()

        # Phát thông báo tới các component đăng ký lắng nghe (ThemedMenuBar, MainWindow, popup menus)
        for listener in list(self._listeners):
            listener(self.current_theme, self.PALETTES[self.current_theme])
```

> **Lưu ý trong phân hệ GUI (`main/gui/`):**
> - Đối với widget chuẩn: Dùng `ttk.Button`, `ttk.Label` từ `tkinter.ttk` để `ThemeManager` tự động đồng bộ hóa thông qua `sv-ttk`.
> - Đối với widget tùy biến (in-window `ThemedMenuBar`, dropdown menus, context menus): Đăng ký thông qua `ThemeManager.add_listener(callback)` để cập nhật màu nền surface, viền, hover, accent và menu dropdown ngay khi đổi theme giữa Light và Dark.

---

### 4.6 Cửa sổ Cài đặt & Tab Giới thiệu (`gui.py` - SettingsDialog)

**Chức năng:** Cung cấp hộp thoại cài đặt không khóa giao diện (non-modal) với kiến trúc Stacked Canvas (0ms chuyển tab) gồm 5 tab chức năng:
1. **Cấu hình chung (General):** Chất lượng video, Network caching, Bước nhảy tua (ngắn/dài), Tối ưu CPU (Affinity P-cores/E-cores), Thư mục tải về, Cookies file Netscape.
2. **Phím tắt (Hotkeys):** Tùy biến toàn bộ phím tắt điều khiển với kiểm tra trùng lặp và lưu tức thì.
3. **Phụ đề (Subtitles):** Tùy biến kiểu chữ, màu sắc, viền, khung nền và Live Preview thời gian thực.
4. **Thông tin hệ thống (System Info):** Quét thông số CPU, GPU, RAM, VLC và đề xuất Auto-tuning.
5. **Giới thiệu (About Tab):**
   - **Hero Header:** Logo ứng dụng (56x56), Tên phần mềm (`FB Video Watcher`), Tagline, Phiên bản (`v{APP_VERSION}`).
   - **Tác giả & Bản quyền:** Tác giả (`P A U L / JustFun`), Bản quyền (`© 2026 P A U L / JustFun. All rights reserved.`), Giấy phép (`Freeware`).
   - **Cộng đồng:** Nút tham gia Discord với logo Discord chính thức tự đổi màu theo theme (Blurple cho Hệ thống, Đen cho Sáng, Trắng cho Tối).
   - **Định dạng & Nền tảng:** Hỗ trợ Container (MP4, MKV, WebM, M3U8 HLS, MPD DASH, TS), nền tảng trực tuyến phổ biến và video cục bộ.
   - **Cập nhật phần mềm:** Nút "🔄 Kiểm tra bản cập nhật" bất đồng bộ kết nối trực tiếp GitHub Releases API.

---

### 4.7 Auto-Updater Module (`updater.py`)

**Chức năng:** Quản lý toàn diện quy trình tự động cập nhật phần mềm không gián đoạn (In-App Auto-Update) từ GitHub Releases (`Olinere/fb-video-watching`):

#### Quy trình hoạt động:
1. **Kiểm tra bản cập nhật (`check_for_updates`):**
   - Truy vấn GitHub API: `https://api.github.com/repos/Olinere/fb-video-watching/releases/latest`.
   - Phân tích và so sánh phiên bản ngữ nghĩa (Semver: `parse_semver`).
   - Trả về `UpdateInfo` nếu có bản mới hơn và chứa asset `.zip` hoặc `.exe`.
2. **Tải ngầm không gián đoạn (`download_update`):**
   - Tải file cập nhật theo từng chunk 64KB vào thư mục tạm `%TEMP%\fbw_update\v{version}\`.
   - Callback báo tiến trình phần trăm (%), dung lượng (MB) lên thanh trạng thái.
   - Người dùng tiếp tục xem video bình thường trong lúc tải.
3. **Chụp trạng thái phát (`get_current_playback_snapshot`):**
   - Ghi nhớ URL, mốc thời gian mili-giây (`position_ms`), âm lượng, tốc độ phát, tắt tiếng vào `resume_state.json`.
4. **Khởi chạy tiến trình cập nhật độc lập (`apply_update_and_restart`):**
   - Sử dụng PowerShell ẩn với cờ `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`.
   - **Bypass File Lock của Windows (Rename-then-Copy):**
     - Đổi tên file đang chạy `FB-Video-Watcher.exe` $\rightarrow$ `FB-Video-Watcher.exe.old`.
     - Sao chép file mới từ thư mục tạm vào đúng vị trí của file cũ (hỗ trợ mọi đường dẫn, kể cả Desktop/OneDrive).
   - **Tẩy sạch biến môi trường PyInstaller:**
     - Xóa `_MEIPASS2` và `_MEIPASS` khỏi môi trường.
     - Thiết lập `PYINSTALLER_RESET_ENVIRONMENT = "1"` để bản mới tự giải nén nhân Python sạch sẽ, tránh lỗi `Failed to load Python DLL (python310.dll)`.
   - Khởi chạy lại file mới tại đúng vị trí cũ: `Start-Process -FilePath "$exePath"`.
   - Dọn sạch file `.old` và thư mục tạm `%TEMP%\fbw_update`.
5. **Khôi phục phát tiếp tự động (`_apply_post_update_resume`):**
   - Bản mới khởi động, nạp `resume_state.json`, tự động phát lại URL và tua chính xác tới mili-giây đang xem dở.

---

### 4.8 Hỗ trợ Toàn màn hình Đa màn hình (`platform_utils.py` & `gui.py`)

**Chức năng:** Đảm bảo tính năng phóng to toàn màn hình (Full-screen) luôn hiển thị đúng trên màn hình mà người dùng đang thao tác, không bị nhảy về màn hình chính trên hệ thống nhiều màn hình.

#### Nguyên lý kỹ thuật:
1. **Lấy tọa độ màn hình chứa cửa sổ (`get_monitor_bounds_for_window`):**
   - Gọi Windows API `MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST = 2)`.
   - Truy vấn `GetMonitorInfoW` để lấy tọa độ thực tế `(left, top, width, height)` của màn hình hiện tại.
2. **Kích hoạt Full-screen tại chỗ (`enter_fullscreen`):**
   - Lưu lại `_fs_prev_geometry` và trạng thái `_fs_prev_state`.
   - Kích hoạt `root.attributes("-fullscreen", True)`.
   - Lập tức gán tọa độ chuẩn theo màn hình phát hiện: `root.geometry(f"{mw}x{mh}+{mx}+{my}")`.
3. **Khôi phục chuẩn xác khi thoát (`exit_fullscreen`):**
   - Tắt `root.attributes("-fullscreen", False)`.
   - Khôi phục cửa sổ về đúng `_fs_prev_geometry` trên màn hình phụ đó.

---

## 5. Cấu trúc thư mục dự án

```
FB-Video-watching/
├── .fbwenv/                 # Môi trường ảo Python (KHÔNG commit vào git)
├── .gitignore
├── README.md                # Hướng dẫn sử dụng cho người dùng (xem §15)
├── specs.md                 # File đặc tả kỹ thuật
├── Agent.md                 # Hướng dẫn cho AI model triển khai code
├── requirements.txt         # Dependencies
├── build.bat                # Script tự động đóng gói PyInstaller .exe
├── fb_video_watcher.spec    # PyInstaller spec nhúng version_info và PE metadata
├── main.py                  # Entry point (import từ main/)
├── main/                    # Source code chính
│   ├── __init__.py          # Single Source of Truth cho __version__
│   ├── app.py               # Application orchestrator (kết nối tất cả)
│   ├── bulk_import_dialog.py # Hộp thoại nhập danh sách tập/video từ văn bản thô
│   ├── text_parser.py        # SmartTextParser bóc tách link, giải mã shim, gọt tracking
│   ├── url_resolver.py      # Module 4.1 — Resolve URL Facebook & đa nền tảng
│   ├── collection.py        # Model ResolvedCollection & CollectionEntry cho playlist/album
│   ├── vlc_player.py        # Module 4.2 — VLC Controller
│   ├── gui/                 # Module 4.3 — Phân hệ Giao diện người dùng Tkinter Fluent
│   │   ├── __init__.py      # Re-export MainWindow, SettingsDialog, ThemedMenuBar, components
│   │   ├── components.py    # SeekBarController, OSDOverlay, PiPProgressOverlay, ListboxTooltip
│   │   ├── menu_bar.py      # ThemedMenuBar (Khử thanh menu trắng Win32, đồng bộ màu theme)
│   │   ├── settings_dialog.py # SettingsDialog (Cài đặt đa thẻ Fluent)
│   │   └── main_window.py   # MainWindow (Player surface, video controls, playlist, layout)
│   ├── history_dialog.py    # Hộp thoại hiển thị & tìm kiếm lịch sử xem
│   ├── theme.py             # Module 4.5 — Trừu tượng hóa Theme/Dark Mode (sv_ttk)
│   ├── settings.py          # Settings manager (JSON load/save)
│   ├── updater.py           # Module 4.6 — Tự động cập nhật ngầm & khôi phục phát
│   ├── downloader.py        # Tải video & trích xuất MP3 đa luồng
│   ├── ffmpeg_utils.py       # Quản lý phát hiện FFmpeg, fallback progressive stream
│   ├── ffmpeg_installer.py   # Tự động tải & cài đặt FFmpeg Portable Add-on ngầm
│   ├── ffmpeg_setup_dialog.py # Hộp thoại tiến trình tải tiện ích mở rộng FFmpeg
│   ├── devlog.py            # Bảng điều khiển kỹ thuật thời gian thực (Dock/Detach)
│   ├── hotkeys.py           # Hệ thống quản lý và tùy biến phím tắt
│   ├── subtitle.py          # Xử lý định dạng & kiểm tra tính hợp lệ phụ đề
│   ├── playback_queue.py    # Model hàng đợi phát & QueueItem metadata
│   ├── queue_controller.py  # Điều phối chuyển bài, thử lại lỗi & lặp danh sách
│   ├── queue_persistence.py # Lưu và nạp queue.json có kiểm soát quyền riêng tư
│   ├── chapters.py          # Quản lý mục lục video và chuẩn hóa mốc thời gian
│   ├── windows_integration.py # Tích hợp Windows (CLI, protocol fbvw://, IPC)
│   ├── telegram_manager.py   # Quản lý tài khoản Telegram & phiên Telethon
│   ├── playback_health.py   # Theo dõi tình trạng mạng, buffering & phục hồi
│   ├── playback_profiles.py # Quản lý source profile theo domain (Auto/Custom)
│   ├── privacy_session.py   # Quản lý chính sách phiên riêng tư Runtime
│   ├── stream_proxy.py      # Local HTTP proxy, daemon handlers & async shutdown
│   ├── system_info.py       # Auto-detect phần cứng (xem Agent.md §2)
│   ├── auto_tune.py         # Tự tối ưu config theo phần cứng (xem Agent.md §3)
│   ├── platform_utils.py    # Multi-monitor bounds, VLC embed, Win32 icon, DWM
│   ├── timestamp.py         # Utility: parse timestamp strings ↔ ms
│   ├── constants.py         # Default values, config paths, regex patterns (APP_VERSION)
│   ├── bin/
│   │   └── qjs.exe          # QuickJS engine cho yt-dlp giải mã n-sig YouTube
│   ├── docs/
│   │   └── cookies_guide.html # Hướng dẫn xuất cookies cho video riêng tư
│   ├── extractors/          # Các bộ trích xuất luồng chuyên biệt
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── generic.py
│   │   ├── local.py
│   │   ├── sexvietnew.py
│   │   ├── telegram.py
│   │   ├── vlxx.py
│   │   ├── xnhau.py
│   │   └── youtube.py
│   └── image/               # Assets icon (ICO, PNG) & Discord logos theo theme
└── tests/                   # Toàn bộ 28 test files (262 unit tests vượt qua 100%)
    ├── test_auto_tune.py
    ├── test_devlog.py
    ├── test_downloader_ffmpeg_fallback.py
    ├── test_extended_features.py
    ├── test_extractors.py
    ├── test_ffmpeg_installer.py
    ├── test_gpu_offload.py
    ├── test_health_and_auto_suggestion.py
    ├── test_history.py
    ├── test_hotkeys.py
    ├── test_platform_utils.py
    ├── test_playback_queue.py
    ├── test_profiles_health.py
    ├── test_queue_hover_tooltip.py
    ├── test_queue_privacy_windows.py
    ├── test_queue_ui_and_devlog_layout.py
    ├── test_resume_loop_download.py
    ├── test_settings.py
    ├── test_space_key.py
    ├── test_stream_proxy.py
    ├── test_subtitle.py
    ├── test_system_info.py
    ├── test_telegram.py
    ├── test_text_parser.py
    ├── test_timestamp.py
    ├── test_updater.py
    ├── test_url_memory_and_osd.py
    └── test_url_resolver.py
```

---

## 6. Môi trường ảo & Dependencies

### 6.1 Tạo môi trường ảo `.fbwenv`

> [!IMPORTANT]
> **Bắt buộc** tạo virtual environment tên **`.fbwenv`** trong thư mục gốc project trước khi cài bất kỳ dependency nào.

```bash
# Tạo môi trường ảo
python -m venv .fbwenv

# Kích hoạt (Windows PowerShell)
.\.fbwenv\Scripts\Activate.ps1

# Kích hoạt (Windows CMD)
.\.fbwenv\Scripts\activate.bat

# Cài dependencies
pip install -r requirements.txt
```

> **Lưu ý:** Thêm `.fbwenv/` vào `.gitignore` — không commit môi trường ảo vào git.

### 6.2 File `requirements.txt`

```
yt-dlp>=2024.01.01
python-vlc>=3.0.20
psutil>=5.9.0
pywin32>=306; sys_platform == 'win32'
sv-ttk>=2.6.0
```

> **Lưu ý:** `tkinter` là stdlib, không cần list. `FFmpeg` cài riêng, không qua pip. `psutil` dùng cho `system_info.py` (detect CPU/RAM/GPU). `pywin32` chỉ chạy trên Windows, dùng để set flag chống nháy giật (flicker) GUI. `sv-ttk` cung cấp theme Fluent Design Windows 11 hiện đại cho Tkinter.

---

## 7. Xử lý lỗi & Edge Cases

### 7.1 URL & Resolver

| # | Tình huống | Xử lý |
|---|---|---|
| 1 | URL không phải Facebook | Hiện thông báo "URL không hợp lệ. Chỉ hỗ trợ URL Facebook." |
| 2 | URL Facebook hợp lệ nhưng **không chứa video** (ảnh, text post) | yt-dlp raise exception → hiện "Bài viết này không chứa video." |
| 3 | Video bị xóa / không tồn tại | Bắt `DownloadError` từ yt-dlp → "Video không tồn tại hoặc đã bị xóa." |
| 4 | Video riêng tư (cần đăng nhập) | Detect `AuthRequiredError` → hiện dialog hướng dẫn export cookies + nút mở Settings |
| 5 | URL chứa **tracking params** dài (fbclid, mibextid...) | Không ảnh hưởng — yt-dlp tự xử lý. Regex chỉ validate domain, không chặn query params |
| 6 | User dán URL có **khoảng trắng** đầu/cuối | `url.strip()` trước khi validate |
| 7 | User dán **nhiều URL** hoặc dán cả **bài viết dài** | Tự động kích hoạt hộp thoại `BulkImportDialog`, sử dụng `SmartTextParser` bóc tách toàn bộ link, giải mã `l.facebook.com`, gọt sạch mã tracking (`fbclid`, `si`, `utm_*`) và đưa vào hàng đợi phát kèm nhãn tiền tố |
| 8 | URL redirect nhiều lần (fb.watch → facebook.com → ...) | yt-dlp tự follow redirect. Nếu quá 5 redirect → timeout |
| 9 | yt-dlp trả về **nhiều video** (playlist/album) | Chỉ phát video đầu tiên. Hiện thông báo "Đã chọn video đầu tiên trong album" |
| 10 | **Stream URL hết hạn** (token expired sau 1-4h) | Detect playback error (`on_error` callback) → auto re-resolve URL gốc → phát tiếp từ vị trí cũ |
| 11 | yt-dlp **quá cũ**, không extract được | Bắt exception → hiện "yt-dlp cần cập nhật" + nút "Cập nhật ngay" |
| 12 | **Cookies.txt sai format** hoặc hết hạn | Bắt lỗi yt-dlp → "Cookies không hợp lệ hoặc đã hết hạn. Vui lòng export lại." |

### 7.2 Playback & VLC

| # | Tình huống | Xử lý |
|---|---|---|
| 13 | User **seek trước khi video buffer xong** | Disable seek bar cho tới khi VLC state = `Playing` (tránh crash/seek sai) |
| 14 | User **seek quá cuối video** (timestamp > duration) | Clamp về duration - 1 giây. Hiện toast "Đã nhảy tới cuối video" |
| 15 | User **seek về trước 0** (timestamp âm) | Clamp về 0 |
| 16 | User nhấn **Play lúc đang resolve** URL trước đó | Disable nút Play + hiện loading. Nếu nhấn lại → cancel resolve cũ, bắt đầu resolve mới |
| 17 | User dán **URL mới khi đang phát** video cũ | Stop video cũ → resolve URL mới → phát. Lưu position video cũ vào history |
| 18 | Video phát **xong** (end reached) | Dừng ở frame cuối (không loop). Nút Play chuyển thành "Phát lại". Seek bar về cuối |
| 19 | **Livestream** | Disable seek bar, ẩn timestamp jump, ẩn tốc độ phát, hiện badge "🔴 LIVE" |
| 20 | Video rất dài (>2h) | Không giới hạn — VLC xử lý tốt. Seek bar scale tự động. Time label dạng `h:mm:ss` |
| 21 | Video **chỉ có audio** (không có hình) | VLC phát audio bình thường. Video surface hiện placeholder/thumbnail |
| 22 | **Codec không hỗ trợ** (hiếm) | VLC handle hầu hết codec. Nếu fail → hiện "Không thể phát video này. Thử tắt Hardware Decode trong Settings." |

### 7.3 Network

| # | Tình huống | Xử lý |
|---|---|---|
| 23 | **Mất mạng** lúc đang resolve | yt-dlp retry 3 lần (đã config). Sau 3 lần → "Không thể kết nối. Kiểm tra mạng." |
| 24 | **Mất mạng** lúc đang phát | VLC tự buffer/retry. Nếu buffer hết → hiện overlay "Đang kết nối lại..." Khi có mạng → tiếp tục tự động |
| 25 | **Mạng chậm** (video giật) | VLC sử dụng network-caching buffer. Nếu giật liên tục → gợi ý tăng buffer trong Settings hoặc giảm chất lượng |

### 7.4 GUI & UX

| # | Tình huống | Xử lý |
|---|---|---|
| 26 | User **resize cửa sổ** | Video surface co giãn theo (VLC tự scale). Giữ aspect ratio. Tôn trọng `MIN_WINDOW_WIDTH/HEIGHT` |
| 27 | User **double-click** vào video surface | Toggle fullscreen (hành vi quen thuộc từ mọi video player) |
| 28 | **Clipboard không chứa URL** khi nhấn "Dán & Phát" | Hiện toast/label "Clipboard không chứa URL Facebook hợp lệ" (không crash, không dialog chặn) |
| 29 | User mở **Settings khi đang phát** video | Video tiếp tục phát. Settings là Toplevel window riêng, không block main window |
| 30 | User **đóng app** khi đang phát | `WM_DELETE_WINDOW` → save position → stop VLC → đóng socket proxy bất đồng bộ → shutdown threads → destroy (xem §9.2 E) |
| 31 | User nhấn **phím tắt** khi focus ở ô URL input | Phím `Space`, `←`, `→` phải nhập text bình thường trong Entry. Chỉ trigger shortcut khi focus KHÔNG ở Entry widget |

### 7.5 System & Environment

| # | Tình huống | Xử lý |
|---|---|---|
| 32 | **VLC chưa cài** | Kiểm tra lúc startup → dialog: "Cần cài VLC Media Player" + link download + hướng dẫn chọn 64-bit |
| 33 | **VLC sai bit** (32-bit VLC + 64-bit Python) | Detect mismatch → "VLC 32-bit không tương thích Python 64-bit. Vui lòng cài VLC 64-bit." |
| 34 | **FFmpeg chưa cài** | Cảnh báo (không chặn): "FFmpeg chưa cài. Một số video có thể không phát được âm thanh." |
| 35 | **settings.json bị corrupt** (JSON invalid) | Bắt `JSONDecodeError` → xóa file cũ, tạo mới từ defaults. Log cảnh báo |
| 36 | **history.db bị corrupt** | Bắt SQLite error → xóa DB cũ, tạo mới. Mất lịch sử cũ nhưng app không crash |
| 37 | **Nhiều instance app** chạy đồng thời | Cho phép — không lock single instance. SQLite dùng WAL mode để tránh lock conflict |
| 38 | **Ổ đĩa đầy** (không ghi được settings/history) | Bắt `OSError` → hiện cảnh báo, app vẫn chạy bình thường (chỉ không lưu được) |

### 7.6 Re-resolve Strategy (Stream URL hết hạn)

Facebook stream URL có **token thời hạn** (thường 1-4 giờ). Khi hết hạn, VLC sẽ báo lỗi phát. Cần xử lý tự động:

```
Video đang phát bình thường
        │
        ▼
VLC báo lỗi (on_error callback)
        │
        ▼
┌─────────────────────────────────┐
│ Lưu vị trí hiện tại (position) │
│ Hiện overlay "Đang tải lại..." │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ Re-resolve URL gốc (yt-dlp)    │  ← Thread riêng, không block GUI
│ (dùng URL Facebook ban đầu,    │
│  KHÔNG phải stream URL cũ)     │
└────────┬────────────────────────┘
         │
    ┌────┴────┐
    │ Thành   │ Thất bại
    │ công    │    │
    ▼         │    ▼
 Phát tiếp    │  Hiện lỗi + nút "Thử lại"
 từ position  │
 đã lưu       │
```

```python
# Lưu URL gốc (Facebook URL) — KHÔNG phải stream URL
self._original_url = facebook_url    # "https://facebook.com/reel/123"
self._stream_url = resolved.stream_url  # URL tạm thời có token

def _on_playback_error(self, error_msg: str):
    """Callback khi VLC báo lỗi."""
    saved_position = self.player.get_position()

    # Chỉ re-resolve nếu đã phát được ít nhất 5 giây (tránh loop lỗi)
    if saved_position > 5000:
        self._re_resolve(saved_position)
    else:
        self._show_error(error_msg)

def _re_resolve(self, resume_position: int):
    """Re-resolve URL gốc và phát tiếp."""
    self._show_overlay("Đang tải lại...")
    _executor.submit(self._do_re_resolve, resume_position)

def _do_re_resolve(self, resume_position: int):
    try:
        result = resolve_facebook_url(self._original_url)
        self._stream_url = result.stream_url
        self.root.after(0, lambda: self._resume_playback(result.stream_url, resume_position))
    except Exception as e:
        self.root.after(0, lambda: self._show_retry_dialog(str(e)))

def _resume_playback(self, new_stream_url: str, position: int):
    """Phát video mới từ vị trí cũ."""
    self.player.play(new_stream_url)
    # Đợi VLC bắt đầu phát rồi mới seek (cần delay nhỏ)
    self.root.after(500, lambda: self.player.seek_to(position))
    self._hide_overlay()
```

> [!IMPORTANT]
> - **Luôn giữ `_original_url`** (URL Facebook) — đây là URL duy nhất ổn định. Stream URL là tạm thời.
> - **Chỉ re-resolve tối đa 3 lần liên tiếp** — nếu thất bại 3 lần → dừng, hiện lỗi, tránh loop vô hạn.
> - **Delay 500ms trước khi seek** sau khi phát stream mới — VLC cần thời gian init media.

### 7.7 Seek Bar — Chi tiết kỹ thuật

Seek bar trên network stream được tối ưu hóa đặc biệt với cơ chế tính toán tọa độ chuột và xem trước thời gian thực (Real-time Timestamp Preview):

```python
class SeekBarController:
    """Quản lý seek bar logic — tính tọa độ chuột, preview thời gian thực và tránh giật xung đột."""

    def __init__(self, scale_widget: ttk.Scale, on_seek: Callable[[int], None], on_preview: Optional[Callable[[int], None]] = None):
        self.scale = scale_widget
        self.on_seek = on_seek
        self.on_preview = on_preview
        self._is_user_dragging = False  # True khi user đang kéo/giữ chuột trên seek bar
        self._is_seeking = False        # True khi đang chờ VLC seek xong (debounce 350ms)

        self.scale.bind("<ButtonPress-1>", self._on_drag_start)
        self.scale.bind("<B1-Motion>", self._on_drag_motion)
        self.scale.bind("<ButtonRelease-1>", self._on_drag_end)

    def _get_value_from_x(self, x: int) -> float:
        """Tính toán giá trị timestamp mục tiêu (ms) từ tọa độ ngang con trỏ chuột."""
        width = max(1, self.scale.winfo_width())
        fraction = max(0.0, min(1.0, x / float(width)))
        from_ = float(self.scale.cget("from"))
        to_ = float(self.scale.cget("to"))
        return from_ + fraction * (to_ - from_)

    def _on_drag_start(self, event):
        self._is_user_dragging = True
        self._is_seeking = False
        val = self._get_value_from_x(event.x)
        self.scale.set(val)
        if self.on_preview:
            self.on_preview(int(val))
        return "break"

    def _on_drag_motion(self, event):
        if self._is_user_dragging:
            val = self._get_value_from_x(event.x)
            self.scale.set(val)
            if self.on_preview:
                self.on_preview(int(val))
            return "break"

    def _on_drag_end(self, event):
        if self._is_user_dragging:
            val = self._get_value_from_x(event.x)
            self.scale.set(val)
            self._is_user_dragging = False
            target_ms = int(val)
            self._is_seeking = True
            if self.on_preview:
                self.on_preview(target_ms)
            self.on_seek(target_ms)
            self.scale.after(350, self._confirm_seek)
            return "break"

    def cancel_drag(self, current_ms: int = 0):
        """Hủy kéo khi nhấn Escape, hoàn tác về thời gian đang phát."""
        self._is_user_dragging = False
        self._is_seeking = False
        self.scale.set(current_ms)

    def update_position(self, current_ms: int, duration_ms: int):
        """Cập nhật vị trí thanh trượt từ VLC loop — CHỈ khi user KHÔNG tương tác."""
        if not self._is_user_dragging and not self._is_seeking:
            if duration_ms > 0:
                self.scale.configure(to=duration_ms)
                self.scale.set(current_ms)
```

> **Nguyên tắc trải nghiệm người dùng (UX):**
> 1. Khi người dùng click hoặc kéo chuột trên thanh trượt, con trượt (`thumb`) và mốc thời gian hiển thị (`lbl_time`) phải nhảy và di chuyển tức thì theo con trỏ chuột.
> 2. Hiển thị huy hiệu OSD nổi trên video (`⏱️ mm:ss / mm:ss`) kèm thanh tiến trình nhỏ để người dùng dễ quan sát trực tiếp trên màn hình video.
> 3. Vòng lặp cập nhật từ VLC (`update_playback_time`) tuyệt đối **không ghi đè** lên nhãn thời gian và thanh trượt khi `is_user_interacting` đang là `True`.
> 4. Nhấn phím `Escape` khi đang kéo sẽ hủy thao tác (`cancel_drag`) và đưa con trượt về mốc thời gian đang phát hiện tại.

---

## 8. Startup & Initialization Flow

```python
def main():
    # 1. Kiểm tra VLC đã cài chưa
    if not check_vlc_installed():
        show_vlc_install_dialog()
        sys.exit(1)

    # 2. Kiểm tra yt-dlp version (cảnh báo nếu quá cũ)
    check_ytdlp_version()

    # 3. Tạo thư mục config (~/.fb-video-watcher/)
    ensure_config_dir()

    # 4. Khởi tạo GUI
    app = Application()
    app.run()  # tkinter mainloop
```

#### Kiểm tra VLC:
```python
import ctypes, os, sys

def check_vlc_installed() -> bool:
    """Thử load libvlc.dll. Trả False nếu không tìm thấy."""
    try:
        import vlc
        vlc.Instance('--quiet')
        return True
    except OSError:
        return False
```

---

## 9. Threading Model & Performance

### 9.1 Threading Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Main Thread     │     │  Resolver Thread  │     │  VLC Event Thread │
│   (Tkinter GUI)   │     │  (yt-dlp calls)   │     │  (libVLC internal) │
│                    │     │                    │     │                    │
│  - UI rendering    │     │  - URL resolution  │     │  - Time changed    │
│  - User input      │◄────│  - Format selection│     │  - End reached     │
│  - Widget update   │     │                    │     │  - Error events     │
│                    │     │                    │     │                    │
│  root.after() ◄────┼─────┼────────────────────┼─────┤                    │
│  (marshal events)  │     │                    │     │                    │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

- **Main thread:** Tkinter mainloop — MỌI thao tác UI phải trên thread này.
- **Resolver thread:** Chạy yt-dlp (IO-bound, có thể mất 3-15 giây). Dùng `threading.Thread`.
- **VLC events:** libVLC tự quản lý thread riêng. Callback từ VLC events phải dùng `root.after(0, callback)` để marshal về main thread.

> ⚠️ **QUAN TRỌNG:** Không bao giờ gọi Tkinter widget methods từ thread khác main thread. Luôn dùng `root.after()`.

### 9.2 Tối ưu hiệu năng & Chống "Not Responding"

> [!IMPORTANT]
> App phải ưu tiên **trải nghiệm mượt** hơn tiết kiệm tài nguyên. Config tối ưu được **auto-detect** dựa trên phần cứng thực tế (xem `system_info.py` + `auto_tune.py` trong Agent.md). Không được để app bị "Not Responding" trong bất kỳ tình huống nào.

#### A. Nguyên tắc vàng: KHÔNG BAO GIỜ block Main Thread

Mọi thao tác có thể mất >50ms **PHẢI** chạy trên thread riêng:

| Thao tác | Thời gian ước tính | Giải pháp |
|---|---|---|
| Resolve URL (yt-dlp) | 3–15 giây | `threading.Thread(daemon=True)` |
| Lưu history (SQLite) | 5–50ms | `threading.Thread` hoặc `root.after()` nếu < 50ms |
| Kiểm tra VLC installed | 100–500ms | Chạy lúc startup, hiện splash/loading |
| Load thumbnail | 1–5 giây | `threading.Thread(daemon=True)` |

```python
# ❌ SAI — block main thread, gây "Not Responding"
def on_play_clicked():
    stream_url = resolve_facebook_url(url)  # Block 3-15 giây!
    player.play(stream_url)

# ✅ ĐÚNG — resolve trên thread riêng, callback về main thread
def on_play_clicked():
    show_loading_indicator()
    disable_play_button()
    thread = threading.Thread(
        target=_resolve_and_play,
        args=(url,),
        daemon=True
    )
    thread.start()

def _resolve_and_play(url: str):
    try:
        result = resolve_facebook_url(url)
        # Marshal về main thread
        root.after(0, lambda: _on_resolved(result))
    except Exception as e:
        root.after(0, lambda: _on_resolve_error(e))

def _on_resolved(result: ResolvedVideo):
    hide_loading_indicator()
    enable_play_button()
    player.play(result.stream_url)
```

#### B. VLC Caching — Buffer cho streaming mượt

VLC args **KHÔNG được hardcode** — phải build động bằng `AutoTuner` (xem Agent.md §3):

```python
# ❌ SAI — hardcode
VLC_ARGS = ['--network-caching=3000', '--avcodec-hw=dxva2', '--avcodec-threads=4']

# ✅ ĐÚNG — build từ auto_tune + user settings
from main.system_info import SystemInfo
from main.auto_tune import AutoTuner

sys_info = SystemInfo.detect()
tuner = AutoTuner(sys_info, user_settings)
vlc_args = tuner.build_vlc_args()
# Kết quả ví dụ trên máy i5-13500:
#   ['--quiet', '--no-video-title-show', '--network-caching=5000',
#    '--file-caching=2500', '--live-caching=5000',
#    '--avcodec-hw=d3d11va', '--avcodec-threads=4']
# Kết quả ví dụ trên laptop i3 cũ, 4GB RAM:
#   ['--quiet', '--no-video-title-show', '--network-caching=1500',
#    '--file-caching=1000', '--live-caching=1500',
#    '--avcodec-threads=1']
```

**Giá trị default trong `constants.py`** (dùng khi auto-detect thất bại):

| VLC arg | Default | Auto-tune logic |
|---|---|---|
| `--network-caching` | 3000ms | RAM < 4GB → 1500, 4-8GB → 3000, >8GB → 5000 |
| `--file-caching` | 2000ms | = network_caching / 2, tối thiểu 1000 |
| `--live-caching` | 3000ms | = network_caching |
| `--avcodec-hw` | `auto` | NVIDIA/AMD/Intel → `d3d11va` (Win10+), fallback `dxva2`, unknown → bỏ (software) |
| `--avcodec-threads` | `0` (auto) | ≤4 cores → 1, 4-8 → 2, 8-16 → 4, >16 → 6 |

#### C. UI Update Interval — Cập nhật seek bar

```python
# Seek bar + time label cập nhật mỗi 250ms (4 FPS cho UI)
# Đủ mượt mắt, không tốn CPU cho việc update widget liên tục
UI_UPDATE_INTERVAL_MS = 250

def _start_ui_timer(self):
    """Gọi sau khi video bắt đầu phát."""
    self._update_ui()

def _update_ui(self):
    if self.player.state == 'playing':
        current = self.player.get_position()    # ms
        duration = self.player.get_duration()    # ms
        self.seek_bar.set(current)
        self.time_label.config(
            text=f"{format_time(current)} / {format_time(duration)}"
        )
    # Lặp lại — dùng root.after() thay vì while loop
    self._ui_timer_id = self.root.after(UI_UPDATE_INTERVAL_MS, self._update_ui)
```

> **KHÔNG DÙNG `while True` loop** để cập nhật UI. Dùng `root.after()` để schedule — giữ mainloop luôn responsive.

#### D. Resolver với ThreadPoolExecutor (tái sử dụng thread)

```python
import concurrent.futures

# Tạo 1 lần duy nhất, tái sử dụng thread pool — tránh overhead tạo thread mới mỗi lần
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,        # 1 cho resolve, 1 cho thumbnail/history
    thread_name_prefix="fbw-worker"
)

def resolve_async(url: str, callback, error_callback):
    """Submit resolve task vào thread pool."""
    future = _executor.submit(resolve_facebook_url, url)
    future.add_done_callback(
        lambda f: root.after(0, lambda: _handle_future(f, callback, error_callback))
    )
```

#### E. Xử lý trường hợp app "treo" khi tắt

```python
def on_closing():
    """Gọi khi user đóng cửa sổ."""
    # 1. Dừng video trước (tránh VLC thread chạy mồ côi)
    player.stop()

    # 2. Lưu history (nhanh, < 50ms)
    history.save_position(current_url, player.get_position())

    # 3. Shutdown thread pool (đợi tối đa 2 giây)
    _executor.shutdown(wait=True, cancel_futures=True)

    # 4. Destroy GUI
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)
```

#### F. Tóm tắt config hiệu năng

| Parameter | Default | Dynamic | Lý do |
|---|---|---|---|
| `--network-caching` | 3000ms | Auto-tune theo RAM | Buffer rộng, tránh giật |
| `--avcodec-hw` | `auto` | Auto-detect GPU vendor | Hardware decode nếu có |
| `--avcodec-threads` | `0` (auto) | Auto-tune theo CPU cores | Tận dụng multi-core |
| `UI_UPDATE_INTERVAL_MS` | 250ms | Cố định | Mượt mắt, không spam CPU |
| `ThreadPoolExecutor` | 2 workers | Auto-tune theo CPU cores | Tái sử dụng thread |
| Resolver | daemon thread | — | Tự chết khi app đóng |

> [!TIP]
> Tất cả giá trị trên đều có thể bị **user override** qua Settings Panel. Auto-tune chỉ là giá trị khuyến nghị ban đầu.

### 9.3 Local Stream Proxy — vòng đời và chống treo GUI

Telegram và một số nguồn đặc biệt được phát qua `StreamProxyServer` tại
`127.0.0.1`. Một request proxy có thể còn sống khi VLC đang pause, vì handler
đang chờ chunk tiếp theo hoặc đang ghi dữ liệu vào socket của VLC. Do đó proxy
không được đóng đồng bộ trên Tkinter main thread.

Các yêu cầu bắt buộc:

1. HTTP server phải dùng request thread daemon và `block_on_close = False` để
   `server_close()` không chờ vô hạn một handler stream cũ.
2. `StreamProxyHandler` phải đăng ký socket đang hoạt động; khi shutdown,
   proxy chủ động `shutdown()`/`close()` các socket này để đánh thức handler.
3. Khi đổi từ Telegram sang nguồn không dùng proxy: dừng VLC trước, sau đó gọi
   `StreamProxyServer.stop_async()`, rồi mới nạp media mới vào VLC.
4. Khi đóng ứng dụng, proxy cũng phải được shutdown trên daemon thread; không
   được gọi thao tác có thể chờ socket trực tiếp từ Tkinter main thread.
5. Việc này không được thay đổi `network_caching`, `file_caching`,
   `live_caching` hoặc bất kỳ thiết lập Auto-Tuner nào của người dùng.

Luồng chuyển video an toàn:

```
VLC Telegram (playing/paused)
        │
        ▼
player.stop()  ── đóng client socket
        │
        ▼
StreamProxyServer.stop_async()
        │
        ├── đóng socket còn hoạt động
        ├── shutdown listening server
        └── không chặn Tkinter main thread
        │
        ▼
player.play(YouTube stream)
```

---

## 10. Timestamp Parser (`timestamp.py`)

Phải hỗ trợ nhiều format input từ user:

| Input | Kết quả (ms) | Giải thích |
|---|---|---|
| `"90"` | 90000 | 90 giây |
| `"1:30"` | 90000 | 1 phút 30 giây |
| `"1:01:30"` | 3690000 | 1 giờ 1 phút 30 giây |
| `"1h30m"` | 5400000 | 1 giờ 30 phút |
| `"1h30m45s"` | 5445000 | 1 giờ 30 phút 45 giây |
| `"30s"` | 30000 | 30 giây |
| `"5m"` | 300000 | 5 phút |
| `""` hoặc invalid | `ValueError` | Báo lỗi |

```python
def parse_timestamp(text: str) -> int:
    """Parse chuỗi timestamp → milliseconds. Raise ValueError nếu invalid."""
```

---

## 11. Config & Settings (`constants.py`)

```python
# --- App ---
APP_NAME = "FB Video Watcher"
from main import __version__
APP_VERSION = __version__  # Dynamic Single Source of Truth from main/__init__.__version__
CONFIG_DIR = Path.home() / ".fb-video-watcher"
HISTORY_DB = CONFIG_DIR / "history.db"
COOKIE_FILE = CONFIG_DIR / "cookies.txt"  # Optional

# --- Window ---
DEFAULT_WINDOW_WIDTH = 960
DEFAULT_WINDOW_HEIGHT = 640
MIN_WINDOW_WIDTH = 640
MIN_WINDOW_HEIGHT = 480

# --- VLC (Giá trị DEFAULT — sẽ bị override bởi auto_tune.py và settings.json) ---
# KHÔNG hardcode cho CPU/GPU cụ thể. Xem Agent.md §3 để hiểu cách build VLC args.
VLC_ARGS_DEFAULTS = {
    'network_caching': 3000,     # ms — auto_tune sẽ điều chỉnh theo RAM
    'file_caching': 2000,        # ms
    'live_caching': 3000,        # ms
    'hw_accel': 'auto',          # 'auto' | 'dxva2' | 'd3d11va' | 'none'
    'decode_threads': 0,         # 0 = auto (dựa trên CPU cores)
}

# --- Playback ---
DEFAULT_VOLUME = 80            # 0-150
SEEK_SHORT = 5                 # giây (phím ←→)
SEEK_LONG = 30                 # giây (Shift+←→)
SPEED_OPTIONS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
MAX_VIDEO_HEIGHT = 1080        # Giới hạn resolution khi resolve (user có thể chỉnh trong Settings)
UI_UPDATE_INTERVAL_MS = 250    # Cập nhật seek bar mỗi 250ms (4 FPS cho UI)

# --- URL ---
FB_URL_PATTERN = re.compile(
    r'https?://(?:www\.|m\.|mbasic\.)?facebook\.com/.+|'
    r'https?://fb\.watch/.+|'
    r'https?://fb\.gg/.+'
)

# --- Resolver ---
RESOLVE_TIMEOUT = 15           # giây
RESOLVE_RETRIES = 3
```

---

## 12. Yêu cầu hệ thống (System Requirements)

| Yêu cầu | Chi tiết |
|---|---|
| **OS** | Windows 10/11 (64-bit) |
| **Python** | 3.10+ (khuyến nghị 3.12) |
| **VLC** | 3.0.x trở lên, **64-bit** (phải khớp Python) |
| **RAM** | ~50-100 MB (so với ~500MB-1GB khi dùng browser) |
| **Network** | Kết nối Internet |
| **FFmpeg** | Khuyến nghị cài (cho trường hợp video+audio tách stream) |

---

## 13. Quy trình phát triển đề xuất

### Phase 1: Core (MVP)
1. ✅ `timestamp.py` — Parser timestamp (đơn giản nhất, viết test trước)
2. ✅ `url_resolver.py` — Resolve URL Facebook qua yt-dlp
3. ✅ `vlc_player.py` — Khởi tạo VLC, phát stream URL, seek
4. ✅ `gui.py` — GUI cơ bản: URL input + video surface + play/pause + seek bar + timestamp jump
5. ✅ `main.py` — Kết nối tất cả, chạy được

### Phase 2: Polish
6. Keyboard shortcuts
7. Fullscreen mode
8. Speed control
9. Error handling hoàn chỉnh
10. Loading/buffering indicators

### Phase 3: Extras
11. History (SQLite) + Resume playback
12. Cookie support cho video riêng tư
13. "Dán & Phát" — one-click từ clipboard
14. Tự động re-resolve khi stream URL hết hạn
15. Remember window size/position

---

## 14. Lưu ý cho người viết code

> [!IMPORTANT]
> 1. **yt-dlp phải dùng API Python** (`yt_dlp.YoutubeDL`), KHÔNG gọi subprocess — tránh overhead và dễ handle exception.
> 2. **VLC `set_hwnd()`** chỉ hoạt động SAU KHI Tkinter frame đã `pack()`/`grid()` và `update_idletasks()`.
> 3. **Callback từ VLC events** PHẢI marshal về main thread bằng `root.after(0, fn)` — nếu không sẽ crash hoặc deadlock.
> 4. **Resolver chạy trên thread riêng** — GUI phải responsive trong lúc resolve (hiện loading).
> 5. **Test thực tế** với các loại URL: reel, watch, share link, fb.watch redirect.
> 6. **yt-dlp cần cập nhật thường xuyên** — Facebook thay đổi API liên tục. Nên có nút/menu "Cập nhật yt-dlp" trong app.

> [!TIP]
> - Dùng `player.set_time(ms)` thay vì `player.set_position(float)` cho seek chính xác.
> - Source code nằm trong folder `main/`, entry point là `main.py` ở root (import từ `main/`).

---

## 15. README.md — Yêu cầu viết

> [!IMPORTANT]
> **Phải viết file `README.md`** ở thư mục gốc project. Đây là file người dùng đọc đầu tiên khi clone repo hoặc mở GitHub.

### Cấu trúc README bắt buộc:

```markdown
# FB Video Watcher

> Mô tả ngắn 1-2 dòng về app.

## 📸 Screenshot
(Ảnh chụp giao diện app — thêm sau khi có GUI hoàn chỉnh)

## ✨ Tính năng
- Danh sách các tính năng chính (bullet points)

## 📋 Yêu cầu hệ thống
- OS, Python version, VLC, FFmpeg...

## 🚀 Cài đặt & Chạy
### Bước 1: Clone repo
### Bước 2: Tạo môi trường ảo .fbwenv
### Bước 3: Cài dependencies
### Bước 4: Chạy app

## 🎮 Cách sử dụng
- Hướng dẫn dán URL, phát video, nhảy timestamp...

## ⌨️ Phím tắt
- Bảng keyboard shortcuts

## ⚙️ Cài đặt (Settings)
- Cách mở Settings, các tùy chỉnh có sẵn

## 🔒 Video riêng tư (Cookies)
- Hướng dẫn export cookies từ browser

## 🐛 Xử lý lỗi thường gặp
- VLC chưa cài, sai bit version, video bị xóa...

## 📄 License
(MIT hoặc tùy chọn)
```

### Yêu cầu nội dung:
- Viết bằng **tiếng Việt** (target user là người Việt).
- Phải có lệnh cài đặt **copy-paste được** (code block).
- Phải ghi rõ tạo môi trường ảo `.fbwenv`.
- Section phím tắt phải khớp với bảng keyboard shortcuts trong specs.

---

## 16. Kế hoạch tối ưu hóa bộ nhớ & Cơ chế "Xài xong dọn" (Memory Cleanup & Lifecycle Management)

> [!IMPORTANT]
> **NGUYÊN TẮC BẤT KHẢ XÂM PHẠM: TUÂN THỦ 100% CÀI ĐẶT CỦA NGƯỜI DÙNG**
> * **TUYỆT ĐỐI KHÔNG can thiệp, KHÔNG tự ý thay đổi** các thông số cài đặt streaming của người dùng và Auto-Tuner (bao gồm `network_caching`, `file_caching`, `hardware_decode`, `decode_threads`).
> * Nếu người dùng hoặc Auto-Tuner chọn bộ đệm 3000ms hay 5000ms, hệ thống **bắt buộc giữ nguyên 100%** để đảm bảo chất lượng phát và tính toàn vẹn của cấu hình.
> * Toàn bộ công tác tối ưu chỉ tập trung vào việc **triệt tiêu rác bộ nhớ thực sự (Dead Memory, Stale Metadata, Leftover Files, Circular References, Uncommitted OS Pages)** sinh ra trong quá trình xử lý ngầm, hoàn toàn không "ăn bớt" bộ đệm phát video của người dùng.

### 16.1 Hiện trạng & Thành tựu tối ưu kỹ thuật
* **Tiến trình Bootloader launcher (`FB-Video-Watcher.exe`):** ~1.1 MB – 6.9 MB RAM.
* **Tiến trình chính (`FB-Video-Watcher.exe`):** **~35 – 45 MB RAM** (Working Set thực tế khi phát video 1080p và sau khi tua/nhảy mốc trong video siêu dài 10 tiếng, giảm ngoạn mục từ đỉnh ~568 MB - tiết kiệm hơn **93%** RAM).
* **Mức tiêu thụ CPU:** Cực kỳ nhàn rỗi, chỉ **~0.4%** trên CPU đa nhân hiện đại.
* **Phân tích đỉnh RAM gốc (Peak Working Set trước khi dọn):**
  1. **Direct3D 11 Graphics Drivers kép (Intel UHD 770 + NVIDIA RTX 4060):** Chiếm ~340 MB (~60% RAM) do nạp cùng lúc hai bộ shader compiler (`nvgpucomp64.dll`: 94MB, `nvwgf2umx.dll`: 85MB, `igc64.dll`: 82MB, `media_bin_64.dll`: 22MB) khi giải mã trên iGPU và xuất hình qua dGPU.
  2. **Windows System & DirectX Runtime:** ~153 MB (Font Cache DirectWrite, D3DCompiler, DWM).
  3. **VLC Demuxer & Codec Plugins:** ~51 MB (bảng chỉ mục khung hình video dài).
  4. **Toàn bộ Python App, GUI & SQLite:** Chỉ chiếm đúng **~25.9 MB (<5%)**.

* **Mục tiêu đề ra:**
  * **"Xài xong là dọn":** Mọi tài nguyên tạm (biến, session, file temp, dialog instance, media cũ) phải được dọn dẹp dứt điểm ngay khi hoàn thành tác vụ.
  * **Ổn định dài hạn (Zero Memory Leak):** Xem liên tục nhiều giờ hoặc đổi qua lại 20+ video không làm RAM tăng lũy kế (giữ mức tiêu thụ phẳng ~40MB).
  * **Không làm bẩn máy người dùng:** Không để lại file thừa trong thư mục Downloads, Desktop hay `%TEMP%`.
  * **Zero Lag:** Dọn dẹp trên worker thread ngầm, không gây giật hình hay khựng thanh trượt GUI.

### 16.2 Chi tiết 7 khu vực cần triển khai "Xài xong dọn"

#### 🧹 1. Cắt tỉa dữ liệu `info_dict` khổng lồ & Dọn rác Resolver
* **File liên quan:** `main/extractors/generic.py`, `main/extractors/youtube.py`, `main/app.py`
* **Vấn đề:** `ydl.extract_info(url, download=False)` trả về `info_dict` chứa hàng trăm trường không cần thiết (hàng chục format biến thể, thumbnails đầy đủ, automatic captions, request logs, comments) ngốn từ 25MB – 45MB RAM.
* **Quy chuẩn kỹ thuật:**
  1. Trong hàm `extract()` của cả hai file, ngay sau khi đã xác định xong `stream_url`, `audio_url`, `title`, `duration`, `thumbnail`, `width`, `height`, `http_headers`:
     * Chỉ lưu vào `ResolvedVideo` danh sách format tinh gọn (hoặc format đã chọn), không lưu toàn bộ 50–100 formats thô.
     * Giải phóng dữ liệu thô: `del info_dict`, `del formats_raw`.
  2. Trong `main/app.py` tại worker thread phân giải (hàm `_resolve_url_worker`): Ngay sau khi resolve xong và gửi kết quả về main thread, gọi `gc.collect()`. Gọi trên worker thread ngầm đảm bảo **không hề làm khựng giao diện** chính.

#### 🧹 2. Tự động dọn dẹp file thừa sau Auto-Update
* **File liên quan:** `main/updater.py`, `main/app.py`
* **Vấn đề:** File `.exe` cũ đổi tên thành `.old`. Nếu OneDrive/Defender khóa ngầm lúc PowerShell chạy, file `.old` (~100MB!) bị kẹt lại vĩnh viễn trên Desktop/thư mục app.
* **Quy chuẩn kỹ thuật:**
  1. Trong `main/updater.py`: Bổ sung hàm `cleanup_updater_leftovers()` để quét và xóa sạch file `FB-Video-Watcher.exe.old` và các file `update_*.zip`, `fbw_update_*` tạm trong thư mục Temp.
  2. Trong `main/app.py`: Gọi `cleanup_updater_leftovers()` một lần duy nhất lúc khởi động ứng dụng (trên daemon thread ngầm).

#### 🧹 3. Dọn file `.part` / `.ytdl` tải dở dang khi Hủy tải
* **File liên quan:** `main/downloader.py`
* **Vấn đề:** Khi người dùng bấm Hủy (Cancel) hoặc mất mạng, `yt-dlp` để lại các file tải dở `.part` / `.ytdl` trong thư mục Downloads.
* **Quy chuẩn kỹ thuật:**
  * Trong class `VideoDownloader`, khi `self._cancelled = True` hoặc trong khối ngoại lệ, tự động quét và xóa sạch các file `.part` và `.ytdl` vừa tạo ra trong thư mục tải về.

#### 🧹 4. Dọn sạch file manifest `.m3u8` tạm của YouTube
* **File liên quan:** `main/extractors/youtube.py`, `main/app.py`
* **Vấn đề:** `_prepare_hls_master_manifest` tạo file `stream_{pid}_{timestamp}.m3u8` trong `%TEMP%/fbw_hls` cho VLC. Khi chuyển video khác, file cũ vẫn nằm trong ổ cứng.
* **Quy chuẩn kỹ thuật:**
  1. Khi tạo manifest mới: xóa file manifest cũ trước đó.
  2. Viết hàm `cleanup_hls_cache()` để dọn sạch thư mục `%TEMP%/fbw_hls`.
  3. Trong `app.shutdown()` khi tắt ứng dụng: gọi `cleanup_hls_cache()`.

#### 🧹 5. Giải phóng đối tượng `Media` và Frame Buffer của VLC
* **File liên quan:** `main/vlc_player.py`
* **Vấn đề:** `stop()` chỉ gọi `self.player.stop()` nhưng giữ `self._current_media`, khiến VLC tiếp tục giữ Direct3D textures và frame buffers trong RAM.
* **Quy chuẩn kỹ thuật:**
  * Cập nhật `stop()`: `self.player.stop()`, `self.player.set_media(None)`, `if self._current_media: self._current_media.release(); self._current_media = None`.

#### 🧹 6. Dọn dẹp vòng đời Hộp thoại Cài đặt (`SettingsDialog`) & Lịch sử
* **File liên quan:** `main/gui.py`
* **Vấn đề:** Khi đóng `SettingsDialog`, biến `self._settings_dialog` trên `MainWindow` vẫn giữ nguyên tham chiếu đến cả cây đối tượng hộp thoại (StringVars, 5 frame tabs, widget cây con, ảnh xem trước).
* **Quy chuẩn kỹ thuật:**
  * Bắt sự kiện `<Destroy>` của cửa sổ Toplevel: gán `self._settings_dialog = None`, xóa canvas image preview caches, và lên lịch gọi thu hồi RAM sau 100ms.

#### 🧹 7. Cơ chế Thu hồi vùng nhớ Windows Working Set (OS Memory Trimming)
* **File liên quan:** `main/platform_utils.py`, `main/app.py`
* **Bản chất kỹ thuật:**
  - Python runtime cấp phát bộ nhớ qua heap của C runtime và `VirtualAlloc`. Khi Python giải phóng đối tượng, trình quản lý bộ nhớ của Windows (NT Virtual Memory Manager) không tự động thu hồi (page-out) các trang bộ nhớ vật lý nhàn rỗi khỏi Working Set của tiến trình nếu hệ thống còn nhiều RAM trống.
  - Đặc biệt trên hệ thống đồ họa kép (Hybrid Dual-GPU: iGPU + dGPU), khi giải mã bằng iGPU và xuất hình qua dGPU, cả hai driver đồ họa đều nạp compiler vào tiến trình tạo đỉnh RAM tới 568MB. Khi tua xong, dữ liệu compiler này nhàn rỗi 100% nhưng bị Windows giữ lại.
* **Quy chuẩn kỹ thuật bắt buộc:**
  1. Trong `main/platform_utils.py`, hàm `trim_process_memory()` được triển khai chuẩn xác theo kiến trúc Win32 64-bit:
     ```python
     def trim_process_memory() -> None:
         """
         Yêu cầu Windows thu hồi các trang nhớ vật lý nhàn rỗi (stale working set pages)
         trả về lại RAM của hệ thống. An toàn tuyệt đối, không ảnh hưởng tiến trình.
         Chỉ gọi sau các tác vụ nặng đã hoàn thành (resolve, đóng dialog lớn, dừng media, sau khi tua/seek).
         - KHÔNG BAO GIỜ gọi trong vòng lặp UI timer 250ms.
         """
         if sys.platform == "win32":
             try:
                 from ctypes import wintypes
                 handle = ctypes.windll.kernel32.GetCurrentProcess()

                 # 1. Thử EmptyWorkingSet từ psapi / kernel32 (Chuẩn Win32 API)
                 try:
                     psapi = ctypes.windll.psapi
                     psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
                     psapi.EmptyWorkingSet.restype = wintypes.BOOL
                     if psapi.EmptyWorkingSet(handle):
                         return
                 except Exception:
                     pass

                 try:
                     k32 = ctypes.windll.kernel32
                     k32.K32EmptyWorkingSet.argtypes = [wintypes.HANDLE]
                     k32.K32EmptyWorkingSet.restype = wintypes.BOOL
                     if k32.K32EmptyWorkingSet(handle):
                         return
                 except Exception:
                     pass

                 # 2. Fallback sang SetProcessWorkingSetSize với SIZE_T 64-bit chuẩn
                 k32 = ctypes.windll.kernel32
                 k32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
                 k32.SetProcessWorkingSetSize.restype = wintypes.BOOL
                 size_t_max = ctypes.c_size_t(-1).value
                 k32.SetProcessWorkingSetSize(handle, size_t_max, size_t_max)
             except Exception:
                 pass
     ```
  > [!CAUTION]
  > **BẪY 64-BIT CTYPES CỰC KỲ NGUY HIỂM - CẤM TÁI PHẠM:**
  > Trên nền tảng Windows 64-bit, tuyệt đối **KHÔNG** gọi `SetProcessWorkingSetSize(handle, -1, -1)` mà không chỉ định `argtypes`! Mặc định `ctypes` sẽ truyền `-1` dưới dạng số nguyên có dấu 32-bit `0x00000000FFFFFFFF` (tương đương 4 GB) thay vì `(SIZE_T)-1` (`0xFFFFFFFFFFFFFFFF`). Lệnh gọi sẽ thất bại với mã lỗi `ERROR_INVALID_HANDLE` (return = 0) trong im lặng và Windows hoàn toàn không thu hồi bộ nhớ. Bắt buộc phải sử dụng `psapi.EmptyWorkingSet` với `argtypes=[wintypes.HANDLE]` hoặc `ctypes.c_size_t(-1).value`.

  2. Trong `main/app.py`: Hàm `_post_task_cleanup()` gọi `gc.collect()` và `trim_process_memory()`.
  3. **Cơ chế Debounced Post-Seek Trimming (`_schedule_post_seek_cleanup`, delay 2.5s):**
     - Khi người dùng kéo thanh tua liên tục hoặc bấm nhảy mốc thời gian, timer debounce được reset liên tục.
     - Sau khi dừng tua và video phát ổn định được 2.5s, timer kích hoạt gửi `_post_task_cleanup()` vào `self.executor` (`fbw-worker`) chạy ngầm.
     - Giúp thu hồi tức thì toàn bộ rác demuxer và shader compiler, đưa RAM từ ~500MB+ về thẳng mức sàn **~40 MB**.
  4. **Chu kỳ bảo trì định kỳ 60s (`_periodic_maintenance`):** Thu gom rác thế hệ 2 (`gc.collect()`), dọn Working Set ngầm và checkpoint SQLite WAL.
  5. **Quy tắc an toàn chống giật lag (Zero UI Lag):** Mọi lệnh dọn dẹp nặng CHỈ được chạy trên `ThreadPoolExecutor` ngầm (`fbw-worker`), TUYỆT ĐỐI KHÔNG gọi trực tiếp trên Tkinter UI thread, KHÔNG gọi trong vòng lặp 250ms của GUI.

### 16.3 Lộ trình triển khai kỹ thuật

| Bước | Hạng mục | File cần chỉnh sửa | Mục tiêu |
|---|---|---|---|
| **Bước 1** | Bổ sung hàm `trim_process_memory()` | `main/platform_utils.py` | Cung cấp công cụ hoàn trả RAM cho Windows |
| **Bước 2** | Dọn tàn dư Auto-Update (`.old`, `.zip`) | `main/updater.py`, `main/app.py` | Xóa sạch 100MB file cũ nếu bị kẹt |
| **Bước 3** | Cắt tỉa `info_dict` & dọn rác Resolver | `main/extractors/generic.py`, `main/extractors/youtube.py` | Giảm 30–45MB RAM rác sau phân giải |
| **Bước 4** | Dọn file `.part` dở dang khi Hủy tải | `main/downloader.py` | Giữ sạch thư mục Downloads của user |
| **Bước 5** | Dọn file `.m3u8` tạm & giải phóng `vlc.Media` | `main/extractors/youtube.py`, `main/vlc_player.py` | Xóa sạch buffer và manifest cũ khi đổi video |
| **Bước 6** | Hủy tham chiếu `SettingsDialog` khi đóng | `main/gui/settings_dialog.py` | Thu hồi toàn bộ UI objects khi đóng cửa sổ |
| **Bước 7** | Tích hợp `_post_task_cleanup()` & Post-Seek Debounce | `main/app.py` | Kích hoạt chu trình dọn dẹp tự động an toàn sau khi tua và bảo trì 60s |
| **Bước 8** | Chạy toàn bộ 288 bài Unit Test | Toàn bộ dự án | Đảm bảo 100% tests pass, không gây hồi quy |

---

### 16.4 Bộ quy chuẩn "Xài xong dọn" bắt buộc cho mọi Model AI & Developer khi thêm code mới

> [!IMPORTANT]
> **HƯỚNG DẪN DÀNH CHO CÁC MODEL AI & LẬP TRÌNH VIÊN PHÁT TRIỂN TIẾP NỐI:**
> Để ứng dụng luôn duy trì kỷ lục **~40 MB RAM** và không bao giờ bị phình bộ nhớ trở lại, mọi tính năng mới được thêm vào codebase BẮT BUỘC phải tuân thủ 5 điều răn sau:
> 1. **Nguyên tắc Debounce Post-Action:** Bất kỳ hành vi nào gây tải tạm thời (tua video, nạp subtitle nặng, import hàng loạt, chuyển đổi chất lượng) phải lập lịch dọn dẹp sau 2.0s – 2.5s qua `_schedule_post_seek_cleanup()` hoặc executor thread.
> 2. **Nguyên tắc Worker Pool Non-blocking:** Toàn bộ các thao tác `gc.collect()` và `trim_process_memory()` BẮT BUỘC chạy ngầm trên `self.executor` (`fbw-worker`), TUYỆT ĐỐI KHÔNG chạy trên Main UI Thread và TUYỆT ĐỐI KHÔNG đưa vào vòng lặp UI 250ms (`_update_ui_state`).
> 3. **Nguyên tắc Cắt tỉa Metadata thô:** Tuyệt đối không lưu trữ dữ liệu thô (raw JSON `info_dict`, HTTP headers, cookies, token xác thực, danh sách format 100+ items) vào các model sống lâu như `QueueItem`, `MainWindow`, `Application`. Chỉ lưu trữ các trường tối giản cần thiết.
> 4. **Nguyên tắc Hủy sạch tham chiếu UI Dialog:** Mọi cửa sổ con (`Toplevel`) như `SettingsDialog`, `BulkImportDialog`, `FFmpegSetupDialog` khi đóng phải gán tham chiếu về `None`, hủy toàn bộ timer con và gọi `_trim_memory_if_possible()`.
> 5. **Bảo tồn Win32 64-bit Trimming:** Giữ nguyên vẹn triển khai `trim_process_memory()` với `psapi.EmptyWorkingSet(handle)` và `wintypes.HANDLE`. Tuyệt đối không thay thế bằng các lệnh gọi ctypes thiếu `argtypes`.

---

## 17. Các tính năng mở rộng theo plan1.md

### 17.1 Hàng đợi phát liên tiếp (Playback Queue & Playlist)
- **Model `QueueItem` & `PlaybackQueue` (`main/playback_queue.py`):** Quản lý metadata danh sách phát gọn nhẹ, không lưu trữ direct stream URL, HTTP headers, token hay cookie lâu dài nhằm tránh phình bộ nhớ và tránh lỗi CDN hết hạn.
- **`QueueController` (`main/queue_controller.py`):** Điều phối chuyển tiếp video, đánh dấu trạng thái (`pending`, `resolving`, `playing`, `played`, `error`), thử lại và hỗ trợ lặp danh sách.
- **Phân giải playlist lười (Lazy Playlist Resolution):** `url_resolver.py` sử dụng model `ResolvedCollection` và `CollectionEntry` cho playlist/album, chỉ resolve stream thật khi video chuẩn bị phát.
- **Bảo tồn danh sách phát (Queue Table Preservation):** Khi phát một video từ playlist, bảng hàng đợi được giữ nguyên 100%, không bị xóa; người dùng có thể đóng/mở bảng tùy ý và click chuyển video bất kỳ lúc nào hoặc tự chuyển tiếp khi kết thúc tự nhiên.
- **Giao diện mở rộng sang phải (Expand to Right):** Bật mở panel Queue sẽ mở rộng kích thước cửa sổ sang bên phải, bảo toàn 100% diện tích và kích thước khung phát video.
- **Menu ngữ cảnh đầy đủ:** Phát ngay, Phát tiếp theo, Xóa khỏi danh sách, Di chuyển lên/xuống, Xóa video đã xem, Thử lại mục lỗi, Mở liên kết nguồn.
- **Phím tắt:** `Ctrl + Shift + Q` (Bật/tắt Queue), `PageDown` (Video kế tiếp), `PageUp` (Video trước đó).

### 17.2 Mục lục Video (Chapters)
- **Model `Chapter` (`main/chapters.py`):** Chuẩn hóa thời gian bắt đầu và kết thúc; tự động clamp phần chồng lấn (`result[-1].end_ms = start_ms`) để tránh loại bỏ nhầm chapter do sai số float mili-giây.
- **Trích xuất mục lục:** Extractor YouTube và Generic tự động trích xuất metadata chapters từ nguồn.
- **Giao diện:** Panel Chapters hiển thị danh sách mục lục, highlight chapter đang phát theo thời gian thực của VLC, cho phép click để seek nhanh đến đầu chapter.

### 17.3 Tích hợp Windows (Windows Integration)
- **Hợp đồng dòng lệnh (`main.py`):** Tiếp nhận nhiều URL, đường dẫn file local, cùng các cờ `--add-to-queue`, `--play-now`, `--privacy`, `--no-focus`.
- **Giao thức URI `fbvw://`:** Hỗ trợ `fbvw://play?url=...` và `fbvw://queue?url=...`, giải mã URL một lần duy nhất và kiểm tra tính hợp lệ an toàn.
- **Đăng ký Registry HKCU & Xử lý An toàn:** Ghi cấu hình tại `HKCU\Software\Classes\fbvw`, hoàn toàn không yêu cầu quyền Administrator. Hàm `get_app_launch_command()` (`main/platform_utils.py`) tự động chuẩn hóa đường dẫn `pythonw.exe` / `.exe` độc lập môi trường. Bọc try-except và logging phòng thủ trong `SettingsDialog` đảm bảo không bao giờ làm gián đoạn luồng lưu cài đặt người dùng.
- **Cơ chế Named Pipe IPC Forwarding:** Tự động chuyển tiếp yêu cầu sang instance đang chạy sẵn thông qua Named Pipe `\\.\pipe\fbvw_{username}`, tránh xung đột tiến trình và không cần tạo nhiều cửa sổ khi người dùng click link ngoài trình duyệt.

### 17.4 Cấu hình Profile theo nguồn & Giám sát tình trạng mạng (Source Profiles & Health)
- **Source Profiles (`main/playback_profiles.py`):** Phân chia chế độ `Auto` (AutoTuner tự động tối ưu tham số VLC) và `Custom` (tôn trọng tuyệt đối thiết lập độ phân giải và bộ nhớ đệm của người dùng, không bao giờ tự ý thay đổi).
- **`PlaybackHealthMonitor` (`main/playback_health.py`):** Giám sát tình trạng mạng và giật lag buffering, phân cấp trạng thái (`healthy`, `degraded`, `critical`) kèm cơ chế phục hồi 2 giai đoạn (sau 10s phát mượt chuyển về `degraded`, sau 20s chuyển về `healthy`).
- **Gợi ý mạng suy giảm:** Hiển thị toast gợi ý chuyển sang profile Auto kèm nút `⚡ Đổi sang Auto` khi stream bị suy giảm trên profile Custom (có cooldown 60s/video).

### 17.5 Phiên riêng tư (Privacy Session)
- **Chính sách Runtime (`main/privacy_session.py`):** Quản lý chính sách ghi dữ liệu; khi bật, ứng dụng tuyệt đối không ghi lịch sử xem (history), vị trí phát tiếp (resume state), URL gần nhất (last URL), hay lưu hàng đợi (queue persistence) xuống ổ đĩa.
- **Bảo lưu cấu hình người dùng:** Các thay đổi chủ động trong Cài đặt (Theme, Phím tắt, Phụ đề, Âm lượng) vẫn được phép lưu khi người dùng nhấn "Lưu & Đóng".
- **Giao diện & Chẩn đoán:** Hiển thị badge `🔒 RIÊNG TƯ` nổi bật; tự động che giấu (redact) URL đầy đủ và thông tin nhạy cảm trong hệ thống Devlog.

### 17.6 Quy tắc ưu tiên vòng lặp phát
- Thứ tự ưu tiên được thực thi nghiêm ngặt:
  1. **Lặp đoạn A-B (A-B Repeat):** Ưu tiên cao nhất, luôn giữ việc phát tuần hoàn trong đoạn đã chọn.
  2. **Lặp video hiện tại (Video Loop):** Giữ việc phát lại video đang mở.
  3. **Lặp danh sách phát (Queue Loop):** Chỉ kích hoạt khi video cuối cùng trong hàng đợi kết thúc tự nhiên và không có chế độ lặp cục bộ nào đang bật.

### 17.7 Tối ưu hóa GPU kép Hybrid & Offload sang iGPU (Gaming Mode)
- **Kiến trúc Multi-GPU Topology (`main/system_info.py`):**
  - Model `GPUInfo` đại diện cho từng adapter đồ họa với đầy đủ thông tin: tên, dung lượng VRAM, vendor (`nvidia`, `amd`, `intel`, `unknown`), cờ `is_integrated`, `is_active` và `adapter_index`.
  - Phân loại Topology tự động: `hybrid_dual_gpu` (máy có cả GPU rời và GPU tích hợp khả dụng), `single_discrete` (chỉ có GPU rời), `single_integrated` (chỉ có GPU on-board), hoặc `software_only` (không có card tương thích hoặc máy ảo).
- **Nhận diện khả năng iGPU của CPU (`_detect_cpu_igpu_capability`):**
  - Tự động phân tích tên CPU để loại bỏ các vi xử lý dòng F/KF (như Intel Core i5-13400F, i7-14700KF hay AMD Ryzen 7500F) hoàn toàn không có nhân GPU tích hợp vật lý trên chip.
- **Truy vấn Active DXGI Adapter qua Win32 API (`_query_active_dxgi_adapters`):**
  - Gọi trực tiếp `dxgi.dll!CreateDXGIFactory1` và lặp qua `EnumAdapters1` bằng `ctypes` với thời gian thực thi cực nhanh (<5ms).
  - Bắt và nhận diện chính xác các trường hợp iGPU bị mainboard/BIOS tự động vô hiệu hóa (`ConfigManagerErrorCode: 22` / `CM_PROB_DISABLED`) khi người dùng cắm card rời trên main MSI B660/ASUS/Gigabyte. Khi đó, hệ thống gán trạng thái `is_active = False` và điều hướng về `single_discrete` an toàn, chống crash triệt để do gọi nhầm adapter không hoạt động.
- **Chiến lược điều hướng GPU (`main/auto_tune.py` & `main/platform_utils.py`):**
  - Tùy chọn `gpu_preference`: `auto`, `discrete` (GPU rời), `integrated` (GPU tích hợp), `software` (chỉ CPU).
  - **Gaming Mode (iGPU Offload):** Khi máy ở chế độ GPU kép hoặc người dùng chọn `integrated`:
    - Ghi thiết lập vào Windows Graphics Settings: `HKCU\Software\Microsoft\DirectX\UserGpuPreferences` (`GpuPreference=1` - Power Saving) cho file thực thi của app.
    - Windows Direct3D 11 runtime tự động phân bổ luồng giải mã theo cấu hình Registry trên, đảm bảo video render trên iGPU một cách nguyên bản mà không cần truyền cờ CLI ngoài chuẩn của libVLC 3.0.
    - Giải phóng 100% dung lượng VRAM và xung nhịp của card rời (NVIDIA RTX / AMD Radeon) cho việc chơi game FPS cao hoặc render đồ họa nặng, loại bỏ hoàn toàn hiện tượng drop FPS trong game khi vừa chơi vừa xem stream.

### 17.8 Bộ tải Telegram đa kết nối MTProto siêu tốc & Lookahead Streaming
- **Bộ tải `FastTelethonDownloader` (`main/telegram_manager.py`):**
  - Sử dụng giao thức MTProto trực tiếp thay vì HTTP proxy trung gian chậm chạp.
  - Khởi tạo 6 worker connections song song (`WORKER_COUNT = 6`), chia nhỏ file video thành các part 512KB.
  - Ghi stream trực tiếp xuống ổ đĩa bằng cơ chế non-buffering (Zero in-memory buffering), tốc độ tải đạt tối đa băng thông đường truyền (~10x so với tải đơn luồng thông thường), loại bỏ hoàn toàn nguy cơ phình RAM khi tải video dung lượng lớn (1GB–4GB).
- **Cơ chế Lookahead Streaming Prefetching (`main/extractors/telegram.py`):**
  - Phân luồng đọc trước (Lookahead) với 3 worker senders độc lập nạp sẵn dữ liệu vào buffer HTTP streaming.
  - Tự động áp dụng VLC Network Cache 6000ms riêng cho luồng Telegram để bù đắp độ trễ địa lý khi kết nối tới các Telegram Data Center đặt tại nước ngoài (Singapore, Amsterdam, Miami).
- **Hủy tải tương tác 1-chạm (Interactive 1-Click Cancellation):**
  - Nút **⬇ Tải về** trên giao diện chính đổi nhãn và trạng thái thành **❌ Hủy (xx%)** theo thời gian thực.
  - Người dùng có thể nhấn hủy bất cứ lúc nào: tiến trình ngầm dừng tức thì, các worker đóng kết nối an toàn và tự động dọn sạch các file tạm `.part` / `.ytdl` trong thư mục tải về.

### 17.9 Bộ bóc tách thông minh từ văn bản (SmartTextParser) & Quản lý danh sách phát
- **Bộ phân tích `SmartTextParser` (`main/text_parser.py`):**
  - Tiếp nhận đoạn văn bản dài tùy ý (bài đăng Facebook, status, bài viết tổng hợp phim bộ).
  - Bóc tách toàn bộ link video hợp lệ (`facebook.com`, `fb.watch`, `youtube.com`, `youtu.be`, `tiktok.com`, `douyin.com`, `t.me/c/...`, direct media link).
  - Tự động bóc tách và giải mã link bọc chuyển hướng Facebook Shim (`l.facebook.com/l.php?u=...`).
  - Gọt sạch các tham số theo dõi rác (`fbclid`, `__tn__`, `si`, `utm_*`, `mibextid`).
  - Tự động trích xuất ngữ cảnh/tiền tố đứng trước mỗi link (ví dụ: `Tập 1`, `Phần 2`, `Part A`, `Preview...`) để làm tiêu đề và mô tả trực quan.
- **Hộp thoại nhập hàng loạt (`main/bulk_import_dialog.py`):**
  - Hiển thị bảng xem trước (Preview Table) cho phép chọn lọc (Check/Uncheck), chỉnh sửa tiêu đề và thứ tự trước khi đưa vào hàng đợi phát chính.
- **Lưu trữ & Xuất danh sách phát linh hoạt:**
  - Tự động lưu và đồng bộ danh sách bài trong hàng đợi vào `~/.fb-video-watcher/queue.json` (tự ngắt khi phiên riêng tư Privacy Session kích hoạt).
  - Menu ngữ cảnh trên bảng hàng đợi cung cấp tùy chọn xuất danh sách ra file `.txt` (danh sách URL kèm nhãn), file `.json` (dữ liệu cấu trúc), và file `.m3u` (playlist tiêu chuẩn cho các trình phát đa phương tiện).
  - Tooltip ngữ cảnh nổi (Hover Tooltip): Rê chuột qua từng mục trong hàng đợi hiển thị chi tiết tên tập phim và URL gốc đầy đủ.

### 17.10 Tiện ích mở rộng FFmpeg Portable Add-on & Progressive Fallback
- **Cơ chế Fallback Progressive MP4 (`main/ffmpeg_utils.py` & `main/downloader.py`):**
  - Khi hệ thống máy người dùng chưa cài đặt FFmpeg, bộ tải không báo lỗi hay crash mà tự động fallback sang định dạng Progressive MP4 (`best[ext=mp4]/best`) chứa sẵn cả hình ảnh và âm thanh nguyên bản.
- **Tải và cài đặt tự động FFmpeg Portable Add-on (`main/ffmpeg_installer.py` & `main/ffmpeg_setup_dialog.py`):**
  - Tích hợp nút cài đặt trong **⚙ Cài đặt $\rightarrow$ Cài đặt chung**.
  - Tự động tải bản FFmpeg essentials portable đóng gói sẵn từ máy chủ an toàn, giải nén ngầm vào thư mục `bin/ffmpeg` của ứng dụng kèm hộp thoại tiến trình trực quan (%) mà người dùng không cần thao tác dòng lệnh.

### 17.11 Phân hệ Proxy & DNS Mã Hóa Cô Lập Tầng Ứng Dụng (`main/network/`)
- **Mục tiêu & Nguyên tắc độc lập hệ thống:**
  - Vượt chặn ISP (DNS Poisoning, SNI throttling, kiểm duyệt video) hoàn toàn cô lập trong phạm vi tiến trình phần mềm.
  - Tuyệt đối **KHÔNG thay đổi Card mạng (Network Adapter), Windows Registry mạng, hay yêu cầu quyền Administrator**.
  - **Mặc định TẮT / Kết nối trực tiếp:** `proxy_mode = "direct"`, `doh_enabled = False`. Quyết định của người dùng luôn được ưu tiên cao nhất, ứng dụng không bao giờ tự ý bật hay ép buộc cấu hình mạng.
  - **Tiết kiệm tài nguyên tuyệt đối (Zero Leaks):** Không nhúng Chromium/CEF/WebView2. Bộ nhớ đệm DoH LRU được giới hạn cứng tối đa 256 bản ghi với TTL 300s, chiếm $< 50\text{KB}$ RAM.
- **Cấu hình Proxy đa giao thức (`main/network/proxy_config.py`):**
  - Hỗ trợ các giao thức: HTTP, HTTPS, SOCKS5, và SOCKS5h (DNS phân giải từ xa).
  - Tự động mã hóa che giấu mật khẩu (`user:****@host:port`) khi ghi log hay hiển thị trên giao diện, ngăn ngừa lộ lọt thông tin xác thực.
  - Chuyển đổi định dạng chuẩn cho libVLC CLI (`--http-proxy`, `--socks`, `--socks-user`, `--socks-pwd`), yt-dlp (`ydl_opts['proxy']`), và Telethon MTProto client (`python-socks`).
  - Nút kiểm tra kết nối Proxy không chặn giao diện (Non-blocking probe) đo độ trễ Ping (ms) và phát hiện IP thoát (Egress IP).
- **Bộ phân giải DNS-over-HTTPS DoH (`main/network/doh_resolver.py`):**
  - Hỗ trợ chuẩn RFC 8484 và JSON DNS API qua kết nối HTTPS bảo mật.
  - Tích hợp sẵn Anycast Bootstrap IPs (`1.1.1.1`, `8.8.8.8`, `9.9.9.9`, `94.140.14.14`) nhằm giải quyết triệt để bài toán con gà - quả trứng (Chicken-and-egg problem: cần DNS để phân giải domain server DNS).
  - Hỗ trợ các nhà cung cấp phổ biến: Cloudflare, Google Public DNS, Quad9, AdGuard DNS và Tùy chỉnh DoH URL.
- **Bộ hook Socket DNS Interceptor (`main/network/dns_interceptor.py`):**
  - Hook cục bộ hàm `socket.getaddrinfo` chỉ trong phạm vi tiến trình Python của ứng dụng.
  - Tự động bỏ qua loopback (`localhost`, `127.0.0.1`, `::1`) và các địa chỉ IP số để bảo đảm `StreamProxyServer` cục bộ và IPC hoạt động trơn tru.
  - Cơ chế Fail-safe: Tự động fallback DNS hệ thống nếu DoH gặp timeout hoặc sự cố mạng.
- **Quản lý mạng tập trung (`main/network/manager.py`):**
  - Pattern Singleton `NetworkManager` điều phối toàn bộ cấu hình mạng, tự động nạp/ngắt interceptor và truyền proxy vào các module `downloader`, `extractors`, `auto_tune`, `telegram_manager`.
- **Giao diện Cài đặt (Tab "Mạng & Proxy" trong `SettingsDialog`):**
  - Bố cục 2 cột trực quan, điều khiển linh hoạt giữa Direct / System / Custom Proxy và DoH, tích hợp các nút kiểm tra kết nối và phân giải tên miền thời gian thực.

### 17.12 Khắc phục triệt để hiển thị OSD Timeline đỏ trong chế độ PiP (`main/gui/components.py` & `main/gui/main_window.py`)
- **Vấn đề đã khắc phục:**
  - Ở lần đầu tiên kích hoạt chế độ Picture-in-Picture (PiP), thanh OSD tiến trình đỏ (3px) ở cạnh dưới bị ẩn do xung đột Z-Order Win32 (cửa sổ chính `root` nhận `focus_force()` đè lên overlay) và độ trễ tính toán tọa độ bất đồng bộ của Tkinter (`geometry` chưa kịp đồng bộ với Win32 message pump).
- **Kiến trúc giải pháp vững chắc:**
  - **Win32 Owner-Child Layering (`GWL_HWNDPARENT`):** Gán tường minh `root_hwnd` làm chủ sở hữu (Owner) của `top_hwnd`. Theo quy tắc quản lý cửa sổ của Windows DWM, một cửa sổ được sở hữu (Owned Window) luôn luôn nằm phía trước cửa sổ sở hữu nó trong Z-Order, ngay cả khi cửa sổ sở hữu nhận focus hay phát video phần cứng Direct3D 11 compositing ở 60fps.
  - **Explicit Bounds Injection:** Truyền trực tiếp tọa độ và kích thước đã tính toán `bounds=(x, y, pip_w, pip_h)` từ `toggle_pip()` và `set_pip_aspect_ratio()` vào `show()` và `reposition()`, loại bỏ 100% độ trễ hình học bất đồng bộ ngay từ microsecond đầu tiên.
  - **Layered Click-Through:** Áp dụng `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE` để chuột xuyên thấu hoàn toàn xuống bề mặt video VLC bên dưới mà không cản trở thao tác rê chuột, kéo thả di chuyển cửa sổ hay click đôi phóng to.
  - **Clean Lifecycle & Zero RAM Bloat:** Khi thoát PiP, gọi `pip_progress_overlay.destroy()` để hủy hoàn toàn Toplevel và dọn sạch widget nội bộ, đảm bảo khi bật lại PiP sẽ luôn tạo mới HWND tương thích với HWND mới của `root` sau khi tắt `overrideredirect`. Bộ nhớ RAM duy trì ổn định ở mức ~40 MB với 0 bytes rò rỉ.

### 17.13 Lưu trữ & Khôi phục Vị trí PiP Đa màn hình (Multi-Monitor PiP Position Persistence)
- **Vấn đề đã khắc phục:**
  - Khi người dùng di chuyển hoặc thay đổi kích thước cửa sổ Picture-in-Picture (PiP) sang màn hình phụ (Monitor 2, Monitor 3...), sau đó tắt PiP và mở lại, cửa sổ PiP liên tục bị giật nhảy về góc dưới bên phải của màn hình chính (Monitor 1).
  - Nguyên nhân do `DEFAULT_SETTINGS["ui"]` và `_save_current_pip_size()` trước đó chỉ lưu `width` và `height` mà hoàn toàn thiếu tọa độ $(x, y)$, đồng thời `toggle_pip()` sử dụng `winfo_screenwidth()` / `winfo_screenheight()` (bị Tkinter giới hạn ở màn hình chính) và ép tọa độ về góc phải Monitor 1; ngoài ra `_on_video_release()` chỉ lưu khi resize mà bỏ qua khi kéo di chuyển cửa sổ.
- **Kiến trúc giải pháp vững chắc:**
  - **Lưu trữ tọa độ phân tách theo tỉ lệ (`pip_x_horizontal`, `pip_y_horizontal`, `pip_x_vertical`, `pip_y_vertical`):** Tọa độ $(x, y)$ và kích thước $(w, h)$ được lưu độc lập cho tỉ lệ ngang (16:9) và dọc (9:16) trong `settings.json`, duy trì tương thích ngược 100%.
  - **Nhận diện Vùng làm việc Màn hình Win32 (`main/platform_utils.py`):**
    - `is_rect_visible_on_any_monitor(x, y, w, h) -> bool`: Gọi Win32 `MonitorFromRect(..., MONITOR_DEFAULTTONULL)`. Nếu cửa sổ nằm ngoài toàn bộ màn hình hiện hữu (ví dụ khi rút dây màn hình phụ), hệ thống tự động fallback an toàn về màn hình hiện tại thay vì bị treo ngoài không gian vô hình.
    - `get_monitor_work_area_for_rect(x, y, w, h) -> (left, top, right, bottom)`: Xác định chính xác vùng làm việc (`rcWork`, đã trừ taskbar) của màn hình chứa phần lớn diện tích cửa sổ PiP.
    - `get_monitor_work_area_for_window(window) -> (left, top, right, bottom)`: Lấy vùng làm việc của màn hình đang chứa cửa sổ thông qua `MonitorFromWindow`.
  - **Giữ vị trí khi Kéo thả & Thay đổi kích thước (`main/gui/main_window.py`):**
    - `_on_video_release()` tự động ghi nhớ và lưu cấu hình hình học `(w, h, pos_x, pos_y)` khi thả chuột dù là sau khi resize hay kéo di chuyển cửa sổ.
    - `toggle_pip()` kiểm tra tọa độ đã lưu: nếu còn hiển thị hợp lệ trên bất kỳ màn hình nào thì phục hồi nguyên vẹn $(x, y, w, h)$ tại đúng màn hình đó; nếu chưa lưu hoặc màn hình đã bị ngắt kết nối thì mới dock thông minh vào góc dưới bên phải của màn hình đang kích hoạt (`work_right - pip_w - 40, work_bottom - pip_h - 70`).
    - `_on_video_motion()` căn chỉnh hít mép (snapping) và `set_pip_size()` / `set_pip_aspect_ratio()` kẹp biên (clamping) theo `work_left, work_top, work_right, work_bottom` của màn hình đang chứa PiP thay vì màn hình chính, chống giật ngược về Monitor 1.



