"""哈希去重引擎：三级漏斗（L1 按大小 → L2 部分哈希 → L3 完整 SHA-256）。

文件名不参与重复判定；判定结果只含"内容完全一致"的组。
带 (路径, 大小, 修改时间) 键的哈希缓存，未变更文件复用上次结果。
"""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

from .models import DupGroup

SAMPLE = 64 * 1024      # L2 采样大小
CHUNK = 1024 * 1024     # L3 分块大小


def _partial_hash(path: str, size: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(min(size, SAMPLE)))
        if size > 2 * SAMPLE:
            f.seek(-SAMPLE, 2)
            h.update(f.read(SAMPLE))
    return h.hexdigest()


def _full_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def build_groups(files, cache: dict, progress=None,
                 cancel: threading.Event | None = None, max_workers: int = 4):
    """返回 (groups, locked_paths)。progress(done, total, phase)。"""
    locked: list = []
    lock = threading.Lock()

    # L1：按大小分组
    by_size: dict = {}
    for f in files:
        by_size.setdefault(f.size, []).append(f)
    candidates = [f for g in by_size.values() if len(g) > 1 for f in g]
    total = len(candidates)
    done = 0

    def tick(phase):
        nonlocal done
        with lock:
            done += 1
            if progress is not None:
                progress(done, total, phase)

    # L2：部分哈希
    def partial_one(f):
        if cancel is not None and cancel.is_set():
            return
        try:
            f.hash = _partial_hash(f.full_path, f.size)
        except OSError:
            with lock:
                locked.append(f.full_path)
        tick("快速比对")

    if candidates:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(partial_one, candidates))
    if cancel is not None and cancel.is_set():
        return [], locked

    by_partial: dict = {}
    for f in candidates:
        if f.hash:
            by_partial.setdefault((f.size, f.hash), []).append(f)
    need_full = [f for g in by_partial.values() if len(g) > 1 for f in g]

    # L3：完整哈希（带缓存）
    done = 0
    total = len(need_full)

    def full_one(f):
        nonlocal done
        if cancel is not None and cancel.is_set():
            return
        key = f"{f.full_path.lower()}|{f.size}|{f.mtime}"
        if key in cache:
            f.hash = cache[key]
        else:
            try:
                f.hash = _full_hash(f.full_path)
                cache[key] = f.hash
            except OSError:
                with lock:
                    locked.append(f.full_path)
                return
        tick("完整哈希")

    if need_full:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(full_one, need_full))
    if cancel is not None and cancel.is_set():
        return [], locked

    by_hash: dict = {}
    for f in candidates:
        if f.hash:
            by_hash.setdefault(f.hash, []).append(f)

    groups: list = []
    for g in by_hash.values():
        if len(g) > 1:
            grp = DupGroup(files=g)
            grp.recommend()
            groups.append(grp)
    groups.sort(key=lambda g: -(len(g.files) - 1) * g.files[0].size)
    return groups, locked
