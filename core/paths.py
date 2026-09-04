"""应用数据路径解析（开发环境与 PyInstaller EXE 环境统一适配）。

FIX-EXE.1：解决 EXE 部署到 Program Files 时 _internal/ 目录只读导致
DB 写入失败、Chrome profile 创建失败的问题。

策略：
- 开发环境（python TK_Studio_V1_6_4.py）：返回项目根目录，
  与历史行为完全一致（向后兼容）。
- EXE 环境（sys.frozen）：返回 %LOCALAPPDATA%\\TK_Studio，
  该目录用户可写、不受 UAC 限制、跨重启持久化。

所有可写数据（SQLite DB、Chrome profile 目录、快照元数据）统一使用
get_app_data_root() 作为基目录，确保 EXE 环境下全部可写。
"""
import os
import sys


def get_app_data_root():
    """用户可写数据根目录。

    返回:
        str: 数据根目录绝对路径。

    开发模式:
        项目根目录（core/ 的上一级），与历史行为一致。
    EXE 模式 (sys.frozen):
        %LOCALAPPDATA%\\TK_Studio，自动创建。
        避免写入 PyInstaller _internal/ 目录（Program Files 部署时只读）。
    """
    if getattr(sys, 'frozen', False):
        base = os.path.expandvars(r"%LOCALAPPDATA%\TK_Studio")
        os.makedirs(base, exist_ok=True)
        return base
    # 开发模式：项目根目录 = core/ 的上一级
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
