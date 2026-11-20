"""数据模型：文件记录、重复组。"""

from dataclasses import dataclass, field

KEEP = "keep"
CLEAN = "clean"


def format_size(num: float) -> str:
    if num >= 1024 * 1024:
        return f"{num / 1024 / 1024:.1f} MB"
    if num >= 1024:
        return f"{num / 1024:.1f} KB"
    return f"{int(num)} B"


@dataclass(eq=False)  # eq=False：保留默认按身份的 __hash__，FileItem 需作字典键（界面状态映射）
class FileItem:
    """单个被扫描到的文件。"""

    full_path: str
    file_name: str
    size: int
    mtime: float          # 修改时间 (epoch 秒)
    source: str           # 来源标签：我的文档 / 微信 / 自定义
    from_wechat: bool
    hash: str = ""        # L3 完整哈希（内容一致判定依据）
    decision: str = CLEAN  # keep=保留 / clean=清理

    @property
    def info_text(self) -> str:
        import datetime
        t = datetime.datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M")
        return f"{format_size(self.size)} · {t} · {self.source}"


@dataclass
class DupGroup:
    """一组内容完全一致的文件。"""

    files: list = field(default_factory=list)

    @property
    def clean_count(self) -> int:
        return sum(1 for f in self.files if f.decision == CLEAN)

    @property
    def reclaim(self) -> int:
        return sum(f.size for f in self.files if f.decision == CLEAN)

    def recommend(self) -> None:
        """推荐保留策略：优先保留「我的文档/自定义」里最新的一份；否则保留最新一份。"""
        keep = None
        local = [f for f in self.files if not f.from_wechat]
        if local:
            keep = max(local, key=lambda f: f.mtime)
        if keep is None:
            keep = max(self.files, key=lambda f: f.mtime)
        for f in self.files:
            f.decision = KEEP if f is keep else CLEAN
