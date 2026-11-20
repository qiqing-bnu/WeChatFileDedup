"""扫描器：递归枚举文件（全程只读，不改动任何文件）。"""

import os
import threading

from .models import FileItem
from .paths import ALWAYS_EXCLUDE, WECHAT_DIR_NAMES, is_wechat_path

# Windows 文件属性
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def scan(roots, exts, min_size, progress=None, cancel: threading.Event | None = None):
    """遍历所有启用的根目录，返回 (files, skipped_count)。

    roots: [Root]；exts: {'.docx', ...}，空集合表示不过滤；min_size: 字节。
    progress(done_count) 每 50 个文件回调一次（须由调用方保证线程安全）。
    """
    files: list = []
    skipped = 0
    done = 0

    for root in roots:
        exclude_wechat = root.label == "我的文档"
        for dirpath, dirnames, filenames in os.walk(root.path, topdown=True):
            if cancel is not None and cancel.is_set():
                return files, skipped
            dirnames[:] = [
                d for d in dirnames
                if d not in ALWAYS_EXCLUDE
                and not (exclude_wechat and d in WECHAT_DIR_NAMES)
            ]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if exts and ext not in exts:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    skipped += 1
                    continue
                attrs = getattr(st, "st_file_attributes", 0)
                if attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                    continue
                if st.st_size < min_size:
                    continue
                files.append(FileItem(
                    full_path=full,
                    file_name=fn,
                    size=st.st_size,
                    mtime=st.st_mtime,
                    source=root.label,
                    from_wechat=is_wechat_path(full),
                ))
                done += 1
                if progress is not None and done % 50 == 0:
                    progress(done)

    return files, skipped
