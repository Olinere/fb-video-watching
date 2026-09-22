# Kế hoạch triển khai các tính năng mở rộng

Tài liệu này mô tả các thay đổi kỹ thuật trước khi bắt đầu code cho 5 nhóm tính năng:

1. Queue / Playlist phát liên tiếp.
2. Chapters / mục lục video.
3. Tích hợp Windows.
4. Preset theo nguồn với chế độ Auto và Custom tôn trọng lựa chọn người dùng.
5. Privacy Session.

## 0. Nguyên tắc không thay đổi

- Tiếp tục dùng Tkinter/sv-ttk cho GUI và VLC/libVLC cho playback.
- Không nhúng browser, WebView hoặc YouTube player.
- Không gửi heartbeat/timestamp ngược lên YouTube.
- Không lưu direct stream URL vào settings, history hoặc queue lâu dài vì URL CDN có thể hết hạn.
- yt-dlp chỉ làm nhiệm vụ resolve metadata và direct stream URL; VLC chịu trách nhiệm phát.
- Tất cả tác vụ mạng, resolve playlist, thumbnail và cập nhật metadata phải chạy ngoài Tkinter main thread.
- Callback từ worker/VLC phải marshal về main thread bằng root.after(...).
- Chế độ Custom của người dùng không được AutoTuner tự ý ghi đè.
- Tính năng mới phải có fallback an toàn, không làm hỏng playback video đơn hiện tại.
- Không log cookie, token, direct stream URL hoặc dữ liệu riêng tư.
- Mọi giá trị phần cứng, ngưỡng health và giới hạn queue phải nằm trong constants.py hoặc settings.json, không hardcode rải rác.
- Widget mới phải dùng ttk/ThemeManager; không gán màu cứng trong GUI.
- Code Win32 thấp tầng phải được cô lập qua platform_utils.py; module windows_integration.py chỉ điều phối nghiệp vụ.
- Mọi thao tác có thể vượt quá 50ms phải chạy ngoài Tkinter main thread.

## 1. Kiến trúc tổng thể

Luồng chính:

    Input URL / Windows protocol / File
                    |
                    v
           URL Resolver + Extractor
                    |
           +--------+---------+
           |                  |
           v                  v
      ResolvedVideo      ResolvedCollection
           |                  |
           +--------+---------+
                    v
           PlaybackQueue / QueueController
                    |
                    v
           PlaybackController trong app.py
                    |
                    v
                VLCPlayer

Các module mới dự kiến:

    main/
    ├── playback_queue.py       # QueueItem, PlaybackQueue, trạng thái queue
    ├── chapters.py             # Chapter model và chuẩn hóa chapter metadata
    ├── windows_integration.py  # CLI args, URI scheme, registry, forwarding
    ├── playback_health.py      # Theo dõi buffering/network health
    └── privacy_session.py      # Runtime policy chặn persistence nhạy cảm

Các module hiện tại cần mở rộng:

    main/app.py
    main/gui.py
    main/settings.py
    main/constants.py
    main/history.py
    main/url_resolver.py
    main/extractors/base.py
    main/extractors/youtube.py
    main/extractors/generic.py
    main/hotkeys.py
    main.py

---

## 2. Queue / Playlist phát liên tiếp

### 2.1. Mục tiêu

Cho phép người dùng:

- thêm URL đơn vào queue;
- thêm nhiều URL cùng lúc;
- dán URL playlist/album và chọn video muốn thêm;
- kéo thả để đổi thứ tự;
- phát video kế tiếp;
- bỏ qua item lỗi mà không dừng toàn bộ queue;
- chọn hành vi sau khi hết queue: dừng hoặc lặp queue.

Queue là dữ liệu runtime. Chỉ persist queue khi người dùng bật tùy chọn lưu queue; mặc định không tự lưu để tránh lưu URL nhạy cảm ngoài ý muốn.

### 2.2. Model QueueItem

Tạo QueueItem bằng dataclass:

    queue_id: UUID hoặc string ổn định trong phiên
    source_url: URL gốc dùng để resolve lại
    canonical_url: URL đã chuẩn hóa nếu có
    source_name: youtube/facebook/telegram/local/...
    content_id: ID video nếu extractor cung cấp
    title: tiêu đề hiển thị
    thumbnail_url: optional
    duration_ms: optional
    chapters: metadata nhỏ nếu đã có
    status: pending/resolving/ready/playing/played/skipped/error
    error_message: optional
    position: thứ tự trong queue
    privacy_only: bool

Không lưu các trường sau vào queue persistence:

- stream_url;
- audio_url;
- HTTP auth header;
- cookie;
- token CDN.

Stream URL phải được resolve lại khi item đến lượt phát.

### 2.3. PlaybackQueue và QueueController

PlaybackQueue chỉ quản lý dữ liệu, không biết Tkinter và không gọi VLC.

Các thao tác cần có:

- add(item);
- add_many(items);
- remove(queue_id);
- move(queue_id, new_index);
- clear();
- next_item();
- previous_item();
- current_item();
- mark_status(queue_id, status, error=None);
- snapshot();
- restore(snapshot).

QueueController hoặc app.py chịu trách nhiệm:

- resolve item hiện tại;
- đưa metadata lên UI;
- gọi VLC;
- xử lý Ended, Error, Skip;
- chuyển sang item kế tiếp;
- lưu history theo chính sách hiện tại.

### 2.4. Playlist resolve lazy

Không resolve toàn bộ direct stream của playlist cùng lúc.

Khi input là playlist/album:

1. Extractor lấy danh sách metadata dạng flat.
2. Trả về collection nhẹ gồm ID, URL, title, thumbnail nếu có.
3. UI hiển thị dialog chọn item hoặc nút Thêm tất cả.
4. Chỉ resolve direct stream khi item sắp được phát.

Điều này tránh tăng RAM và tránh tạo hàng loạt URL CDN sắp hết hạn.

Tạo model riêng ResolvedCollection, không nhét entries lớn vào ResolvedVideo:

    ResolvedCollection:
        source_url
        title
        entries: list[CollectionEntry]
        is_partial
        has_more

    CollectionEntry:
        source_url
        content_id
        title
        thumbnail_url
        duration_ms

Extractor không hỗ trợ collection vẫn phải hoạt động như video đơn.

### 2.5. Thay đổi extractor

Trong BaseExtractor bổ sung interface tùy chọn:

- supports_collections();
- extract_collection(...).

Base implementation có thể báo NotSupportedError. url_resolver sẽ fallback về video đơn.

Trong youtube.py:

- tách logic list playlist khỏi logic resolve video;
- không âm thầm lấy entry đầu tiên nếu UI có thể hiển thị danh sách;
- giữ setting tương thích cho workflow cũ: phát entry đầu tiên;
- giải phóng info_dict, formats và metadata thừa sau khi tạo model tinh gọn.

### 2.6. Quy tắc chuyển video

Chỉ chuyển queue khi VLC báo kết thúc tự nhiên.

Không chuyển queue ngay khi:

- stream bị lỗi giữa chừng;
- resolve thất bại;
- người dùng pause;
- người dùng đóng app.

Nếu resolve item tiếp theo thất bại:

- đánh dấu item error;
- giữ error để người dùng xem;
- nếu setting skip_failed_items bật thì thử item tiếp theo;
- không lặp vô hạn.

### 2.6.1. Tương tác với loop và A-B repeat hiện có

Queue loop và loop video hiện có là hai chế độ khác nhau:

- A-B repeat có ưu tiên cao nhất và giữ playback trong item hiện tại.
- Loop video hiện tại lặp item hiện tại, không chuyển queue.
- Chỉ khi item kết thúc tự nhiên và không có A-B/loop video đang hoạt động thì queue mới chuyển sang item kế tiếp.
- Queue loop chỉ chạy sau khi item cuối kết thúc tự nhiên.
- Khi user tắt loop video trong lúc queue đang chạy, queue tiếp tục từ item hiện tại theo trạng thái hiện tại; không tự nhảy item ngoài ý muốn.

Khi chuyển từ Telegram/proxy sang item kế tiếp hoặc nguồn khác, phải giữ đúng thứ tự lifecycle hiện có:

1. lưu runtime state nếu policy cho phép;
2. dừng VLC;
3. gọi StreamProxyServer.stop_async() nếu proxy cũ đang hoạt động;
4. resolve item mới ở worker;
5. cập nhật VLC trên main thread.

### 2.6.2. Local file và giới hạn playlist

Local media file phải được phép đưa vào queue nhưng không đi qua network resolver. LocalExtractor trả metadata trực tiếp và queue vẫn dùng cùng state machine.

Để playlist dài không làm phình RAM/UI:

- đặt giới hạn số entry nạp một lần trong constants.py;
- hỗ trợ pagination hoặc nút “Nạp thêm” nếu extractor cung cấp;
- không tải thumbnail toàn bộ playlist trước khi user chọn;
- Treeview chỉ render các row cần thiết nếu số lượng lớn.

### 2.7. UI Queue

Thêm Queue panel có thể dock/collapse, không chiếm diện tích video khi đóng.

Mỗi row hiển thị:

- thứ tự;
- title hoặc URL rút gọn;
- duration nếu có;
- trạng thái;
- biểu tượng lỗi nếu resolve thất bại.

Context menu:

- Phát ngay;
- Phát tiếp theo;
- Xóa khỏi queue;
- Di chuyển lên/xuống;
- Xóa các item đã xem;
- Retry item lỗi;
- Mở URL nguồn.

Nút chính:

- Thêm URL vào queue;
- Dán và thêm;
- Xóa queue;
- Chọn hành vi khi hết queue.

Hotkey dự kiến:

- Ctrl+Shift+Q: mở/đóng Queue;
- PageDown: item kế tiếp;
- PageUp: item trước đó.

Các hotkey phải đi qua hệ thống hotkey hiện tại, không hardcode riêng trong GUI.

### 2.8. Tiêu chí nghiệm thu queue

- Dán video đơn vẫn phát như trước.
- Dán playlist không block GUI.
- Playlist dài không tạo hàng trăm direct stream URL trong RAM.
- Item lỗi không làm queue crash.
- Stream URL không được lưu vào settings/history/queue persistence.
- Queue tự chuyển sau Ended, nhưng không tự chuyển sau lỗi mạng nếu retry chưa xong.
- Đóng/mở Queue panel không ảnh hưởng player.

---

## 3. Chapters / mục lục video

### 3.1. Mục tiêu

Nếu extractor cung cấp chapters, người dùng xem được mục lục và chọn chapter để phát từ đầu chapter. Nếu nguồn không có chapter, UI không hiển thị panel rỗng gây khó hiểu.

### 3.2. Model Chapter

Tạo Chapter:

    index: int
    title: str
    start_ms: int
    end_ms: Optional[int]

Chuẩn hóa:

- bỏ chapter thiếu title hoặc start không hợp lệ;
- clamp start về 0;
- clamp end không vượt duration nếu duration biết;
- sort theo start_ms;
- loại chapter trùng hoặc overlap bất thường;
- không cho phép chapter âm hoặc vượt duration quá mức.

### 3.3. ResolvedVideo

Mở rộng ResolvedVideo:

    chapters: list[Chapter]
    content_id: Optional[str]
    source_name: Optional[str]
    canonical_url: Optional[str]

Trong youtube.py lấy từ info.get("chapters"). Extractor khác có thể map metadata tương đương nếu nguồn cung cấp.

Chapters chỉ là metadata nhỏ, không tải thêm video hoặc thumbnail riêng.

### 3.4. UI

Thêm nút Mục lục cạnh khu vực điều khiển hoặc trong menu video.

Khi không có chapter:

- ẩn nút; hoặc
- disable nút với tooltip “Video không cung cấp mục lục”.

Panel hiển thị:

- tên chapter;
- thời điểm bắt đầu;
- chapter hiện tại được highlight theo vị trí VLC;
- click để seek đến start_ms.

Khi đổi video, panel phải được thay mới atomically để không hiển thị chapter của video trước.

Khi re-resolve cùng video, giữ lại chapter metadata cũ nếu content_id không đổi.

### 3.5. Tiêu chí nghiệm thu chapters

- Video có chapters hiển thị đúng thứ tự.
- Click chapter seek đúng và UI không bị timer VLC ghi đè.
- Video không có chapters không tạo exception.
- Chapters không làm tăng đáng kể thời gian resolve hoặc RAM.
- Chapters của playlist item được giữ nếu metadata đã có.

---

## 4. Tích hợp Windows

### 4.1. Phạm vi

Tích hợp Windows gồm:

1. Nhận URL/file từ command line.
2. Đăng ký URI scheme riêng.
3. Tùy chọn Open with cho file media.
4. Forward input mới vào instance đang chạy.
5. Cài đặt/gỡ đăng ký an toàn ở HKCU, không yêu cầu Administrator.

Không tự ý chiếm association của mp4, mkv hoặc browser. Người dùng phải opt-in.

### 4.2. Command line contract

Entry point main.py nhận:

- một hoặc nhiều URL;
- một hoặc nhiều đường dẫn file local;
- --add-to-queue;
- --play-now;
- --privacy;
- --no-focus nếu cần.

Input phải đi qua cùng handle_play_request hoặc QueueController, không tạo pipeline riêng.

### 4.3. URI scheme

Đề xuất scheme:

    fbvw://play?url=<url-encoded-source-url>
    fbvw://queue?url=<url-encoded-source-url>

Tên scheme phải được chốt một lần và dùng thống nhất trong installer/docs.

Quy tắc:

- decode URL đúng một lần;
- reject scheme/host không hợp lệ;
- không thực thi chuỗi nhận được như command;
- fbvw://play phát ngay;
- fbvw://queue thêm vào queue;
- Privacy từ URI phải được bật trước khi tạo queue/playback.

### 4.4. Forwarding instance

Hiện đặc tả cho phép nhiều instance. Không ép single-instance toàn app ngay lập tức.

Đề xuất:

- mặc định vẫn cho phép nhiều instance;
- thêm setting reuse_existing_instance, mặc định bật cho URI/protocol;
- instance đầu tiên tạo mutex/named pipe theo user;
- instance mới gửi payload cho instance đầu tiên rồi thoát;
- nếu forwarding thất bại, instance mới tiếp tục khởi động bình thường.

Payload chỉ gồm:

    action: play/add_to_queue
    items: list[str]
    privacy: bool

Không truyền cookie hoặc stream URL qua pipe.

Transport nằm trong windows_integration.py. App chỉ nhận callback.

Các hàm gọi Registry, mutex, named pipe, foreground window và command line Win32 phải nằm trong platform_utils.py hoặc một adapter Win32 được platform_utils.py gọi. windows_integration.py không được rải các lời gọi ctypes/pywin32 trong logic nghiệp vụ.

### 4.5. Registry

Chỉ ghi HKEY_CURRENT_USER:

- Software\Classes\fbvw cho URI scheme;
- Software\Classes\Applications\FB-Video-Watcher.exe cho Open with;
- context menu chỉ tạo khi người dùng bật.

Installer/uninstaller phải register/unregister đối xứng. Không xóa key nếu key đã bị người dùng sửa thành cấu hình khác.

### 4.6. Settings UI

Thêm nhóm Windows Integration:

- nhận link fbvw://;
- dùng instance đang chạy;
- đăng ký Open with cho file media;
- thêm context menu Explorer;
- nút Đăng ký lại;
- nút Hủy đăng ký.

Hiển thị trạng thái đăng ký thực tế, không chỉ trạng thái trong settings.

### 4.7. Tiêu chí nghiệm thu Windows

- Double-click URI mở đúng app và đúng hành động.
- Gửi nhiều URL không làm mất item.
- Nếu app đang chạy, URL được chuyển tới đúng instance.
- Nếu instance đầu tiên không phản hồi, instance thứ hai vẫn mở được.
- Uninstall không xóa association không thuộc về app.
- Không cần Administrator.
- Đường dẫn có khoảng trắng và Unicode hoạt động.

---

## 5. Preset theo nguồn với Auto/Custom

### 5.1. Quy tắc bắt buộc

- Auto: ứng dụng được phép tự chọn chất lượng, network caching và tùy chọn phù hợp.
- Custom: ứng dụng không được tự ý đổi giá trị người dùng đã chọn.
- Custom gặp mạng yếu thì chỉ cảnh báo/gợi ý, không tự hạ chất lượng hoặc đổi buffer.
- Chỉ khi người dùng nhấn Áp dụng thì thay đổi mới có hiệu lực.
- Tắt popup không đồng nghĩa đổi preset.

### 5.2. Settings schema

Mở rộng settings:

    source_profiles:
        global:
            mode: auto
            max_height: 1080
            network_caching_ms: 3000
            hardware_decode: true
        youtube.com:
            mode: custom
            max_height: 1080
            network_caching_ms: 3000
            hardware_decode: true
        facebook.com:
            mode: auto

Tên profile dùng normalized source/domain, không dùng URL đầy đủ.

Giá trị hợp lệ:

- mode: auto hoặc custom;
- max_height: 360, 480, 720, 1080, 0 cho best;
- network_caching_ms: trong range an toàn của VLC;
- hardware_decode: bool.

Nếu không có profile riêng, dùng global.

### 5.2.1. Tương thích settings cũ

Settings hiện tại đã có:

- video.max_height;
- streaming.network_caching;
- streaming.hardware_decode;
- streaming.decode_threads.

Migration phải giữ dữ liệu cũ và xác định mode rõ ràng:

- file settings mới hoặc giá trị cũ còn đúng default: tạo global.mode = auto;
- nếu giá trị cũ khác default hiện hành: coi đó là user override và tạo global.mode = custom với đúng các giá trị cũ;
- không tự biến một giá trị Custom cũ thành Auto;
- sau migration, mode là nguồn sự thật; không suy luận lại mode ở mỗi lần chạy.

Khi profile source tồn tại, profile source override global; khi không tồn tại, global override các field legacy. Các setting không thuộc profile như volume, speed, subtitle và hotkey giữ nguyên schema hiện tại.

### 5.3. Luồng chọn cấu hình

Trước mỗi lần resolve:

1. Xác định source/domain.
2. Đọc profile source.
3. Fallback về global.
4. Nếu Auto, gọi AutoTuner với profile và system info.
5. Nếu Custom, chuyển nguyên giá trị người dùng vào resolver/VLC.
6. Không ghi ngược giá trị tạm thời của AutoTuner vào settings.

AutoTuner hiện tại đang nhận user_settings và dùng settings.streaming làm override. Cần refactor thành một PlaybackConfig trung gian để không phá quy tắc cũ User Settings > AutoTuner > constants:

    source profile chọn mode và các override nội dung;
    PlaybackConfig merge source profile với global/legacy settings;
    AutoTuner chỉ tính phần có mode=auto;
    phần custom được giữ nguyên;
    VLCArgsBuilder nhận PlaybackConfig cuối cùng.

Không truyền trực tiếp một dict profile chưa merge vào nhiều module khác nhau.

Profile không được lấy từ URL đầy đủ và không được ảnh hưởng chéo giữa các domain.

### 5.4. Auto profile

Auto được phép quyết định:

- max height;
- network caching;
- decode threads;
- hardware decode theo system info;
- fallback format khi nguồn không cung cấp đúng chất lượng.

Auto không được thay đổi:

- volume;
- playback speed;
- subtitle style;
- hotkey;
- privacy state.

AutoTuner nên trả về object kết quả, không sửa trực tiếp settings:

    TunedPlaybackConfig:
        max_height
        network_caching_ms
        hardware_decode
        decode_threads
        reason[]

Settings chỉ lưu việc user chọn Auto, không lưu mọi giá trị tạm thời AutoTuner tính ra.

### 5.5. PlaybackHealthMonitor

Tạo PlaybackHealthMonitor chạy theo tick UI hiện có hoặc timer nhẹ.

Theo dõi:

- thời gian ở trạng thái Buffering;
- số lần buffering trong cửa sổ thời gian;
- thời gian playback thực tế so với wall clock;
- số lần VLC error/re-resolve;
- tốc độ tải nếu VLC/stream proxy cung cấp số liệu đáng tin cậy.

Không kết luận mạng yếu chỉ từ một lần buffering ngắn. Dùng các trạng thái:

- healthy;
- degraded;
- critical.

Các ngưỡng và cooldown nằm trong constants.py, không hardcode trong GUI.

### 5.6. Popup gợi ý

Khi health chuyển degraded hoặc critical:

- nếu profile là Auto: hiển thị trạng thái đang tự điều chỉnh, không hỏi đổi profile;
- nếu profile là Custom: chỉ hiển thị cảnh báo/gợi ý;
- không lặp popup liên tục; có cooldown theo video và session.

Mẫu thông báo:

    Mạng có dấu hiệu không ổn định hoặc tốc độ tải không đủ
    cho cấu hình hiện tại.

    Gợi ý: chuyển sang Auto. Ứng dụng có thể giảm độ phân giải
    để stream mượt hơn.

    [Áp dụng Auto] [Giữ cấu hình hiện tại]
    [Không nhắc lại cho video này]

Khi nhấn Áp dụng Auto:

1. Lưu profile source thành Auto nếu user chọn áp dụng cho nguồn này; hoặc chỉ áp dụng runtime nếu chọn chỉ lần này.
2. Lưu vị trí playback hiện tại.
3. Dừng media cũ an toàn.
4. Resolve lại với config Auto.
5. Phát lại từ vị trí cũ.
6. Giữ subtitle, volume, speed và privacy state.

Vì specs.md quy định network caching/hardware decode có thể chỉ áp dụng cho video tiếp theo, popup “Áp dụng Auto” là ngoại lệ có chủ ý: nó phải dùng flow reconfigure hiện tại, lưu vị trí, reinitialize VLC đúng lifecycle rồi resolve/phát lại. Không gọi SettingsManager.set() nhiều lần trong popup vì set() hiện tự save ngay và có thể tạo trạng thái nửa chừng.

Khi nhấn Giữ cấu hình hiện tại, không thay đổi settings và không tự hạ chất lượng.

### 5.7. UI preset

Trong Settings thêm Playback Profiles:

- profile Global;
- danh sách source/domain đã dùng;
- combobox Auto/Custom;
- max resolution;
- network caching;
- hardware decode;
- Khôi phục mặc định;
- Áp dụng ngay.

Ở thanh trạng thái player có thể hiển thị:

    Profile: YouTube / Custom
    Health: Tốt

Không đưa quá nhiều thông số kỹ thuật lên UI chính.

### 5.8. Tiêu chí nghiệm thu preset

- Custom 1080p không tự tụt xuống 720p.
- Custom buffer không bị AutoTuner thay đổi.
- Mạng yếu chỉ tạo cảnh báo và gợi ý.
- Popup có thể áp dụng ngay và resume đúng vị trí.
- Auto có thể tự điều chỉnh nhưng không thay đổi setting không liên quan.
- Profile YouTube không ảnh hưởng Facebook hoặc nguồn khác.
- Có thể hoàn nguyên về Auto/Custom rõ ràng.

---

## 6. Privacy Session

### 6.1. Mục tiêu

Cho phép xem video mà không ghi dữ liệu phiên vào history/settings/persistence của ứng dụng.

Privacy Session không đăng xuất YouTube/Facebook và không xóa cookie. Cookie vẫn có thể được dùng để resolve video riêng tư.

### 6.2. Dữ liệu bị chặn

Trong Privacy Session, không ghi:

- watch history mới;
- playback position/resume state;
- last URL;
- thumbnail cache lâu dài;
- queue persistence;
- bookmark mới;
- source profile mới;
- log chứa URL đầy đủ hoặc title nhạy cảm nếu redaction bật.

Không xóa history cũ.

Privacy Session chặn persistence tự động liên quan đến nội dung đang xem, không biến SettingsManager thành read-only tuyệt đối. Các thay đổi preference người dùng chủ động bấm “Lưu & Đóng” như theme, hotkey, volume hoặc subtitle style vẫn có thể được lưu. Riêng last_url, history/resume, queue snapshot, source profile phát sinh từ health popup và metadata nội dung phải bị chặn hoặc chỉ lưu sau khi session kết thúc nếu user xác nhận.

Các file tạm vẫn phải được dọn:

- HLS manifest;
- bản sao cookie tạm;
- file proxy tạm;
- metadata cache tạm.

### 6.3. Runtime policy

Tạo PrivacySession hoặc RuntimePersistencePolicy để các module hỏi policy thay vì tự kiểm tra cờ GUI:

    is_enabled()
    allow_history_write()
    allow_resume_write()
    allow_content_state_write()
    allow_explicit_user_settings_write()
    allow_queue_persist()
    redact_diagnostics()

HistoryManager không cần biết UI. app.py hoặc policy wrapper quyết định có write hay dùng no-op.

### 6.4. Bật/tắt session

Privacy Session là runtime-only:

- mặc định tắt khi khởi động lại;
- không lưu trạng thái Privacy vào settings.json;
- có toggle ở menu/toolbar;
- hiển thị badge rõ ràng: PRIVATE SESSION.

Nếu bật khi đang xem:

- hiện xác nhận;
- từ thời điểm xác nhận trở đi không ghi thêm;
- dữ liệu đã ghi trước đó không tự động xóa;
- tùy chọn xóa bản ghi video hiện tại phải là thao tác riêng có xác nhận.

Nếu Privacy được truyền từ Windows URI/CLI, phải bật trước khi tạo queue/playback và hiển thị badge ngay khi GUI khởi động.

### 6.5. Queue trong Privacy Session

Queue vẫn hoạt động nhưng chỉ tồn tại trong RAM.

- item thêm trong session được đánh dấu privacy_only;
- không ghi queue snapshot ra disk;
- khi tắt session, hỏi có muốn xóa item privacy khỏi queue;
- không trộn item privacy vào recent history.

### 6.6. Cookie và log

Privacy Session không tạo cơ chế cookie mới ngoài temporary copy hiện tại.

Log phải redact:

- query có token;
- direct media URL;
- URL có thông tin định danh nhạy cảm;
- path cookie;
- session/account identifier.

Thông báo lỗi vẫn phải hữu ích nhưng không in nguyên exception có thể chứa signed URL.

### 6.7. Tiêu chí nghiệm thu Privacy

- Bật Privacy rồi phát video không tạo row mới trong history.
- Đóng app không lưu last URL của video privacy.
- Không ghi resume position.
- Queue privacy không còn sau restart.
- Cookie vẫn hoạt động cho video yêu cầu auth.
- History cũ không bị xóa ngoài thao tác người dùng.
- Badge và toggle phản ánh đúng runtime state.

---

## 7. Settings schema và migration

Thêm settings_schema_version.

Migration phải:

- merge settings mới với default;
- giữ nguyên settings cũ;
- tạo source_profiles nếu chưa có;
- tạo defaults cho queue nếu cần;
- không bật Privacy Session tự động;
- không thay đổi giá trị Custom người dùng đã lưu.

Mọi giá trị JSON phải được validate/clamp. Settings hỏng một phần không được làm app crash.

---

## 8. Thay đổi dự kiến theo file

### File mới

- main/playback_queue.py
- main/chapters.py
- main/windows_integration.py
- main/playback_health.py
- main/privacy_session.py

### File cần sửa

- main.py: parse CLI và khởi tạo Windows integration.
- main/app.py: điều phối queue, chapter, health warning, privacy và Windows input.
- main/gui.py: Queue panel, Chapter panel, preset state, privacy badge.
- main/settings.py: schema version, source profiles, Windows options.
- main/constants.py: defaults, thresholds, cooldowns, profile schema.
- main/hotkeys.py: hotkey queue/chapter nếu bật.
- main/extractors/base.py: ResolvedCollection, Chapter, source/content metadata.
- main/extractors/youtube.py: playlist listing, lazy resolution, chapters.
- main/extractors/generic.py: map chapters/content metadata nếu có; fallback video đơn.
- main/url_resolver.py: normalized source identity và collection dispatch.
- main/history.py: policy-aware write boundary nếu cần.
- main/platform_utils.py: adapter Win32 cho Registry, mutex/named pipe, foreground/focus và đường dẫn executable; giữ nguyên các helper multi-monitor, DWM, toast hiện có.
- main/updater.py hoặc installer script: giữ registry association sau update và hỗ trợ unregister.

Sau khi code xong cần cập nhật:

- specs.md;
- Agent.md;
- README.md;
- docs/ cho Queue, Windows integration, presets và Privacy Session.

---

## 9. Kiểm thử

### Unit tests mới

- tests/test_playback_queue.py
- tests/test_chapters.py
- tests/test_windows_integration.py
- tests/test_playback_health.py
- tests/test_privacy_session.py

Mở rộng:

- tests/test_settings.py;
- tests/test_extractors.py;
- tests/test_url_resolver.py;
- tests/test_extended_features.py.

Test GUI phải tuân thủ quy ước hiện tại: root withdrawn, không mở fullscreen/dialog thật trên desktop, và callback worker phải được mock/marshal về main thread.

### Case bắt buộc

Queue:

- thêm/xóa/reorder;
- duplicate URL;
- queue rỗng;
- playlist rỗng;
- playlist dài;
- item lỗi;
- item bị xóa;
- chuyển queue sau ended;
- không chuyển queue sau lỗi chưa xử lý.

Chapters:

- chapter hợp lệ;
- thiếu title;
- overlap;
- ngoài duration;
- video không có chapter;
- chapter thay đổi khi đổi video.

Windows:

- URL Unicode;
- path có khoảng trắng;
- nhiều input;
- protocol play/queue;
- forwarding thành công/thất bại;
- registry đã tồn tại;
- unregister không xóa cấu hình ngoài app.

Preset:

- Auto được điều chỉnh;
- Custom không bị thay đổi;
- popup cooldown;
- áp dụng Auto runtime;
- áp dụng Auto cho source;
- re-resolve sau khi áp dụng.

Privacy:

- không ghi history;
- không ghi last URL;
- không ghi queue;
- cookie vẫn dùng được;
- session không làm mất history cũ;
- bật/tắt giữa playback.

Compatibility/performance:

- settings cũ được migration đúng;
- User Custom override vẫn thắng AutoTuner;
- loop video/A-B không bị queue auto-next phá;
- Telegram proxy shutdown không block main thread khi queue chuyển item;
- local file queue không gọi yt-dlp;
- queue dài không giữ stream URL hoặc thumbnail hàng loạt;
- multi-instance thông thường vẫn được phép; chỉ URI/protocol mới forward khi setting bật.

### Manual integration tests

- YouTube video đơn;
- YouTube playlist;
- Facebook video đơn;
- Telegram stream/proxy;
- local media file;
- nguồn cần cookie;
- mạng chậm hoặc mất mạng;
- VLC error giữa queue;
- chạy từ Explorer/URI/command line;
- app đang chạy và app chưa chạy;
- Privacy từ đầu và Privacy giữa phiên;
- Custom profile bị buffering nhưng không tự hạ chất lượng.

---

## 10. Thứ tự triển khai

### Phase 1 — Model và nền tảng

1. Tạo model queue/chapter/profile/privacy.
2. Thêm settings migration.
3. Viết test model thuần, chưa đụng GUI.

### Phase 2 — Chapters

1. Mở rộng ResolvedVideo.
2. Parse và normalize chapters.
3. Hiển thị chapter panel.
4. Tích hợp seek và test.

### Phase 3 — Queue/Playlist

1. Queue runtime cho video đơn.
2. Auto-next sau ended tự nhiên.
3. Playlist listing lazy.
4. Queue panel và retry/skip.
5. Queue persistence tùy chọn.

### Phase 4 — Preset và health monitor

1. Source profile schema.
2. Tách Auto/Custom trong AutoTuner.
3. Health monitor.
4. Popup gợi ý có Apply/Keep.
5. Re-resolve khi Apply Auto.

### Phase 5 — Privacy Session

1. Runtime policy.
2. Chặn history/settings/queue writes.
3. UI badge và toggle.
4. Redact log/diagnostic.

### Phase 6 — Windows integration

1. CLI parser.
2. URI scheme.
3. Registry opt-in.
4. Forwarding instance tùy chọn.
5. Installer/uninstaller và manual test.

### Phase 7 — Hoàn thiện

1. Chạy toàn bộ test suite.
2. Đo RAM/CPU trước và sau khi thêm queue/chapters.
3. Kiểm tra không giữ direct URL/token quá vòng đời cần thiết.
4. Cập nhật specs.md, Agent.md, README.md.
5. Build thử bản portable và installer.

---

## 11. Mặc định đề xuất cần giữ

- Queue không persist mặc định.
- Playlist mở dialog chọn item, không tự phát toàn bộ ngay.
- Item lỗi được đánh dấu và hỏi/skip theo setting, không skip im lặng mặc định.
- Queue hết thì dừng, không tự loop mặc định.
- Chapters chỉ hiển thị khi metadata có sẵn.
- Windows integration ghi HKCU và phải opt-in.
- Reuse existing instance mặc định bật cho URI/protocol, nhưng không cấm chạy nhiều instance thông thường.
- Source profile mặc định là Auto.
- Custom không bao giờ bị sửa tự động.
- Health warning chỉ là gợi ý, không tự đổi cấu hình.
- Privacy Session mặc định tắt sau mỗi lần khởi động.

## 12. Tiêu chí hoàn thành tổng thể

- Playback video đơn hiện tại không bị regression.
- Queue/playlist hoạt động mà không tăng RAM theo số lượng direct stream.
- Chapters hiển thị đúng và không làm chậm resolve.
- Windows URI/Open with hoạt động với Unicode và khoảng trắng.
- Auto tối ưu được, Custom luôn được tôn trọng.
- Cảnh báo mạng yếu có nút áp dụng rõ ràng và không tự ý thay đổi.
- Privacy Session không để lại history/resume/last URL/queue persistence.
- Tác vụ nặng vẫn chạy ngoài Tkinter main thread.
- Toàn bộ test hiện có và test mới đều pass.
- Tài liệu dự án phản ánh đúng hành vi thực tế.

## 13. Đối chiếu với specs.md, Agent.md và README.md

### 13.1. specs.md

Các điểm phải cập nhật trong specs.md trước khi coi tính năng hoàn thành:

- Luồng chính phải có nhánh collection/queue sau URL Resolver, nhưng vẫn giữ nhánh video đơn.
- ResolvedVideo phải bổ sung chapters, source_name, content_id và canonical_url; ResolvedCollection là model riêng.
- GUI layout phải bổ sung Queue panel, Chapter panel và badge Privacy Session nhưng các panel phải collapse được để giữ video surface chiếm phần lớn cửa sổ.
- Settings phải bổ sung source profiles, mode Auto/Custom, Windows Integration và Privacy Session runtime.
- Quy tắc hiệu năng phải giữ ThreadPoolExecutor/root.after, không block Tkinter; playlist resolve dùng worker và queue chuyển item phải dừng proxy Telegram theo đúng lifecycle hiện tại.
- Edge cases phải bổ sung playlist rỗng/dài, item lỗi, playlist có private item, chapter lỗi, URI Unicode, registry đã tồn tại, forwarding thất bại, Custom profile bị buffering và Privacy Session.
- Quy tắc loop phải ghi rõ thứ tự A-B repeat > loop video > queue loop.
- Hướng dẫn Windows phải ghi rõ registry HKCU và opt-in, không tự chiếm file association.

### 13.2. Agent.md

Các nguyên tắc phải giữ nguyên trong code mới:

- không hardcode CPU/GPU/thread/threshold;
- User Settings > AutoTuner > constants;
- module độc lập, dependency injection, không circular import;
- GUI chỉ gọi interface, không truy cập internal VLC/queue state;
- platform-specific thấp tầng nằm ở platform_utils.py;
- mọi tác vụ trên 50ms chạy worker;
- callback VLC/worker marshal về main thread;
- không làm hỏng multi-monitor fullscreen, StreamProxyServer async shutdown, updater và VLC lifecycle;
- không tự chạy build.bat/PyInstaller khi chưa có yêu cầu rõ ràng.

Cấu trúc thư mục trong Agent.md phải bổ sung các module mới và test tương ứng sau khi code thật sự được tạo; không cập nhật sơ đồ như thể file đã tồn tại trước khi implementation hoàn thành.

### 13.3. README.md

README phải bổ sung phần hướng dẫn người dùng, không chỉ mô tả implementation:

- thêm Queue/Playlist: thêm URL, chọn item playlist, đổi thứ tự, retry/skip;
- thêm Chapters: mở mục lục và chọn chapter;
- thêm Windows Integration: URI scheme, Open with, opt-in và cách hủy đăng ký;
- thêm Preset theo nguồn: Auto tự tối ưu, Custom được tôn trọng, popup mạng yếu chỉ gợi ý và nút Áp dụng mới thay đổi;
- thêm Privacy Session: badge, dữ liệu không lưu, cookie vẫn có thể dùng để resolve video riêng tư;
- cập nhật bảng hotkey sau khi chốt hotkey queue/chapter;
- cập nhật danh sách test và các xử lý lỗi mới.

Không tuyên bố queue/chapters/Windows integration/Privacy đã có trong README trước khi code và test hoàn thành.

### 13.4. Các điểm không được thay đổi ngầm

- Mục tiêu vẫn là native VLC player nhẹ thay browser.
- YouTube/Facebook vẫn chỉ được resolve thành stream để VLC phát; không có đồng bộ timestamp tài khoản.
- Cookie vẫn chỉ là đầu vào xác thực cho resolver, không phải session heartbeat.
- Settings Custom hiện tại không được tự hạ độ phân giải, tự đổi buffer hoặc tự reconfigure nếu user chưa xác nhận.
- Nhiều instance vẫn được phép trong launch thông thường; forwarding chỉ là tùy chọn cho URI/Open with.
