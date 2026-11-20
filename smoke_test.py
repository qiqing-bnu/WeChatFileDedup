"""只读冒烟测试：构造临时重复文件，验证扫描→哈希→分组→推荐逻辑。

不触碰回收站、不删除任何文件；结束后清理临时目录。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import hasher, scanner
from core.models import KEEP
from core.paths import Root

base = tempfile.mkdtemp(prefix="dedup_test_")
doc = os.path.join(base, "docs")
wx = os.path.join(base, "wx", "FileStorage", "File", "2026-11")
os.makedirs(doc)
os.makedirs(wx)

# 三个"完全相同"的文件（跨目录），一个不同内容同名文件，一个小文件
payload = os.urandom(300_000)
same2 = os.urandom(150_000)
cases = [
    (os.path.join(doc, "report.docx"), payload),
    (os.path.join(wx, "report.docx"), payload),
    (os.path.join(wx, "report (1).docx"), payload),
    (os.path.join(doc, "same2.zip"), same2),
    (os.path.join(wx, "same2.zip"), same2),
    (os.path.join(doc, "other.docx"), os.urandom(300_000) + b"x"),  # 大小相同但内容不同
    (os.path.join(doc, "tiny.txt"), b"ab"),                          # 小于最小阈值
]
for path, data in cases:
    with open(path, "wb") as f:
        f.write(data)

roots = [Root(doc, "我的文档"), Root(os.path.join(base, "wx"), "微信")]
files, skipped = scanner.scan(roots, {".docx", ".zip"}, 1024)
print(f"files={len(files)} skipped={skipped}")
assert len(files) == 6, files
assert skipped == 0

groups, locked = hasher.build_groups(files, {}, lambda d, t, p: None)
print(f"groups={len(groups)} locked={len(locked)}")
assert len(groups) == 2, [len(g.files) for g in groups]

for g in groups:
    name = g.files[0].file_name
    keeps = [f for f in g.files if f.decision == KEEP]
    assert len(keeps) == 1, name
    assert not keeps[0].from_wechat, f"推荐保留项应是文档侧: {name}"
    print(f"  组[{name}] {len(g.files)} 份, 保留: {keeps[0].full_path}")

# 大组应排在前面（可释放空间降序）
assert groups[0].files[0].file_name == "report.docx"

# 同大小不同内容不得成组
assert all(g.files[0].file_name != "other.docx" for g in groups)

# 缓存命中：第二次构建应复用哈希
cache = {}
for f in files:
    key = f"{f.full_path.lower()}|{f.size}|{f.mtime}"
    cache[key] = f.hash
g2, _ = hasher.build_groups(files, cache, lambda d, t, p: None)
assert len(g2) == 2

shutil.rmtree(base)
print("SMOKE TEST PASSED")
