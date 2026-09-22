# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = [
    ('main/image', 'main/image'),
    ('main/bin', 'main/bin'),
    ('docs', 'docs'),
    ('main/docs', 'main/docs'),
]
datas += collect_data_files('sv_ttk')
datas += collect_data_files('yt_dlp')
datas += collect_data_files('yt_dlp_ejs')
datas += collect_data_files('telethon')

hiddenimports = [
    'vlc',
    'psutil',
    'sqlite3',
    'win32gui',
    'win32con',
    'sv_ttk',
    'yt_dlp',
    'yt_dlp_ejs',
    'telethon',
    'qrcode',
    'cryptg',
]
hiddenimports += collect_submodules('yt_dlp')
hiddenimports += collect_submodules('yt_dlp_ejs')
hiddenimports += collect_submodules('telethon')
hiddenimports += collect_submodules('qrcode')
hiddenimports += collect_submodules('main')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter.test', 'unittest.test'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

import re
from pathlib import Path

# Extract version dynamically from main/__init__.py
version_str = "1.0.0"
init_file = Path("main/__init__.py")
if init_file.exists():
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_file.read_text(encoding="utf-8"))
    if match:
        version_str = match.group(1)

ver_parts = [int(p) for p in re.findall(r'\d+', version_str)]
while len(ver_parts) < 4:
    ver_parts.append(0)
ver_tuple = tuple(ver_parts[:4])

version_info_content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple},
    prodvers={ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'P A U L / JustFun'),
        StringStruct('FileDescription', 'FB Video Watcher'),
        StringStruct('FileVersion', '{version_str}'),
        StringStruct('InternalName', 'FB-Video-Watcher'),
        StringStruct('LegalCopyright', '© 2026 P A U L / JustFun. All rights reserved.'),
        StringStruct('LegalTrademarks', 'Freeware (Miễn phí cho mục đích cá nhân)'),
        StringStruct('Comments', 'Discord: https://discord.gg/9gM5FAXDrC | GitHub: https://github.com/Olinere/fb-video-watching'),
        StringStruct('OriginalFilename', 'FB-Video-Watcher.exe'),
        StringStruct('ProductName', 'FB Video Watcher'),
        StringStruct('ProductVersion', '{version_str}')])
      ]), 
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

version_file_path = "version_info.txt"
with open(version_file_path, "w", encoding="utf-8") as vf:
    vf.write(version_info_content)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FB-Video-Watcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='main/image/app_icon.ico',
    version=version_file_path,
)

