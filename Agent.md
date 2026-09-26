# Agent.md — Hướng dẫn cho AI Model triển khai code

> **File này dành cho các AI model đọc trước khi viết code.** Nó bổ sung cho `specs.md` bằng các nguyên tắc kiến trúc, abstraction, và yêu cầu tương thích đa máy.

---

## 1. Nguyên tắc cốt lõi

### 1.1 KHÔNG BAO GIỜ hardcode cấu hình phần cứng

```python
# ❌ TUYỆT ĐỐI KHÔNG LÀM THẾ NÀY
VLC_ARGS = ['--avcodec-hw=dxva2', '--avcodec-threads=4']  # Fix cứng cho i5-13500

# ✅ PHẢI LÀM THẾ NÀY — auto-detect rồi quyết định
hw_info = SystemInfo.detect()
vlc_args = VLCArgsBuilder(hw_info, user_settings).build()
```

App phải chạy được trên **bất kỳ máy nào** — từ laptop i3 cũ đến desktop i9. Mọi giá trị liên quan phần cứng phải được **detect tự động** hoặc **user tự chỉnh trong Settings**.

### 1.2 Module hóa & Trừu tượng hóa

Mỗi module phải:
- **Độc lập** — có thể test riêng, không phụ thuộc vòng tròn.
- **Interface rõ ràng** — giao tiếp qua function/method signatures, không truy cập trực tiếp internal state.
- **Thay thế được** — nếu sau này đổi VLC sang mpv, chỉ cần sửa 1 module.

### 1.3 TUYỆT ĐỐI KHÔNG tự động đóng gói hay build file .exe
- **KHÔNG BAO GIỜ** tự ý chạy `PyInstaller`, `build.bat` hoặc build file `.exe` nếu người dùng không yêu cầu trực tiếp.
- Chỉ sửa mã nguồn, bổ sung tính năng/sửa lỗi và kiểm thử bằng `unittest` trong môi trường code.
- Việc đóng gói chỉ thực hiện khi người dùng đưa ra chỉ thị rõ ràng.

### 1.4 Nguyên tắc Tự động Cập nhật (Auto-Updater) & File Lock Windows
- **Single Source of Truth cho phiên bản:** Phiên bản ứng dụng được khai báo duy nhất tại `main/__init__.__version__`. Mọi nơi khác (`constants.py`, `gui.py`, `fb_video_watcher.spec`) đều phải tham chiếu từ đây.
- **Bypass File Lock trên Windows:** Hệ điều hành cấm ghi đè trực tiếp lên file `.exe` đang chạy, nhưng cho phép **Rename**. Luôn áp dụng cơ chế **Rename-then-Copy** (Đổi tên file cũ thành `.old`, copy file mới đè vào vị trí cũ, sau khi app mới khởi chạy thì xóa file `.old`).
- **Cờ tiến trình chạy ngầm:** Khi tạo subprocess PowerShell chạy độc lập, **TUYỆT ĐỐI KHÔNG DÙNG `DETACHED_PROCESS` (0x00000008)** vì sẽ làm Windows PowerShell 5.1 bị sập ngay khi khởi tạo do mất console host. Thay vào đó, dùng `CREATE_NO_WINDOW (0x08000000) | CREATE_NEW_PROCESS_GROUP (0x00000200)`.
- **Cô lập môi trường PyInstaller (`_MEIPASS2`):** PyInstaller một file (`--onefile`) tự gán biến môi trường `_MEIPASS2`. Khi khởi chạy bản mới từ updater, BẮT BUỘC phải tẩy sạch `_MEIPASS2` và gán `PYINSTALLER_RESET_ENVIRONMENT = "1"` để bản mới tự giải nén thư mục `_MEI...` mới, tránh lỗi `Failed to load Python DLL (python310.dll)`.

### 1.5 Nguyên tắc Toàn màn hình Đa màn hình (Multi-Monitor Fullscreen)
- Trên Windows, Tkinter's `root.attributes("-fullscreen", True)` bị hardcode tọa độ `(0, 0)` của màn hình chính.
- BẮT BUỘC sử dụng `get_monitor_bounds_for_window` (dùng `MonitorFromWindow` và `GetMonitorInfoW`) để lấy tọa độ thực tế của màn hình chứa cửa sổ và gán `root.geometry(f"{mw}x{mh}+{mx}+{my}")` ngay sau khi kích hoạt `-fullscreen`. Khi thoát, khôi phục lại đúng tọa độ `_fs_prev_geometry`.

---

## 2. Module `system_info.py` — Auto-detect phần cứng

### 2.1 Mục đích
- Detect cấu hình máy tự động khi app khởi động.
- Hiển thị thông tin phần cứng trong Settings Panel (tab "Thông tin hệ thống").
- Cung cấp dữ liệu cho các module khác để tự tối ưu (VLC args, thread pool size, buffer...).

### 2.2 Class `SystemInfo`

```python
import platform
import os
import subprocess
import psutil  # cần thêm vào requirements.txt

@dataclass
class GPUInfo:
    """Đại diện cho một card đồ họa (vật lý hoặc tích hợp) kèm trạng thái hoạt động."""
    name: str
    vram_mb: Optional[int] = None
    vendor: str = "unknown"  # "nvidia" | "amd" | "intel" | "unknown"
    is_integrated: bool = False
    is_active: bool = True
    adapter_index: Optional[int] = None

@dataclass
class SystemInfo:
    # --- CPU ---
    cpu_name: str              # "Intel(R) Core(TM) i5-13500"
    cpu_cores_physical: int    # 14
    cpu_cores_logical: int     # 20
    cpu_freq_mhz: float        # 4800.0

    # --- RAM ---
    ram_total_gb: float        # 32.0
    ram_available_gb: float    # 18.5 (tại thời điểm detect)

    # --- GPU & Multi-GPU Topology ---
    gpu_name: str              # "NVIDIA GeForce RTX 4060" hoặc "Intel UHD 770"
    gpu_vram_mb: int | None    # 8192, None nếu iGPU
    gpu_vendor: str            # "nvidia" | "amd" | "intel" | "unknown"
    gpu_topology: str          # "hybrid_dual_gpu" | "single_discrete" | "single_integrated" | "unknown"
    discrete_gpu_name: str | None
    integrated_gpu_name: str | None
    igpu_adapter_index: int | None
    cpu_has_igpu: bool         # False nếu CPU đuôi F/KF (i5-13400F, i7-14700KF, Ryzen 7500F)
    gpus: list[GPUInfo]        # Danh sách chi tiết các GPU được phát hiện

    # --- CPU Architecture & Topology ---
    is_hybrid_cpu: bool        # True nếu Intel P/E cores (12th+) hoặc AMD Zen/Zen-c
    cpu_p_cores: int           # Số lượng P-cores
    cpu_e_cores: int           # Số lượng E-cores
    p_core_logical_indices: list[int]
    e_core_logical_indices: list[int]

    # --- OS ---
    os_name: str               # "Windows"
    os_version: str            # "10.0.22631"
    os_arch: str               # "64bit"

    # --- Python & VLC ---
    python_version: str        # "3.12.4"
    python_arch: str           # "64bit"
    vlc_version: str | None    # "3.0.20" hoặc None nếu chưa cài
    vlc_arch: str | None       # "64bit" hoặc None

    @classmethod
    def detect(cls) -> 'SystemInfo':
        """Auto-detect tất cả thông tin hệ thống. Không raise exception — trả 'unknown' nếu detect thất bại."""
        ...

    def to_display_dict(self) -> dict[str, str]:
        """Trả dict dạng đẹp để hiển thị trên GUI.
        Ví dụ: {'CPU': 'Intel i5-13500 (14C/20T)', 'RAM': '32 GB (18.5 GB khả dụng)', ...}
        """
        ...
```

### 2.3 Cách detect từng thành phần

| Thành phần | Windows | Fallback |
|---|---|---|
| **CPU name** | `platform.processor()` hoặc registry `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0` | `"Unknown CPU"` |
| **CPU cores** | `os.cpu_count()` (logical), `psutil.cpu_count(logical=False)` (physical) | logical = `os.cpu_count()`, physical = logical // 2 |
| **CPU iGPU Capability** | Phân tích tên CPU (`_detect_cpu_igpu_capability()`): phát hiện và lọc chính xác các model F/KF (i5-13400F, i7-14700KF, Ryzen 7500F...) không có nhân đồ họa tích hợp | `True` |
| **RAM** | `psutil.virtual_memory()` | `0` (hiện "Không xác định") |
| **GPU (WMI)** | WMI query: `wmic path win32_VideoController get Name,AdapterRAM` | Parse output `systeminfo` |
| **Active DXGI Query** | Gọi `dxgi.dll!CreateDXGIFactory1` + `EnumAdapters1` (<5ms): xác thực adapter nào đang thực sự active trong OS; nhận diện iGPU bị BIOS tắt (`CM_PROB_DISABLED` - Code 22) để fallback an toàn | Dựa vào WMI list |
| **GPU vendor** | Detect từ `gpu_name`: chứa "NVIDIA" → `nvidia`, "AMD"/"Radeon" → `amd`, "Intel" → `intel` | `"unknown"` |
| **VLC version** | `import vlc; vlc.libvlc_get_version()` | `None` |
| **VLC arch** | Check `libvlc.dll` path: `Program Files` = 64-bit, `Program Files (x86)` = 32-bit | Check `ctypes.sizeof(ctypes.c_void_p)` |

### 2.4 Dùng `psutil` và các thư viện bổ trợ — thêm vào `requirements.txt`

```
yt-dlp>=2024.01.01
yt-dlp-ejs>=0.8.0
python-vlc>=3.0.20
psutil>=5.9.0
pywin32>=306; sys_platform == 'win32'
sv-ttk>=2.6.0
pyinstaller>=6.0.0
Pillow>=10.0.0
tkinterdnd2>=0.3.0
curl-cffi>=0.7.0
telethon>=1.36.0
qrcode>=7.4.0
cryptg>=0.4.0; sys_platform == 'win32'
```

> `psutil` để lấy thông tin hệ thống, `pywin32` chống giật giao diện, `sv-ttk` mang lại Fluent Design Windows 11 cho Tkinter mà không tốn thêm RAM, `Pillow` và `tkinterdnd2` hỗ trợ xử lý ảnh và kéo thả, `curl-cffi`/`yt-dlp-ejs` giải mã YouTube JavaScript challenge, và `telethon`/`qrcode`/`cryptg` quản lý nguồn Telegram.

---

## 3. Auto-tuning — Tự tối ưu theo phần cứng

### 3.1 Module `auto_tune.py`

Dựa trên `SystemInfo`, tự động chọn config tối ưu:

```python
class AutoTuner:
    """Tự động chọn config phù hợp dựa trên phần cứng."""

    def __init__(self, sys_info: SystemInfo, user_settings: dict):
        self.sys_info = sys_info
        self.user_settings = user_settings

    def recommend_decode_threads(self) -> int:
        """
        Khuyến nghị số threads decode dựa trên CPU.
        - ≤ 4 cores logical  → 1 thread
        - 4-8 cores          → 2 threads
        - 8-16 cores         → 4 threads
        - > 16 cores         → 6 threads
        """
        cores = self.sys_info.cpu_cores_logical
        if cores <= 4:
            return 1
        elif cores <= 8:
            return 2
        elif cores <= 16:
            return 4
        else:
            return 6

    def recommend_hw_accel(self) -> str | None:
        """
        Chọn hardware acceleration phù hợp GPU.
        - NVIDIA → 'dxva2' hoặc 'd3d11va'
        - AMD    → 'dxva2' hoặc 'd3d11va'
        - Intel  → 'dxva2'
        - Unknown/Fallback → None (software decode)
        """
        vendor = self.sys_info.gpu_vendor
        os_ver = self.sys_info.os_version
        if vendor in ('nvidia', 'amd', 'intel'):
            # Windows 10+ hỗ trợ d3d11va tốt hơn dxva2
            if os_ver and int(os_ver.split('.')[0]) >= 10:
                return 'd3d11va'
            return 'dxva2'
        return None  # Software decode

    def recommend_network_buffer(self) -> int:
        """
        Buffer dựa trên RAM khả dụng và tổng RAM.
        - < 4 GB available và total < 8 GB  → 1500 ms (tiết kiệm)
        - 4-8 GB                            → 3000 ms (tiêu chuẩn)
        - > 8 GB available hoặc total ≥ 16GB → 5000 ms (thoải mái khi vừa chơi game)
        """
        ram = self.sys_info.ram_available_gb
        total = self.sys_info.ram_total_gb
        if ram > 8.0 or total >= 16.0:
            return 5000
        elif ram >= 4.0 or total >= 8.0:
            return 3000
        else:
            return 1500

    def recommend_gpu_preference(self) -> str:
        """
        Chiến lược phân bổ GPU (Gaming Mode / Multi-GPU Topology):
        - 'power_saving': Điều hướng giải mã video sang iGPU trong CPU (Intel UHD/Iris hoặc AMD Radeon),
                          giải phóng 100% card đồ họa rời (dGPU) cho tác vụ 3D / chơi game.
        - 'high_performance': Điều hướng sang GPU rời hiệu năng cao (single dGPU hoặc user chọn).
        - 'software': Tắt hardware decode, chuyển sang giải mã CPU thuần túy.
        - 'default': Để Windows/VLC tự quyết định.
        """
        user_pref = self.user_settings.get('performance', {}).get('gpu_preference', 'auto')
        if user_pref == 'integrated':
            return 'power_saving'
        elif user_pref == 'discrete':
            return 'high_performance'
        elif user_pref == 'software':
            return 'software'

        # Chế độ "auto": Nếu phát hiện hệ thống GPU kép (Hybrid Dual GPU) có iGPU active
        # → ưu tiên 'power_saving' (dùng iGPU gánh video để dGPU thoải mái game)
        if (
            self.sys_info.gpu_topology == 'hybrid_dual_gpu'
            and self.sys_info.cpu_has_igpu
            and self.sys_info.integrated_gpu_name
            and "Tắt" not in str(self.sys_info.integrated_gpu_name)
        ):
            return 'power_saving'
        elif self.sys_info.gpu_topology == 'single_discrete':
            return 'high_performance'
        return 'default'

    def recommend_thread_pool_size(self) -> int:
        """Workers cho ThreadPoolExecutor."""
        cores = self.sys_info.cpu_cores_logical
        if cores <= 4:
            return 1
        return 2

    def build_vlc_args(self) -> list[str]:
        """Build VLC args tự động — KHÔNG hardcode."""
        args = ['--quiet', '--no-video-title-show']

        # Platform-specific
        if self.sys_info.os_name != 'Windows':
            args.append('--no-xlib')

        # Network caching (user override hoặc auto)
        cache = self.user_settings.get('streaming', {}).get(
            'network_caching',
            self.recommend_network_buffer()
        )
        args.append(f'--network-caching={cache}')
        args.append(f'--file-caching={max(cache // 2, 1000)}')
        args.append(f'--live-caching={cache}')

        # Hardware decode (user override hoặc auto)
        hw_enabled = self.user_settings.get('streaming', {}).get('hardware_decode', True)
        if hw_enabled:
            hw_method = self.recommend_hw_accel()
            if hw_method:
                args.append(f'--avcodec-hw={hw_method}')

            # D3D11 GPU Routing: Được Windows DirectX Runtime tự động điều hướng
            # qua HKCU\Software\Microsoft\DirectX\UserGpuPreferences (GpuPreference=1/2)
            # được áp dụng tại platform_utils.apply_windows_gpu_preference().
            # (libVLC 3.0 không yêu cầu và không hỗ trợ cờ adapter CLI riêng).

        # Decode threads (user override hoặc auto)
        threads = self.user_settings.get('streaming', {}).get(
            'decode_threads',
            0  # 0 = auto
        )
        if threads == 0:
            threads = self.recommend_decode_threads()
        args.append(f'--avcodec-threads={threads}')

        return args
```

### 3.2 Quy tắc ưu tiên config

```
User Settings (settings.json)  >  Auto-detect (SystemInfo)  >  Default fallback
         ưu tiên 1                      ưu tiên 2                  ưu tiên 3
```

Nếu user đã chỉnh setting → **luôn dùng giá trị của user**.
Nếu user chưa chỉnh (hoặc chọn "Auto") → dùng giá trị auto-detect.
Nếu auto-detect thất bại → dùng default an toàn.

---

## 4. Hiển thị cấu hình máy trên GUI

### 4.1 Trong Settings Panel — Tab "Thông tin hệ thống"

Thêm 1 section/tab trong cửa sổ Settings:

```
╔═══════════════ Thông tin hệ thống ════════════════╗
║                                                    ║
║  CPU:     Intel Core i5-13500 (14C/20T @ 4.8GHz)  ║
║  RAM:     32 GB (18.5 GB khả dụng)                ║
║  GPU:     NVIDIA GeForce RTX 4060                  ║
║  Topology: Đồ họa kép (Intel UHD 770 + RTX 4060)   ║
║  OS:      Windows 11 (64-bit) Build 22631          ║
║                                                    ║
║  ── Phần mềm ──────────────────────────────────── ║
║  Python:  3.12.4 (64-bit)                          ║
║  VLC:     3.0.20 (64-bit) ✅ Tương thích           ║
║  yt-dlp:  2024.12.01                               ║
║  FFmpeg:  7.1 ✅ Đã cài                            ║
║                                                    ║
║  ── Auto-tune đề xuất ─────────────────────────── ║
║  HW Decode:       d3d11va                          ║
║  GPU Preference:  power_saving (Offload sang iGPU) ║
║  Decode threads:  4 (dựa trên 20 logical cores)    ║
║  Network buffer:  5000ms (RAM > 8GB)               ║
║  Thread pool:     2 workers                         ║
║                                                    ║
║  [📋 Copy thông tin]   [🔄 Detect lại]             ║
╚════════════════════════════════════════════════════╝
```

- **Nút "Copy thông tin"** — copy toàn bộ system info ra clipboard (hữu ích khi báo bug trên GitHub).
- **Nút "Detect lại"** — chạy lại `SystemInfo.detect()` (ví dụ khi user vừa cài VLC).

### 4.2 Format khi copy:

```
FB Video Watcher v1.0.4-beta
=======================
CPU: Intel Core i5-13500 (14C/20T)
RAM: 32 GB (18.5 GB available)
GPU: NVIDIA GeForce RTX 4060
Topology: hybrid_dual_gpu (Integrated: Intel UHD 770, Discrete: RTX 4060)
OS:  Windows 11 64-bit (Build 22631)
Python: 3.12.4 (64-bit)
VLC: 3.0.20 (64-bit)
yt-dlp: 2024.12.01
FFmpeg: 7.1
```

---

## 5. Nguyên tắc Module hóa & Abstraction

### 5.1 Dependency Graph (không vòng tròn)

```
main.py
  └── app.py
        ├── gui.py              ← Chỉ biết interface, không biết implementation
        │     └── settings_gui  ← Phần GUI của Settings (trong gui.py hoặc tách riêng)
        ├── vlc_player.py       ← Chỉ nhận stream_url + VLC args, không biết Facebook
        ├── url_resolver.py     ← Chỉ biết yt-dlp, không biết GUI
        ├── history.py          ← Chỉ biết SQLite, không biết GUI
        ├── settings.py         ← Chỉ biết JSON file, không biết GUI
        ├── system_info.py      ← Chỉ detect phần cứng, không biết gì khác
        ├── auto_tune.py        ← Nhận SystemInfo + Settings → trả config
        ├── timestamp.py        ← Pure function, zero dependency
        └── constants.py        ← Chỉ chứa default values
```

### 5.2 Quy tắc abstraction

#### A. Mỗi module có trách nhiệm DUY NHẤT

```python
# ❌ SAI — url_resolver.py không nên biết về GUI
def resolve_and_show_error(url, gui):
    try:
        result = resolve(url)
    except Exception:
        gui.show_error("Lỗi!")  # Module resolver đang gọi GUI!

# ✅ ĐÚNG — resolver chỉ resolve, raise exception nếu lỗi
# app.py sẽ bắt exception và gọi GUI
def resolve(url: str) -> ResolvedVideo:
    ...  # Raise URLValidationError, VideoNotFoundError, etc.
```

#### B. Giao tiếp qua interface, không qua internal state

```python
# ❌ SAI — gui.py truy cập trực tiếp VLC internal
class GUI:
    def update_time(self):
        time = self.vlc.player._media_player.get_time()  # Truy cập internal!

# ✅ ĐÚNG — qua public method
class GUI:
    def update_time(self):
        time = self.vlc_player.get_position()  # Public API
```

#### C. Config không nằm rải rác — tập trung 1 chỗ

```python
# ❌ SAI — magic number rải rác trong code
def resolve(url):
    ydl_opts = {'socket_timeout': 15, 'retries': 3}  # Magic numbers!

# ✅ ĐÚNG — lấy từ constants hoặc settings
from constants import RESOLVE_TIMEOUT, RESOLVE_RETRIES

def resolve(url, timeout=RESOLVE_TIMEOUT, retries=RESOLVE_RETRIES):
    ydl_opts = {'socket_timeout': timeout, 'retries': retries}
```

#### D. Platform-specific code phải được isolate

```python
# ❌ SAI — platform check rải rác
class VLCPlayer:
    def embed(self, frame):
        if sys.platform == 'win32':
            self.player.set_hwnd(frame.winfo_id())

# ✅ ĐÚNG — tách ra utility function
# platform_utils.py
```

#### E. Trừu tượng hóa màu sắc (Theme) thay vì fix cứng

```python
# ❌ SAI — Hardcode màu sắc trực tiếp vào widget
label = tk.Label(root, text="Title", bg="#000000", fg="#ffffff")

# ✅ ĐÚNG — Dùng ttk.Label và ThemeManager (theme.py) tích hợp sv-ttk
# ThemeManager sẽ tự động nạp theme Windows 11 Fluent và đồng bộ Dark Title Bar
label = ttk.Label(root, text="Title")
```

### 5.3 Tóm tắt quy tắc

| Quy tắc | Mô tả |
|---|---|
| **Single Responsibility** | Mỗi module/class chỉ làm 1 việc |
| **No Circular Imports** | A import B thì B không được import A |
| **Config tập trung** | Mọi giá trị cấu hình nằm trong `constants.py` hoặc `settings.json` |
| **No Magic Numbers** | Không có số/chuỗi "ma thuật" rải rác trong code |
| **Platform Isolation** | Code phụ thuộc OS phải nằm riêng 1 chỗ, có fallback |
| **Dependency Injection** | Module nhận dependency qua constructor/parameter, không tự tạo |
| **Fail Gracefully** | Auto-detect thất bại → dùng default an toàn, không crash |
| **User Override** | User settings luôn được ưu tiên hơn auto-detect |
| **Theme Abstraction** | GUI dùng `ttk` widgets kết hợp `sv-ttk`, không gán màu cứng (`bg=`, `fg=`); custom UI (ThemedMenuBar, menus) đăng ký ThemeManager listener |

---

## 6. Cấu trúc thư mục đầy đủ (đồng bộ theo main/__init__.__version__)

```
FB-Video-watching/
├── .fbwenv/                 # Môi trường ảo Python (KHÔNG commit)
├── .gitignore
├── README.md                # Hướng dẫn sử dụng (tiếng Việt)
├── specs.md                 # Đặc tả kỹ thuật chi tiết
├── Agent.md                 # Hướng dẫn cho AI model & quy tắc dự án
├── requirements.txt         # Thư viện phụ thuộc Python
├── build.bat                # Script build PyInstaller (CHỈ chạy khi user yêu cầu)
├── run.bat                  # Script chạy nhanh ứng dụng
├── main.py                  # Entry point (import từ main/)
├── main/                    # Source code chính
│   ├── __init__.py          # Single Source of Truth cho version (__version__)
│   ├── gui/                 # Phân hệ Giao diện người dùng (Modular GUI Package)
│   │   ├── __init__.py      # Re-export MainWindow, SettingsDialog, ThemedMenuBar, components
│   │   ├── components.py    # SeekBarController, OSDOverlay, PiPProgressOverlay, ListboxTooltip
│   │   ├── menu_bar.py      # ThemedMenuBar (Menu bar hòa sắc chuẩn theme, khử vệt trắng Win32)
│   │   ├── settings_dialog.py # SettingsDialog (Đa thẻ Fluent: Chung, Phím tắt, Phụ đề, Telegram, Mạng, System, About)
│   │   └── main_window.py   # MainWindow (Player surface, video controls, playlist, layout orchestration)
│   ├── text_parser.py        # SmartTextParser bóc tách link, giải mã shim, gọt tracking
│   ├── updater.py           # In-App Auto-Updater (Rename-then-Copy, _MEIPASS2 isolation)
│   ├── downloader.py        # Tải video/MP3 đa luồng yt-dlp & progressive fallback
│   ├── ffmpeg_utils.py       # Quản lý phát hiện FFmpeg, fallback progressive stream
│   ├── ffmpeg_installer.py   # Tự động tải & cài đặt FFmpeg Portable Add-on ngầm
│   ├── ffmpeg_setup_dialog.py # Hộp thoại tiến trình tải tiện ích mở rộng FFmpeg
│   ├── hotkeys.py           # Quản lý & tùy biến phím tắt
│   ├── subtitle.py          # Xử lý định dạng & kiểm tra tính hợp lệ phụ đề
│   ├── devlog.py            # Bảng Devlog chẩn đoán (Dock / Undock / Lọc log)
│   ├── history.py           # Quản lý lịch sử SQLite WAL
│   ├── history_dialog.py    # Hộp thoại hiển thị & tìm kiếm lịch sử xem
│   ├── settings.py          # Settings manager (JSON)
│   ├── theme.py             # Quản lý giao diện Fluent (sv-ttk, dark title bar)
│   ├── vlc_player.py        # VLC playback controller & nhúng native hwnd
│   ├── vlc_installer.py     # Tự động tải & cài đặt ngầm VLC 64-bit
│   ├── vlc_setup_dialog.py  # Hộp thoại tiến trình cài đặt VLC
│   ├── url_resolver.py      # Phân giải đa nền tảng (FB, YT, TikTok, Direct)
│   ├── collection.py        # Model ResolvedCollection & CollectionEntry cho playlist/album
│   ├── stream_proxy.py      # Local HTTP proxy, daemon handlers & async shutdown
│   ├── system_info.py       # Auto-detect phần cứng (CPU, GPU, RAM, OS)
│   ├── auto_tune.py         # Tự tối ưu config VLC theo phần cứng
│   ├── playback_queue.py    # QueueItem, PlaybackQueue model hàng đợi phát
│   ├── queue_controller.py  # Điều phối chuyển bài, bỏ qua lỗi & lặp queue
│   ├── queue_persistence.py # Lưu/nạp hàng đợi ra file queue.json
│   ├── chapters.py          # Chuẩn hóa và quản lý mục lục video
│   ├── windows_integration.py # Tích hợp Windows (CLI, protocol, IPC)
│   ├── telegram_manager.py   # Quản lý tài khoản Telegram & phiên Telethon
│   ├── playback_health.py   # Theo dõi tình trạng giật lag & buffering
│   ├── playback_profiles.py # Cấu hình profile theo domain nguồn (Auto/Custom)
│   ├── privacy_session.py   # Quản lý chính sách phiên riêng tư Runtime
│   ├── platform_utils.py    # Tiện ích Win32 (Monitor bounds, Dark Title Bar, Toast)
│   ├── timestamp.py         # Parse chuỗi thời gian (1:45, 1h30m, 90s)
│   ├── constants.py         # Hằng số, URL patterns & cấu hình mặc định (APP_VERSION)
│   ├── network/             # Phân hệ Proxy & DoH DNS cô lập tầng ứng dụng
│   │   ├── __init__.py
│   │   ├── proxy_config.py  # Proxy dataclass, URL builder, VLC CLI args, Telethon dict, Test probe
│   │   ├── doh_resolver.py  # In-memory DoH resolver, Anycast Bootstrap IPs, LRU cache <50KB
│   │   ├── dns_interceptor.py # Process-level socket.getaddrinfo hook, loopback bypass, fail-safe
│   │   └── manager.py       # NetworkManager Singleton điều phối toàn bộ app
│   ├── bin/
│   │   └── qjs.exe          # QuickJS engine cho yt-dlp giải mã n-sig YouTube
│   ├── docs/
│   │   └── cookies_guide.html # Hướng dẫn xuất cookies cho video riêng tư
│   ├── extractors/          # Các bộ giải mã luồng chuyên biệt
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── generic.py
│   │   ├── local.py
│   │   ├── sexvietnew.py
│   │   ├── telegram.py
│   │   ├── vlxx.py
│   │   ├── xnhau.py
│   │   └── youtube.py
│   └── image/               # Assets hình ảnh & biểu tượng
│       ├── app_icon.ico
│       ├── icon-192.png
│       ├── icon-512.png
│       └── Discord-*.png / .svg # Logo & biểu tượng Discord
└── tests/                   # Toàn bộ 29 test files (296 unit tests vượt qua 100%)
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
    ├── test_network.py
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


---

## 7. Checklist trước khi commit

- [ ] Không có giá trị phần cứng hardcode (CPU name, thread count, GPU model...)
- [ ] `SystemInfo.detect()` có try/except cho MỌI thao tác detect — không bao giờ crash
- [ ] Active DXGI query kiểm tra adapter khả dụng (<5ms) bảo vệ chống thiết bị bị BIOS tắt (Code 22)
- [ ] GPU preference hỗ trợ offload sang iGPU trong cấu hình GPU kép (Gaming Mode)
- [ ] Cấu hình Proxy & DoH DNS mặc định TẮT / Direct; tuyệt đối không thay đổi Network Adapter hay Windows Registry mạng
- [ ] Hook `socket.getaddrinfo` cô lập trong process, bắt buộc bỏ qua `localhost` / `127.0.0.1` để StreamProxy và IPC hoạt động
- [ ] DoH cache có giới hạn LRU tối đa 256 bản ghi (<50KB RAM), không nhúng browser, không gây rò rỉ tài nguyên
- [ ] Mọi config lấy từ `settings.json` → fallback `auto_tune` → fallback `constants.py`
- [ ] Không có circular import
- [ ] Mọi thao tác >50ms chạy trên thread riêng
- [ ] Stream proxy dùng daemon request threads, đóng socket chủ động và không shutdown đồng bộ trên Tkinter main thread
- [ ] Khi đổi Telegram → nguồn khác, dừng VLC trước rồi gọi `StreamProxyServer.stop_async()`
- [ ] Test GUI không mở dialog/fullscreen thật lên desktop khi parent test đang withdrawn
- [ ] Platform-specific code nằm trong `platform_utils.py`
- [ ] Settings Panel hiển thị thông tin hệ thống + nút "Copy thông tin"
- [ ] App chạy được trên máy KHÔNG có GPU rời (fallback software decode)
- [ ] App chạy được trên máy RAM thấp (4GB) với buffer giảm tự động
- [ ] Tuân thủ nguyên tắc "Xài xong dọn": RAM runtime duy trì ~40MB khi phát 1080p và sau khi tua video 10 tiếng
- [ ] Cơ chế `_schedule_post_seek_cleanup()` debounce 2.5s dọn rác sau khi tua/nhảy mốc thời gian
- [ ] Win32 Working Set trimming trong `platform_utils.py` phải dùng chuẩn 64-bit (`psapi.EmptyWorkingSet` với `argtypes=[wintypes.HANDLE]` hoặc `ctypes.c_size_t(-1).value`), tuyệt đối không gọi `SetProcessWorkingSetSize` thiếu `argtypes`
- [ ] Mọi thao tác dọn dẹp nặng (GC, Working set trim) BẮT BUỘC submit vào `self.executor` ngầm, tuyệt đối không chạy trên Tkinter UI thread hay vòng lặp 250ms
- [ ] `PiPProgressOverlay` dùng Win32 Owner-Child (`GWL_HWNDPARENT`), layered transparency và explicit bounds khi toggle PiP, giải phóng sạch sẽ khi thoát PiP (`destroy()`) để tránh lỗi Z-Order và rò rỉ RAM
- [ ] PiP lưu trữ và khôi phục tọa độ (x, y, w, h) đa màn hình theo tỷ lệ, hỗ trợ Win32 work area clamping và tự động fallback an toàn khi ngắt kết nối màn hình phụ

