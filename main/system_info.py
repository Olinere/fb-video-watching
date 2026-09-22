"""
Module for detecting system hardware and software capabilities.
Strictly adheres to Agent.md §2:
- Never hardcodes hardware specifications.
- Safe fallbacks for all components; never raises unhandled exceptions.
"""

from dataclasses import dataclass, field
import json
import os
import platform
import subprocess
import sys
from typing import Optional, Dict, Any, List


@dataclass
class SystemInfo:
    """Dataclass holding detected hardware and environment specifications."""

    # --- CPU ---
    cpu_name: str              # e.g., "Intel(R) Core(TM) i5-13500"
    cpu_cores_physical: int    # Physical cores
    cpu_cores_logical: int     # Logical threads
    cpu_freq_mhz: float        # CPU clock frequency in MHz

    # --- RAM ---
    ram_total_gb: float        # Total physical RAM in GB
    ram_available_gb: float    # Available physical RAM in GB

    # --- GPU ---
    gpu_name: str              # Detected GPU name(s)
    gpu_vram_mb: Optional[int] # VRAM in MB if detectable
    gpu_vendor: str            # "nvidia" | "amd" | "intel" | "unknown"

    # --- OS ---
    os_name: str               # "Windows", "Linux", "Darwin"
    os_version: str            # e.g. "10.0.22631"
    os_arch: str               # "64bit" or "32bit"

    # --- Python & VLC ---
    python_version: str        # e.g. "3.12.4"
    python_arch: str           # e.g. "64bit"
    vlc_version: Optional[str] # e.g. "3.0.20" or None
    vlc_arch: Optional[str]    # e.g. "64bit" or None

    # --- CPU Architecture & Topology ---
    is_hybrid_cpu: bool = False             # True if Intel P/E cores or AMD Zen/Zen-c hybrid
    cpu_p_cores: int = 0                    # Count of Performance Cores
    cpu_e_cores: int = 0                    # Count of Efficient Cores
    p_core_logical_indices: List[int] = field(default_factory=list)  # Logical thread IDs of P-cores
    e_core_logical_indices: List[int] = field(default_factory=list)  # Logical thread IDs of E-cores

    _cached_info: Optional["SystemInfo"] = None

    @classmethod
    def detect(cls, force_refresh: bool = False) -> "SystemInfo":
        """
        Auto-detect all system details.
        Guaranteed to return a valid SystemInfo instance with fallbacks without raising.
        Caches the result so subsequent calls (e.g. opening Settings dialog) are instantaneous.
        """
        if not force_refresh and cls._cached_info is not None:
            return cls._cached_info

        cpu_name = cls._detect_cpu_name()
        cpu_phys, cpu_log, cpu_freq = cls._detect_cpu_details()
        is_hybrid, p_cores, e_cores, p_idx, e_idx = cls._detect_cpu_topology(cpu_log, cpu_phys)
        ram_total, ram_avail = cls._detect_ram()
        gpu_name, gpu_vram, gpu_vendor = cls._detect_gpu()
        os_name, os_version, os_arch = cls._detect_os()
        py_ver, py_arch = cls._detect_python()
        vlc_ver, vlc_arch = cls._detect_vlc(py_arch)

        info = cls(
            cpu_name=cpu_name,
            cpu_cores_physical=cpu_phys,
            cpu_cores_logical=cpu_log,
            cpu_freq_mhz=cpu_freq,
            ram_total_gb=round(ram_total, 2),
            ram_available_gb=round(ram_avail, 2),
            gpu_name=gpu_name,
            gpu_vram_mb=gpu_vram,
            gpu_vendor=gpu_vendor,
            os_name=os_name,
            os_version=os_version,
            os_arch=os_arch,
            python_version=py_ver,
            python_arch=py_arch,
            vlc_version=vlc_ver,
            vlc_arch=vlc_arch,
            is_hybrid_cpu=is_hybrid,
            cpu_p_cores=p_cores,
            cpu_e_cores=e_cores,
            p_core_logical_indices=p_idx,
            e_core_logical_indices=e_idx,
        )
        cls._cached_info = info
        return info

    # --- Detection Helpers ---

    @staticmethod
    def _detect_cpu_name() -> str:
        """Detect human-readable CPU brand/name."""
        # On Windows, winreg gives the clearest official name
        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                )
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return str(val).strip()
            except Exception:
                pass

        # Fallback using platform module
        proc = platform.processor()
        if proc:
            return proc.strip()
        return "Unknown CPU"

    @staticmethod
    def _detect_cpu_details() -> tuple[int, int, float]:
        """Returns (physical_cores, logical_cores, freq_mhz)."""
        logical = os.cpu_count() or 4
        physical = max(1, logical // 2)
        freq = 0.0

        try:
            import psutil
            ps_logical = psutil.cpu_count(logical=True)
            if ps_logical:
                logical = ps_logical
            ps_phys = psutil.cpu_count(logical=False)
            if ps_phys:
                physical = ps_phys
            ps_freq = psutil.cpu_freq()
            if ps_freq and ps_freq.max:
                freq = float(ps_freq.max)
            elif ps_freq and ps_freq.current:
                freq = float(ps_freq.current)
        except Exception:
            pass

        return physical, logical, freq

    @staticmethod
    def _detect_cpu_topology(
        logical_cores: int, physical_cores: int
    ) -> tuple[bool, int, int, List[int], List[int]]:
        """
        Detect hybrid CPU topology (Performance vs Efficient cores) and thread affinity masks.
        Supports Intel 12th/13th/14th Gen/Core Ultra and AMD Zen/Zen-c hybrid processors.
        Returns:
            (is_hybrid, p_core_count, e_core_count, p_core_logical_indices, e_core_logical_indices)
        """
        is_hybrid = False
        p_cores = physical_cores
        e_cores = 0
        p_indices = list(range(logical_cores))
        e_indices: List[int] = []

        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                RelationProcessorCore = 0

                class GROUP_AFFINITY(ctypes.Structure):
                    _fields_ = [
                        ("Mask", ctypes.c_size_t),
                        ("Group", wintypes.WORD),
                        ("Reserved", wintypes.WORD * 3),
                    ]

                class PROCESSOR_RELATIONSHIP(ctypes.Structure):
                    _fields_ = [
                        ("Flags", wintypes.BYTE),
                        ("EfficiencyClass", wintypes.BYTE),
                        ("Reserved", wintypes.BYTE * 20),
                        ("GroupCount", wintypes.WORD),
                        ("GroupMask", GROUP_AFFINITY * 1),
                    ]

                class SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX(ctypes.Structure):
                    _fields_ = [
                        ("Relationship", wintypes.DWORD),
                        ("Size", wintypes.DWORD),
                        ("Processor", PROCESSOR_RELATIONSHIP),
                    ]

                buffer_size = wintypes.DWORD(0)
                ctypes.windll.kernel32.GetLogicalProcessorInformationEx(
                    RelationProcessorCore, None, ctypes.byref(buffer_size)
                )
                if buffer_size.value > 0:
                    buf = ctypes.create_string_buffer(buffer_size.value)
                    if ctypes.windll.kernel32.GetLogicalProcessorInformationEx(
                        RelationProcessorCore, buf, ctypes.byref(buffer_size)
                    ):
                        offset = 0
                        raw_cores = []
                        while offset < buffer_size.value:
                            info = SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX.from_buffer_copy(
                                buf.raw[offset : offset + ctypes.sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)]
                            )
                            if info.Relationship == RelationProcessorCore:
                                proc = info.Processor
                                eff = int(proc.EfficiencyClass)
                                mask = int(proc.GroupMask[0].Mask)
                                raw_cores.append((eff, mask))
                            if info.Size == 0:
                                break
                            offset += info.Size

                        if raw_cores:
                            eff_classes = set(c[0] for c in raw_cores)
                            if len(eff_classes) > 1:
                                is_hybrid = True
                                max_eff = max(eff_classes)
                                p_cores_list = [c for c in raw_cores if c[0] == max_eff]
                                e_cores_list = [c for c in raw_cores if c[0] < max_eff]
                                p_cores = len(p_cores_list)
                                e_cores = len(e_cores_list)

                                p_indices = []
                                for _, mask in p_cores_list:
                                    for bit in range(64):
                                        if (mask & (1 << bit)) and bit < logical_cores:
                                            p_indices.append(bit)
                                p_indices = sorted(list(set(p_indices)))

                                e_indices = []
                                for _, mask in e_cores_list:
                                    for bit in range(64):
                                        if (mask & (1 << bit)) and bit < logical_cores:
                                            e_indices.append(bit)
                                e_indices = sorted(list(set(e_indices)))
            except Exception:
                pass

        return is_hybrid, p_cores, e_cores, p_indices, e_indices

    @staticmethod
    def _detect_ram() -> tuple[float, float]:
        """Returns (total_gb, available_gb)."""
        # Try psutil first
        try:
            import psutil
            vm = psutil.virtual_memory()
            return vm.total / (1024**3), vm.available / (1024**3)
        except Exception:
            pass

        # Fallback on Windows via ctypes GlobalMemoryStatusEx
        if sys.platform == "win32":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                ms = MEMORYSTATUSEX()
                ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                    return (
                        ms.ullTotalPhys / (1024**3),
                        ms.ullAvailPhys / (1024**3),
                    )
            except Exception:
                pass

        return 8.0, 4.0  # Conservative safe fallback

    @staticmethod
    def _detect_gpu() -> tuple[str, Optional[int], str]:
        """Returns (gpu_name, vram_mb, vendor)."""
        name = "Unknown GPU"
        vram: Optional[int] = None
        vendor = "unknown"

        if sys.platform == "win32":
            # 1. Fast path: Direct Windows Registry query for Display Adapters (< 2ms)
            try:
                import winreg
                key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
                gpus = []
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(k, i)
                            i += 1
                            if subkey_name.isdigit():
                                with winreg.OpenKey(k, subkey_name) as subk:
                                    try:
                                        desc, _ = winreg.QueryValueEx(subk, "DriverDesc")
                                        mem = None
                                        for val_name in (
                                            "HardwareInformation.qwMemorySize",
                                            "HardwareInformation.MemorySize",
                                        ):
                                            try:
                                                m, _ = winreg.QueryValueEx(subk, val_name)
                                                if m and isinstance(m, int) and m > 0:
                                                    mem = m
                                                    break
                                            except Exception:
                                                pass
                                        if desc:
                                            gpus.append((str(desc).strip(), mem))
                                    except Exception:
                                        pass
                        except OSError:
                            break

                if gpus:
                    discrete = [
                        g for g in gpus
                        if any(k in g[0].lower() for k in ("nvidia", "geforce", "rtx", "gtx", "amd", "radeon"))
                    ]
                    primary = discrete[0] if discrete else gpus[0]
                    name = primary[0]
                    if primary[1] and isinstance(primary[1], int) and primary[1] > 0:
                        vram = primary[1] // (1024 * 1024)
            except Exception:
                pass

            # 2. Fallback: Query Win32_VideoController via PowerShell CIM if registry returned nothing
            if name == "Unknown GPU":
                try:
                    cmd = [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Get-CimInstance Win32_VideoController | Select-Object -Property Name, AdapterRAM | ConvertTo-Json",
                    ]
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=2.5,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if proc.returncode == 0 and proc.stdout.strip():
                        data = json.loads(proc.stdout)
                        items = data if isinstance(data, list) else [data]
                        gpus = []
                        for item in items:
                            gpu_item_name = item.get("Name")
                            if gpu_item_name:
                                gpus.append((gpu_item_name, item.get("AdapterRAM")))

                        if gpus:
                            discrete = [
                                g for g in gpus
                                if any(k in g[0].lower() for k in ("nvidia", "geforce", "rtx", "gtx", "amd", "radeon"))
                            ]
                            primary = discrete[0] if discrete else gpus[0]
                            name = primary[0]
                            if primary[1] and isinstance(primary[1], int) and primary[1] > 0:
                                vram = primary[1] // (1024 * 1024)
                except Exception:
                    pass

        # Determine vendor tag
        name_lower = name.lower()
        if any(k in name_lower for k in ("nvidia", "geforce")):
            vendor = "nvidia"
        elif any(k in name_lower for k in ("amd", "radeon")):
            vendor = "amd"
        elif "intel" in name_lower:
            vendor = "intel"

        return name, vram, vendor

    @staticmethod
    def _detect_os() -> tuple[str, str, str]:
        """Returns (os_name, os_version, os_arch)."""
        name = platform.system() or "Windows"
        version = platform.version() or "10.0"
        arch = platform.architecture()[0] or "64bit"
        return name, version, arch

    @staticmethod
    def _detect_python() -> tuple[str, str]:
        """Returns (python_version, python_arch)."""
        return platform.python_version(), platform.architecture()[0]

    @staticmethod
    def _detect_vlc(python_arch: str) -> tuple[Optional[str], Optional[str]]:
        """Returns (vlc_version, vlc_arch)."""
        try:
            import vlc
            ver_bytes = vlc.libvlc_get_version()
            if isinstance(ver_bytes, bytes):
                ver = ver_bytes.decode("utf-8", errors="ignore")
            else:
                ver = str(ver_bytes)
            # Typically VLC matches Python bitness if python-vlc succeeds
            return ver.split()[0], python_arch
        except Exception:
            return None, None

    # --- GUI & Formatting Helpers ---

    def to_display_dict(self) -> Dict[str, str]:
        """Format info nicely for GUI display in the Settings Panel."""
        freq_str = f" @ {self.cpu_freq_mhz / 1000:.1f}GHz" if self.cpu_freq_mhz > 0 else ""
        vlc_display = (
            f"{self.vlc_version} ({self.vlc_arch})"
            if self.vlc_version
            else "Chưa phát hiện (cần cài đặt VLC)"
        )
        if self.is_hybrid_cpu:
            cpu_detail = f"{self.cpu_name} ({self.cpu_cores_physical}C: {self.cpu_p_cores}P + {self.cpu_e_cores}E / {self.cpu_cores_logical}T{freq_str})"
        else:
            cpu_detail = f"{self.cpu_name} ({self.cpu_cores_physical}C/{self.cpu_cores_logical}T{freq_str})"

        return {
            "CPU": cpu_detail,
            "RAM": f"{self.ram_total_gb:.1f} GB ({self.ram_available_gb:.1f} GB khả dụng)",
            "GPU": self.gpu_name,
            "Hệ điều hành": f"{self.os_name} {self.os_version} ({self.os_arch})",
            "Python": f"{self.python_version} ({self.python_arch})",
            "VLC": vlc_display,
        }

    def format_copy_text(self) -> str:
        """Text format used when user clicks 'Copy thông tin'."""
        if self.is_hybrid_cpu:
            cpu_line = f"CPU:    {self.cpu_name} ({self.cpu_cores_physical}C: {self.cpu_p_cores}P + {self.cpu_e_cores}E / {self.cpu_cores_logical}T)"
        else:
            cpu_line = f"CPU:    {self.cpu_name} ({self.cpu_cores_physical}C/{self.cpu_cores_logical}T)"

        lines = [
            "FB Video Watcher - System Information",
            "=" * 38,
            cpu_line,
            f"RAM:    {self.ram_total_gb:.1f} GB ({self.ram_available_gb:.1f} GB available)",
            f"GPU:    {self.gpu_name} (Vendor: {self.gpu_vendor})",
            f"OS:     {self.os_name} {self.os_version} ({self.os_arch})",
            f"Python: {self.python_version} ({self.python_arch})",
            f"VLC:    {self.vlc_version or 'Not Installed'} ({self.vlc_arch or 'N/A'})",
        ]
        return "\n".join(lines)
