"""清理器：把文件移入系统回收站（SHFileOperation），并支持从回收站还原。

还原原理：回收站内每个被删文件都有一个 $I 元数据文件（记录原始路径、
大小、删除时间）和一个 $R 数据文件。解析 $I 匹配后把 $R 移回原位。
"""

import ctypes
import os
import time
from ctypes import wintypes

FO_DELETE = 3
FOF_SILENT = 0x4
FOF_NOCONFIRMATION = 0x10
FOF_ALLOWUNDO = 0x40
FOF_NOERRORUI = 0x400


class SHFILEOPSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def recycle_delete(path: str) -> bool:
    """把单个文件移入回收站。返回是否成功。"""
    op = SHFILEOPSTRUCT()
    op.hwnd = None
    op.wFunc = FO_DELETE
    # 双空字符结尾（路径 + 一个 \0，c_wchar_p 自动补一个终止 \0）
    op.pFrom = path + "\0"
    op.pTo = None
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return ret == 0 and not op.fAnyOperationsAborted


def execute(items):
    """批量清理，返回 (成功列表, 失败列表)。"""
    ok, fail = [], []
    for it in items:
        if recycle_delete(it.full_path):
            ok.append(it)
        else:
            fail.append(it)
    return ok, fail


def _parse_ifile(path: str):
    """解析 $I 元数据文件，返回 (原始路径, 大小, 删除时间epoch) 或 None。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 24:
            return None
        version = int.from_bytes(data[0:8], "little")
        size = int.from_bytes(data[8:16], "little")
        ft = int.from_bytes(data[16:24], "little")
        epoch = ft / 10_000_000 - 11_644_473_600  # FILETIME → epoch 秒
        if version == 2 and len(data) >= 28:
            nlen = int.from_bytes(data[24:28], "little")
            raw = data[28:28 + nlen * 2]
        else:  # v1：固定 260 个 UTF-16 字符
            raw = data[24:24 + 520]
        name = raw.decode("utf-16-le", errors="ignore").split("\x00")[0]
        return name, size, epoch
    except (OSError, ValueError):
        return None


def _recycle_bins():
    """返回所有可访问的回收站目录。"""
    bins = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if not os.path.exists(drive):
            continue
        base = os.path.join(drive, "$Recycle.Bin")
        if os.path.isdir(base):
            bins.append(base)
    return bins


def restore(original_path: str, size: int, deleted_epoch: float):
    """从回收站还原文件。返回 (是否成功, 说明)。"""
    want = os.path.normcase(os.path.abspath(original_path))
    best = None  # (epoch, $R路径)
    for base in _recycle_bins():
        for sid in _safe_listdir(base):
            sid_dir = os.path.join(base, sid)
            for fn in _safe_listdir(sid_dir):
                if not fn.startswith("$I"):
                    continue
                parsed = _parse_ifile(os.path.join(sid_dir, fn))
                if parsed is None:
                    continue
                name, isz, iepoch = parsed
                if os.path.normcase(name) != want or isz != size:
                    continue
                if best is None or iepoch > best[0]:
                    rpath = os.path.join(sid_dir, "$R" + fn[2:])
                    best = (iepoch, rpath)
    if best is None:
        return False, "回收站中未找到对应记录"
    rpath = best[1]
    if not os.path.exists(rpath):
        return False, "回收站数据文件已不存在"
    target = original_path
    if os.path.exists(target):
        ts = time.strftime("%Y%m%d_%H%M%S")
        root, ext = os.path.splitext(original_path)
        target = f"{root}.恢复{ts}{ext}"
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        os.rename(rpath, target)
    except OSError as e:
        return False, f"还原失败：{e}"
    return True, target


def _safe_listdir(path: str):
    try:
        return os.listdir(path)
    except OSError:
        return []
