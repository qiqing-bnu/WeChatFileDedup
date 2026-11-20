"""本地存储：设置、哈希缓存、清理日志（JSON），以及 CSV 报告导出。"""

import csv
import json
import os
import time

from .models import KEEP, format_size
from .paths import DEFAULT_EXTS

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WeChatFileDedup")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
CACHE_FILE = os.path.join(APP_DIR, "hash_cache.json")
OPLOG_FILE = os.path.join(APP_DIR, "operations.json")

MAX_BATCHES = 50


def _load(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# ---------- 设置 ----------

def default_settings() -> dict:
    return {"roots": [], "min_size_kb": 4, "exts": list(DEFAULT_EXTS)}


def load_settings() -> dict:
    s = _load(SETTINGS_FILE, None)
    if not isinstance(s, dict):
        s = default_settings()
    s.setdefault("roots", [])
    s.setdefault("min_size_kb", 4)
    s.setdefault("exts", list(DEFAULT_EXTS))
    return s


def save_settings(s: dict) -> None:
    _save(SETTINGS_FILE, s)


# ---------- 哈希缓存 ----------

def load_cache() -> dict:
    c = _load(CACHE_FILE, {})
    return c if isinstance(c, dict) else {}


def save_cache(cache: dict) -> None:
    # 控制体积：超出 20 万条时整体重建（简单截断）
    if len(cache) > 200_000:
        cache = dict(list(cache.items())[-100_000:])
    _save(CACHE_FILE, cache)


# ---------- 清理日志 ----------

class OpLog:
    def __init__(self, batches=None):
        self.batches: list = batches or []

    @classmethod
    def load(cls) -> "OpLog":
        data = _load(OPLOG_FILE, [])
        return cls(data if isinstance(data, list) else [])

    def save(self) -> None:
        if len(self.batches) > MAX_BATCHES:
            self.batches = self.batches[-MAX_BATCHES:]
        _save(OPLOG_FILE, self.batches)

    def add_batch(self, entries: list) -> None:
        self.batches.append({"time": time.time(), "entries": entries})
        self.save()

    def last_batch(self):
        for b in reversed(self.batches):
            if b.get("entries"):
                return b
        return None

    def drop_entries(self, batch: dict, paths_done: set) -> None:
        batch["entries"] = [e for e in batch["entries"] if e["path"] not in paths_done]
        if not batch["entries"]:
            self.batches = [b for b in self.batches if b is not batch]
        self.save()


# ---------- CSV 报告 ----------

def export_csv(path: str, groups) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["组", "判定", "来源", "文件名", "完整路径", "大小", "大小字节", "修改时间", "SHA256前16位"])
        for i, g in enumerate(groups, 1):
            for item in g.files:
                w.writerow([
                    i,
                    "保留" if item.decision == KEEP else "清理",
                    item.source,
                    item.file_name,
                    item.full_path,
                    format_size(item.size),
                    item.size,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.mtime)),
                    item.hash[:16],
                ])
