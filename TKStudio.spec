# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TK Studio V1.6.4.

入口: TK_Studio_V1_6_4.py
目标: 单文件 onedir 模式（启动更快，避免单文件解压延迟）
"""
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 收集所有隐式导入的子模块
hiddenimports = []
hiddenimports += collect_submodules('core')
hiddenimports += collect_submodules('workers')
hiddenimports += ['PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui']
hiddenimports += ['requests', 'urllib3', 'websocket']

a = Analysis(
    ['TK_Studio_V1_6_4.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TKStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 程序，不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TKStudio',
)
