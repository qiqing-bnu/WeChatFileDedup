"""目录发现：自动探测微信接收文件目录与「我的文档」。

已核实的微信存储路径：
  3.x  %USERPROFILE%\\Documents\\WeChat Files\\<wxid>\\FileStorage\\File\\YYYY-MM\\
  4.x  %USERPROFILE%\\Documents\\xwechat_files\\<wxid>\\msg\\file\\YYYY-MM\\
用户若在微信「设置→文件管理」改过存储位置，可通过界面手动添加目录。
"""

import os
from dataclasses import dataclass

WECHAT_DIR_NAMES = ("WeChat Files", "xwechat_files")

# 扫描时永远跳过的系统目录
ALWAYS_EXCLUDE = {"$RECYCLE.BIN", "System Volume Information", "AppData"}

DEFAULT_EXTS = [
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".pdf", ".rtf", ".txt",
    ".zip", ".rar", ".7z", ".tar", ".gz",
]


@dataclass
class Root:
    path: str
    label: str  # 我的文档 / 微信 / 自定义


def documents_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents")


def is_wechat_path(path: str) -> bool:
    low = path.lower()
    return "\\wechat files\\" in low or "\\xwechat_files\\" in low


def detect_roots() -> list:
    """返回候选扫描根目录列表。"""
    roots: list = []
    seen: set = set()

    docs = documents_dir()
    if os.path.isdir(docs):
        roots.append(Root(docs, "我的文档"))
        seen.add(os.path.normcase(docs))

    for name in WECHAT_DIR_NAMES:
        base = os.path.join(docs, name)
        if not os.path.isdir(base):
            continue
        for acct in os.listdir(base):
            acct_dir = os.path.join(base, acct)
            if not os.path.isdir(acct_dir):
                continue
            # 3.x 与 4.x 的接收文件目录都尝试一次
            for marker in ("FileStorage\\File", "msg\\file"):
                p = os.path.join(acct_dir, marker)
                if os.path.isdir(p) and os.path.normcase(p) not in seen:
                    roots.append(Root(p, "微信"))
                    seen.add(os.path.normcase(p))
                    break
    return roots
