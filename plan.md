# Kế hoạch tối ưu hóa bộ nhớ & Cơ chế "Xài xong dọn" (Memory Cleanup & Lifecycle Plan)
**Dự án:** FB Video Watcher  
**Phiên bản mục tiêu:** v1.0.3+  
**Tác giả:** P A U L / JustFun  
**Ngày cập nhật:** 20/09/2026  
**Mục đích tài liệu:** Hướng dẫn kỹ thuật chi tiết từng file, từng hàm để model/lập trình viên tiếp theo triển khai code chính xác, an toàn 100%.

---

> [!IMPORTANT]
> **NGUYÊN TẮC BẤT KHẢ XÂM PHẠM: TUÂN THỦ 100% CÀI ĐẶT CỦA NGƯỜI DÙNG**
> * **TUYỆT ĐỐI KHÔNG can thiệp, KHÔNG tự ý thay đổi** các thông số cài đặt streaming của người dùng và Auto-Tuner (bao gồm `network_caching`, `file_caching`, `hardware_decode`, `decode_threads`).
> * Nếu người dùng hoặc Auto-Tuner chọn bộ đệm 3000ms hay 5000ms, hệ thống **bắt buộc giữ nguyên 100%** để đảm bảo chất lượng phát và tính toàn vẹn của cấu hình.
> * Toàn bộ công tác tối ưu chỉ tập trung vào việc **triệt tiêu rác bộ nhớ thực sự (Dead Memory, Stale Metadata, Leftover Files, Circular References, Uncommitted OS Pages)** sinh ra trong quá trình xử lý ngầm, hoàn toàn không "ăn bớt" bộ đệm phát video của người dùng.

---

## 1. Hiện trạng & Mục tiêu kỹ thuật

### 1.1 Hiện trạng (Baseline Measurement)
* **Tiến trình Bootloader launcher (`FB-Video-Watcher.exe`):** ~8.8 MB RAM.
* **Tiến trình chính (`FB-Video-Watcher.exe`):** **~275 – 288 MB RAM** (Working Set khi phát 1080p).
* **Phân bổ:**
  1. **VLC Network Buffer & Video Surface:** Phục vụ phát video theo đúng thiết lập người dùng (3000ms – 5000ms) $\rightarrow$ *Giữ nguyên 100%*.
  2. **yt-dlp Session & JSON Metadata cache tạm:** ~35 – 50 MB rác sau bóc tách.
  3. **Python Runtime Heap & VirtualAlloc của Windows:** ~80 – 100 MB các trang nhớ nhàn rỗi chưa được Windows thu hồi.
  4. **File rác đọng lại trên đĩa cứng:** File `.old` khi update, file `.part` khi hủy tải, file `.m3u8` tạm của YouTube.

### 1.2 Mục tiêu đề ra
* **"Xài xong là dọn":** Mọi tài nguyên tạm (biến, session, file temp, dialog instance, media cũ) phải được dọn dẹp dứt điểm ngay khi hoàn thành tác vụ.
* **Ổn định dài hạn (Zero Memory Leak):** Xem liên tục nhiều giờ hoặc đổi qua lại 20+ video không làm RAM tăng lũy kế (giữ mức tiêu thụ phẳng).
* **Không làm bẩn máy người dùng:** Không để lại file thừa trong thư mục Downloads, Desktop hay `%TEMP%`.
* **Zero Lag:** Dọn dẹp trên worker thread ngầm, không gây giật hình hay khựng thanh trượt GUI.

---

## 2. Chi tiết 7 khu vực cần triển khai "Xài xong dọn"

---

### 🧹 KHU VỰC 1: Cắt tỉa dữ liệu `info_dict` khổng lồ & Dọn rác Resolver
* **File cần sửa:** [`main/extractors/generic.py`](file:///P:/A.Code/FB-Video-watching/main/extractors/generic.py) và [`main/extractors/youtube.py`](file:///P:/A.Code/FB-Video-watching/main/extractors/youtube.py)
* **Vấn đề:** 
  `ydl.extract_info(url, download=False)` trả về `info_dict` chứa hàng trăm trường không cần thiết (hàng chục format biến thể, danh sách thumbnails đầy đủ, automatic captions, request logs, comments). Dữ liệu này ngốn từ 25MB – 45MB RAM và nằm mãi trong bộ nhớ.
* **Hướng dẫn triển khai chi tiết:**
  1. Trong hàm `extract()` của cả hai file, ngay sau khi đã xác định xong `stream_url`, `audio_url`, `title`, `duration`, `thumbnail`, `width`, `height`, `http_headers`:
     * Chỉ lưu vào `ResolvedVideo` danh sách format tinh gọn (hoặc format đã chọn), không lưu toàn bộ 50–100 formats thô.
     * Giải phóng dữ liệu thô:
       ```python
       del info_dict
       del formats_raw
       ```
  2. Trong [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py) tại worker thread phân giải (hàm `_resolve_url_worker`):
     * Ngay sau khi resolve xong và gửi kết quả về main thread, gọi:
       ```python
       import gc
       gc.collect()
       ```
     * Việc gọi `gc.collect()` trên worker thread đảm bảo dọn sạch ngay bộ nhớ tạm của `yt-dlp` mà **không hề làm khựng giao diện** chính.

---

### 🧹 KHU VỰC 2: Tự động dọn dẹp file thừa sau Auto-Update
* **File cần sửa:** [`main/updater.py`](file:///P:/A.Code/FB-Video-watching/main/updater.py) và [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py)
* **Vấn đề:** 
  Khi ứng dụng cập nhật, file `.exe` cũ được đổi tên thành `.old`. PowerShell cố gắng xóa `.old` nhưng nếu OneDrive hoặc Windows Defender đang quét ngầm, file `.old` (~100MB!) bị kẹt lại vĩnh viễn trên Desktop/thư mục của người dùng. Tương tự với các file zip tạm trong `%TEMP%`.
* **Hướng dẫn triển khai chi tiết:**
  1. Trong [`main/updater.py`](file:///P:/A.Code/FB-Video-watching/main/updater.py), viết thêm hàm:
     ```python
     def cleanup_updater_leftovers() -> None:
         """Dọn dẹp file .old và file update tạm còn sót lại từ lần cập nhật trước."""
         try:
             # 1. Tìm và xóa file .old của executable hiện tại
             exe_path = Path(sys.executable).resolve()
             old_file = exe_path.with_name(exe_path.name + ".old")
             if old_file.is_file():
                 try:
                     old_file.unlink(missing_ok=True)
                     logger.info("Đã dọn dẹp file cập nhật cũ: %s", old_file)
                 except Exception:
                     pass

             # 2. Dọn các file zip/exe update tạm trong thư mục Temp
             temp_dir = Path(tempfile.gettempdir())
             for pattern in ("fbw_update_*", "update_*.zip"):
                 for temp_f in temp_dir.glob(pattern):
                     try:
                         if temp_f.is_file():
                             temp_f.unlink(missing_ok=True)
                         elif temp_f.is_dir():
                             shutil.rmtree(temp_f, ignore_errors=True)
                     except Exception:
                         pass
         except Exception as exc:
             logger.debug("Lỗi khi dọn dẹp file update thừa: %s", exc)
     ```
  2. Trong [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py), gọi hàm `cleanup_updater_leftovers()` một lần duy nhất lúc khởi động ứng dụng (chạy trên background thread để không ảnh hưởng thời gian mở app).

---

### 🧹 KHU VỰC 3: Dọn file `.part` / `.ytdl` tải dở dang khi Hủy tải
* **File cần sửa:** [`main/downloader.py`](file:///P:/A.Code/FB-Video-watching/main/downloader.py)
* **Vấn đề:** 
  Khi người dùng bấm **Hủy tải (Cancel)** hoặc xảy ra mất mạng giữa chừng, `yt-dlp` để lại các file tải dở `.part` hoặc `.ytdl` trong thư mục Downloads của người dùng mãi mãi.
* **Hướng dẫn triển khai chi tiết:**
  1. Trong class `VideoDownloader`, khi cờ `self._cancelled = True` được kích hoạt hoặc trong khối `except Exception`:
     ```python
     def _cleanup_partial_files(self) -> None:
         """Xóa các file .part / .ytdl dở dang khi bị hủy hoặc gặp lỗi."""
         try:
             if hasattr(self, "output_dir") and self.output_dir.is_dir():
                 # Quét các file .part liên quan đến video đang tải
                 for part_file in self.output_dir.glob("*.part"):
                     # Kiểm tra nếu file được chỉnh sửa trong vòng 60 giây qua
                     if time.time() - part_file.stat().st_mtime < 60:
                         try:
                             part_file.unlink(missing_ok=True)
                             logger.info("Đã xóa file tải dở dang: %s", part_file)
                         except Exception:
                             pass
                 for ytdl_file in self.output_dir.glob("*.ytdl"):
                     if time.time() - ytdl_file.stat().st_mtime < 60:
                         try:
                             ytdl_file.unlink(missing_ok=True)
                         except Exception:
                             pass
         except Exception as exc:
             logger.debug("Lỗi dọn file part: %s", exc)
     ```
  2. Gọi `self._cleanup_partial_files()` trong khối xử lý hủy và lỗi tải của `_run_download()`.

---

### 🧹 KHU VỰC 4: Dọn sạch file manifest `.m3u8` tạm của YouTube
* **File cần sửa:** [`main/extractors/youtube.py`](file:///P:/A.Code/FB-Video-watching/main/extractors/youtube.py) và [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py)
* **Vấn đề:** 
  Hàm `_prepare_hls_master_manifest` tạo file `stream_{pid}_{timestamp}.m3u8` trong `%TEMP%/fbw_hls`. Các file này chỉ cần dùng cho video YouTube hiện tại, nhưng khi chuyển video khác thì file cũ vẫn nằm nguyên trong ổ cứng.
* **Hướng dẫn triển khai chi tiết:**
  1. Trong [`main/extractors/youtube.py`](file:///P:/A.Code/FB-Video-watching/main/extractors/youtube.py):
     * Lưu đường dẫn file manifest cuối cùng: `_last_created_manifest: Optional[Path] = None`.
     * Khi tạo manifest mới: xóa file manifest cũ trước đó nếu nó khác file mới.
  2. Viết thêm hàm dọn dẹp toàn bộ:
     ```python
     def cleanup_hls_cache() -> None:
         """Dọn dẹp thư mục manifest tạm fbw_hls."""
         try:
             cache_dir = Path(tempfile.gettempdir()) / "fbw_hls"
             if cache_dir.is_dir():
                 shutil.rmtree(cache_dir, ignore_errors=True)
         except Exception:
             pass
     ```
  3. Trong [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py) tại hàm `shutdown()` / khi đóng app: gọi `cleanup_hls_cache()`.

---

### 🧹 KHU VỰC 5: Giải phóng đối tượng `Media` và Frame Buffer của VLC
* **File cần sửa:** [`main/vlc_player.py`](file:///P:/A.Code/FB-Video-watching/main/vlc_player.py)
* **Vấn đề:** 
  Khi người dùng nhấn dừng phát (`stop()`), phương thức `stop()` chỉ gọi `self.player.stop()` nhưng giữ nguyên `self._current_media`, khiến VLC tiếp tục giữ Direct3D textures và frame buffers cũ trong RAM.
* **Hướng dẫn triển khai chi tiết:**
  1. Cập nhật phương thức `stop()` trong [`main/vlc_player.py`](file:///P:/A.Code/FB-Video-watching/main/vlc_player.py):
     ```python
     def stop(self) -> None:
         """Stop playback and cleanly release current media to free video frame buffers."""
         try:
             self.player.stop()
             self.player.set_media(None)
             if self._current_media:
                 self._current_media.release()
                 self._current_media = None
         except Exception:
             pass
     ```
  2. Đảm bảo trong `play()` khi đổi sang stream URL mới, khối giải phóng `_current_media` hiện tại tiếp tục được gọi dứt điểm như đã thiết kế.

---

### 🧹 KHU VỰC 6: Dọn dẹp vòng đời Hộp thoại Cài đặt (`SettingsDialog`) & Lịch sử
* **File cần sửa:** [`main/gui.py`](file:///P:/A.Code/FB-Video-watching/main/gui.py)
* **Vấn đề:** 
  Khi người dùng đóng `SettingsDialog` bằng nút "Hủy" hoặc dấu "X", biến `self._settings_dialog` trên `MainWindow` vẫn giữ nguyên tham chiếu đến cả cây đối tượng của hộp thoại (hàng chục `StringVar`, 5 frame tabs, widget cây con, ảnh xem trước subtitle). Python không thể thu gom vùng nhớ này.
* **Hướng dẫn triển khai chi tiết:**
  1. Trong `MainWindow.open_settings_dialog()`:
     * Bắt sự kiện `<Destroy>` của cửa sổ Toplevel để tự động giải phóng:
       ```python
       def _on_dialog_destroy(event):
           if getattr(event, "widget", None) == self._settings_dialog.top:
               self._settings_dialog = None
               # Kích hoạt thu hồi bộ nhớ ngay sau khi đóng hộp thoại lớn
               self.root.after(100, self._trim_memory_if_possible)

       self._settings_dialog.top.bind("<Destroy>", _on_dialog_destroy, add="+")
       ```
  2. Trong `SettingsDialog`:
     * Khi đóng cửa sổ, dọn dẹp các canvas image cache của Subtitle Preview.

---

### 🧹 KHU VỰC 7: Cơ chế Thu hồi vùng nhớ Windows Working Set (OS Memory Trimming)
* **File cần sửa:** [`main/platform_utils.py`](file:///P:/A.Code/FB-Video-watching/main/platform_utils.py) và [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py)
* **Vấn đề:** 
  Khi Python giải phóng rác (ví dụ xóa 40MB metadata của yt-dlp hay đóng SettingsDialog), trình quản lý bộ nhớ của Python (`pymalloc`) vẫn giữ lại vùng nhớ ảo trong tiến trình, Windows không tự động trừ con số RAM này trong Task Manager.
* **Hướng dẫn triển khai chi tiết:**
  1. Trong [`main/platform_utils.py`](file:///P:/A.Code/FB-Video-watching/main/platform_utils.py), bổ sung hàm chuẩn Win32:
     ```python
     def trim_process_memory() -> None:
         """
         Yêu cầu Windows thu hồi các trang nhớ vật lý nhàn rỗi (stale working set pages)
         trả về lại RAM của hệ thống. An toàn tuyệt đối, không ảnh hưởng tiến trình.
         """
         if sys.platform == "win32":
             try:
                 import ctypes
                 ctypes.windll.kernel32.SetProcessWorkingSetSize(
                     ctypes.windll.kernel32.GetCurrentProcess(), -1, -1
                 )
             except Exception:
                 pass
     ```
  2. Trong [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py):
     * Tạo hàm `_post_task_cleanup()`:
       ```python
       def _post_task_cleanup(self) -> None:
           """Dọn rác Python và ép Windows thu hồi RAM nhàn rỗi."""
           import gc
           gc.collect()
           from main.platform_utils import trim_process_memory
           trim_process_memory()
       ```
     * Gọi `_post_task_cleanup()` tại các thời điểm thích hợp:
       * Khoảng 1–2 giây sau khi video mới bắt đầu phát ổn định.
       * Khi người dùng nhấn Dừng video hoặc chuyển sang video khác.
       * Khi đóng hộp thoại Cài đặt hoặc Lịch sử xem.

---

## 3. Lộ trình triển khai khuyến nghị cho Model tiếp theo

| Bước | Hạng mục | File cần chỉnh sửa | Mục tiêu |
|---|---|---|---|
| **Bước 1** | Bổ sung hàm `trim_process_memory()` | [`main/platform_utils.py`](file:///P:/A.Code/FB-Video-watching/main/platform_utils.py) | Cung cấp công cụ hoàn trả RAM cho Windows |
| **Bước 2** | Dọn tàn dư Auto-Update (`.old`, `.zip`) | [`main/updater.py`](file:///P:/A.Code/FB-Video-watching/main/updater.py), [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py) | Xóa sạch 100MB file cũ nếu bị kẹt |
| **Bước 3** | Cắt tỉa `info_dict` & dọn rác Resolver | [`main/extractors/generic.py`](file:///P:/A.Code/FB-Video-watching/main/extractors/generic.py), [`main/extractors/youtube.py`](file:///P:/A.Code/FB-Video-watching/main/extractors/youtube.py) | Giảm 30–45MB RAM rác sau phân giải |
| **Bước 4** | Dọn file `.part` dở dang khi Hủy tải | [`main/downloader.py`](file:///P:/A.Code/FB-Video-watching/main/downloader.py) | Giữ sạch thư mục Downloads của user |
| **Bước 5** | Dọn file `.m3u8` tạm & giải phóng `vlc.Media` | [`main/extractors/youtube.py`](file:///P:/A.Code/FB-Video-watching/main/extractors/youtube.py), [`main/vlc_player.py`](file:///P:/A.Code/FB-Video-watching/main/vlc_player.py) | Xóa sạch buffer và manifest cũ khi đổi video |
| **Bước 6** | Hủy tham chiếu `SettingsDialog` khi đóng | [`main/gui.py`](file:///P:/A.Code/FB-Video-watching/main/gui.py) | Thu hồi toàn bộ UI objects khi đóng cửa sổ |
| **Bước 7** | Tích hợp `_post_task_cleanup()` | [`main/app.py`](file:///P:/A.Code/FB-Video-watching/main/app.py) | Kích hoạt chu trình dọn dẹp tự động |
| **Bước 8** | Chạy toàn bộ 176 bài Unit Test | Toàn bộ dự án | Đảm bảo 100% tests pass, không gây hồi quy |

---

## 4. Checklist kiểm tra nghiệm thu (Acceptance Checklist)

- [ ] Các tham số `network_caching`, `file_caching`, `decode_threads` trong Cài đặt và Auto-Tuner **giữ nguyên 100%**.
- [ ] Khi khởi động app, không còn file `FB-Video-Watcher.exe.old` nào sót lại trong thư mục.
- [ ] Khi bấm Hủy tải video, thư mục Downloads không bị tồn đọng file `.part`.
- [ ] Khi đổi qua lại giữa 5 video khác nhau, các file `.m3u8` cũ trong `%TEMP%/fbw_hls` được dọn sạch.
- [ ] Khi đóng SettingsDialog, RAM trong Task Manager giảm xuống rõ rệt sau 1–2 giây.
- [ ] Toàn bộ **176 bài kiểm thử tự động** tiếp tục pass 100%.
