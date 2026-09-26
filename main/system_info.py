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
import re
import subprocess
import sys
from typing import Optional, Dict, Any, List


@dataclass
class GPUInfo:
    """Represents a physical or virtual graphics adapter with operational status."""
    name: str
    vram_mb: Optional[int] = None
    vendor: str = "unknown"  # "nvidia" | "amd" | "intel" | "unknown"
    is_integrated: bool = False
    is_active: bool = True
    adapter_index: Optional[int] = None


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

    # --- Multi-GPU & Topology ---
    gpu_topology: str = "unknown"           # "hybrid_dual_gpu" | "single_discrete" | "single_integrated" | "unknown"
    discrete_gpu_name: Optional[str] = None
    integrated_gpu_name: Optional[str] = None
    igpu_adapter_index: Optional[int] = None
    cpu_has_igpu: bool = True
    gpus: List[GPUInfo] = field(default_factory=list)

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
        gpu_data = cls._detect_gpu(cpu_name=cpu_name)
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
            gpu_name=gpu_data["primary_name"],
            gpu_vram_mb=gpu_data["primary_vram"],
            gpu_vendor=gpu_data["primary_vendor"],
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
            gpu_topology=gpu_data["topology"],
            discrete_gpu_name=gpu_data["discrete_name"],
            integrated_gpu_name=gpu_data["integrated_name"],
            igpu_adapter_index=gpu_data["igpu_adapter_index"],
            cpu_has_igpu=gpu_data["cpu_has_igpu"],
            gpus=gpu_data["gpus"],
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
    def _detect_cpu_igpu_capability(cpu_name: str) -> bool:
        """
        Check if the CPU physically includes an integrated GPU.
        Returns False for:
        - Intel F / KF series (e.g. i5-12400F, i7-13700F, i9-14900KF, i3-10100F).
        - AMD Ryzen AM4 non-G desktop models (e.g. Ryzen 5 3600, 5600X, 5800X, 5900X).
        - AMD Ryzen 7500F (AM5 F-series without iGPU).
        - Intel Xeon / AMD Threadripper.
        """
        if not cpu_name or cpu_name == "Unknown CPU":
            return True
        name = cpu_name.lower()
        if re.search(r'\bi[3579]-\d{4,5}[kK]?[fF]\b', name) or re.search(r'\b\d{4,5}[kK]?[fF]\b', name):
            return False
        if re.search(r'ryzen\s+[3579]\s+\d{4,5}[fF]\b', name):
            return False
        if "ryzen" in name and not any(k in name for k in ("g", "ge", "mobile", "with radeon")):
            m = re.search(r'ryzen\s+[3579]\s+([1-5]\d{3})', name)
            if m:
                return False
        if any(w in name for w in ("xeon", "threadripper", "epyc")):
            return False
        return True

    @staticmethod
    def _query_active_dxgi_adapters() -> List[tuple[str, int, int]]:
        """
        Query currently active DirectX 11 / DXGI hardware adapters.
        Returns list of (description, vendor_id, dedicated_vram_bytes).
        Takes < 5ms via windll.dxgi.
        """
        if sys.platform != "win32":
            return []
        try:
            import ctypes
            from ctypes import wintypes

            class DXGI_ADAPTER_DESC1(ctypes.Structure):
                _fields_ = [
                    ('Description', wintypes.WCHAR * 128),
                    ('VendorId', wintypes.UINT),
                    ('DeviceId', wintypes.UINT),
                    ('SubSysId', wintypes.UINT),
                    ('Revision', wintypes.UINT),
                    ('DedicatedVideoMemory', ctypes.c_size_t),
                    ('DedicatedSystemMemory', ctypes.c_size_t),
                    ('SharedSystemMemory', ctypes.c_size_t),
                    ('AdapterLuidLowPart', wintypes.DWORD),
                    ('AdapterLuidHighPart', wintypes.LONG),
                    ('Flags', wintypes.UINT),
                ]

            class GUID(ctypes.Structure):
                _fields_ = [
                    ('Data1', wintypes.DWORD),
                    ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD),
                    ('Data4', wintypes.BYTE * 8),
                ]

            dxgi = ctypes.windll.dxgi
            factory = ctypes.c_void_p()
            iid = GUID(0x770aae78, 0xf26f, 0x4dba, (wintypes.BYTE * 8)(0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87))
            hr = dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory))
            if hr != 0 or not factory:
                return []

            vtbl = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
            EnumAdapters1_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
            EnumAdapters1 = EnumAdapters1_proto(vtbl[12])

            GetDesc1_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1))
            Release_proto = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)

            results = []
            idx = 0
            while True:
                adapter = ctypes.c_void_p()
                hr = EnumAdapters1(factory, idx, ctypes.byref(adapter))
                if hr != 0 or not adapter:
                    break
                adapter_vtbl = ctypes.cast(ctypes.cast(adapter, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
                GetDesc1 = GetDesc1_proto(adapter_vtbl[10])
                desc = DXGI_ADAPTER_DESC1()
                GetDesc1(adapter, ctypes.byref(desc))
                Release_proto(adapter_vtbl[2])(adapter)

                # Skip software renderers (DXGI_ADAPTER_FLAG_SOFTWARE = 2)
                if not (desc.Flags & 2):
                    results.append((str(desc.Description), int(desc.VendorId), int(desc.DedicatedVideoMemory)))
                idx += 1

            Release_proto(vtbl[2])(factory)
            return results
        except Exception:
            return []

    @staticmethod
    def _is_integrated_gpu_name(name: str) -> bool:
        """Classify whether a graphics adapter name belongs to an integrated GPU (iGPU)."""
        name_lower = name.lower()
        if "intel" in name_lower:
            if any(k in name_lower for k in ("arc", "iris xe max", "dg1", "discrete")):
                return False
            return True

        if any(k in name_lower for k in ("amd", "radeon")):
            if any(k in name_lower for k in ("rx ", "rx-", "radeon vii", "r9 ", "r7 ", "firepro", "radeon pro")):
                return False
            if any(k in name_lower for k in ("graphics", "vega", "integrated", "processor")):
                return True

        return False

    @staticmethod
    def _detect_vendor_from_name(name: str) -> str:
        """Extract vendor key from graphics adapter name."""
        name_lower = name.lower()
        if any(k in name_lower for k in ("nvidia", "geforce", "quadro", "rtx", "gtx")):
            return "nvidia"
        elif any(k in name_lower for k in ("amd", "radeon")):
            return "amd"
        elif "intel" in name_lower:
            return "intel"
        return "unknown"

    @classmethod
    def _detect_gpu(cls, cpu_name: str = "") -> Dict[str, Any]:
        """
        Detect all graphics hardware adapters, active DXGI status, and Multi-GPU topology.
        Returns dict containing primary info, topology, and detailed GPUInfo instances.
        """
        raw_gpus: List[tuple[str, Optional[int]]] = []

        if sys.platform == "win32":
            # 1. Fast path: Direct Windows Registry query for Display Adapters (< 2ms)
            try:
                import winreg
                key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
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
                                            raw_gpus.append((str(desc).strip(), mem))
                                    except Exception:
                                        pass
                        except OSError:
                            break
            except Exception:
                pass

            # 2. Fallback: Query Win32_VideoController via PowerShell CIM if registry was empty
            if not raw_gpus:
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
                        for item in items:
                            gpu_item_name = item.get("Name")
                            if gpu_item_name:
                                raw_gpus.append((gpu_item_name, item.get("AdapterRAM")))
                except Exception:
                    pass

        # Query currently active hardware adapters from DirectX DXGI
        active_dxgi = cls._query_active_dxgi_adapters()

        # Parse and classify into GPUInfo objects
        cpu_has_igpu = cls._detect_cpu_igpu_capability(cpu_name)
        gpus: List[GPUInfo] = []
        seen_names = set()

        for g_name, g_mem in raw_gpus:
            # Filter out virtual/remote display mirrors
            if any(v in g_name.lower() for v in ("spacedesk", "parsec", "rdp", "citrix", "virtualbox", "vmware")):
                continue
            if g_name in seen_names:
                continue
            seen_names.add(g_name)

            vram_mb = (g_mem // (1024 * 1024)) if (g_mem and isinstance(g_mem, int) and g_mem > 0) else None
            vendor = cls._detect_vendor_from_name(g_name)
            is_integrated = cls._is_integrated_gpu_name(g_name)

            # Check if active in DXGI
            is_active = True
            adapter_index = None
            if active_dxgi:
                is_active = False
                for dxgi_idx, (dxgi_desc, dxgi_ven, dxgi_vram) in enumerate(active_dxgi):
                    if g_name.lower() in dxgi_desc.lower() or dxgi_desc.lower() in g_name.lower():
                        is_active = True
                        adapter_index = dxgi_idx
                        if not vram_mb and dxgi_vram > 0:
                            vram_mb = dxgi_vram // (1024 * 1024)
                        break

            gpus.append(GPUInfo(
                name=g_name,
                vram_mb=vram_mb,
                vendor=vendor,
                is_integrated=is_integrated,
                is_active=is_active,
                adapter_index=adapter_index,
            ))

        # Classify active vs disabled GPUs
        active_discrete = [g for g in gpus if not g.is_integrated and g.is_active]
        active_integrated = [g for g in gpus if g.is_integrated and g.is_active]
        disabled_integrated = [g for g in gpus if g.is_integrated and not g.is_active]

        topology = "unknown"
        igpu_adapter_idx = None
        discrete_name = None
        integrated_name = None

        if active_discrete:
            discrete_name = active_discrete[0].name

        if active_integrated:
            integrated_name = active_integrated[0].name
            igpu_adapter_idx = active_integrated[0].adapter_index
        elif disabled_integrated:
            integrated_name = f"{disabled_integrated[0].name} (Đã tắt trong Windows/BIOS)"

        if active_discrete and active_integrated and cpu_has_igpu:
            topology = "hybrid_dual_gpu"
        elif active_discrete:
            topology = "single_discrete"
        elif active_integrated:
            topology = "single_integrated"
        elif gpus:
            topology = "single_discrete" if not gpus[0].is_integrated else "single_integrated"

        # Primary GPU representation
        primary = active_discrete[0] if active_discrete else (active_integrated[0] if active_integrated else (gpus[0] if gpus else None))
        primary_name = primary.name if primary else "Unknown GPU"
        primary_vram = primary.vram_mb if primary else None
        primary_vendor = primary.vendor if primary else "unknown"

        return {
            "primary_name": primary_name,
            "primary_vram": primary_vram,
            "primary_vendor": primary_vendor,
            "topology": topology,
            "discrete_name": discrete_name,
            "integrated_name": integrated_name,
            "igpu_adapter_index": igpu_adapter_idx,
            "cpu_has_igpu": cpu_has_igpu,
            "gpus": gpus,
        }

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

        if self.gpu_topology == "hybrid_dual_gpu":
            gpu_display = f"Hybrid: {self.discrete_gpu_name} (dGPU) + {self.integrated_gpu_name} (iGPU)"
        elif self.integrated_gpu_name and "Đã tắt" in self.integrated_gpu_name:
            gpu_display = f"{self.gpu_name} [{self.integrated_gpu_name}]"
        else:
            gpu_display = self.gpu_name

        return {
            "CPU": cpu_detail,
            "RAM": f"{self.ram_total_gb:.1f} GB ({self.ram_available_gb:.1f} GB khả dụng)",
            "GPU": gpu_display,
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
            f"GPU:    {self.gpu_name} (Vendor: {self.gpu_vendor}, Topology: {self.gpu_topology})",
        ]
        if self.discrete_gpu_name:
            lines.append(f"dGPU:   {self.discrete_gpu_name}")
        if self.integrated_gpu_name:
            lines.append(f"iGPU:   {self.integrated_gpu_name}")
        lines.extend([
            f"OS:     {self.os_name} {self.os_version} ({self.os_arch})",
            f"Python: {self.python_version} ({self.python_arch})",
            f"VLC:    {self.vlc_version or 'Not Installed'} ({self.vlc_arch or 'N/A'})",
        ])
        return "\n".join(lines)
