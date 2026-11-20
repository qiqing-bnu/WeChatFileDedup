<div align="center">

# WeChatFileDedup · 微信文件去重助手

**扫描微信接收目录与「我的文档」，按内容哈希找出重复文件，双栏确认后安全清理进回收站。**

![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![Runtime deps](https://img.shields.io/badge/runtime%20deps-0-brightgreen)

</div>

---

扫描微信接收文件的目录与「我的文档」，通过哈希算法找出**内容完全一致**的重复文件，
在图形界面中分「我的文档 / 微信」双栏对照，由你决定保留哪一份后，
把其余副本安全移入系统回收站（可一键撤销）。

## 特性

- **内容哈希判定**：三级漏斗（按文件大小分组 → 首尾采样哈希 → 完整 SHA-256 流式哈希），
  文件名不参与判定——同名不同内容不误删，异名同内容能找出。
- **双栏确认界面**：左侧「我的文档 / 自定义」、右侧「微信」，逐组逐份选择保留哪一侧；
  默认推荐保留文档侧最新一份，全部可手动调整。
- **状态一目了然**：每个文件带彩色「保留 / 清理」徽章与行底色；点击行即选中，
  底部预览窗格显示元信息与内容预览（docx/pptx/xlsx 正文、txt/rtf、压缩包条目）。
- **安全清理**：扫描全程只读；清理前强制试运行预览 + 二次确认；删除只进回收站；
  清理记录可一键撤销（自动从回收站还原到原位置）。
- **增量缓存**：哈希结果按 (路径, 大小, 修改时间) 缓存，二次扫描明显加速。
- **自动探测微信目录**：兼容微信 3.x（`WeChat Files\<wxid>\FileStorage\File`）与
  4.x（`xwechat_files\<wxid>\msg\file`）；存储位置改过可用界面手动添加。
- **多账号支持**：每个登录过的账号目录都会列出，可分别勾选。
- **Win11 Fluent 界面**：内嵌 [sv-ttk](https://github.com/rdbende/Sun-Valley-ttk-theme)（MIT）主题，随源码分发。
- **CSV 报告导出**：重复组、判定、路径、大小、哈希一览。

## 快速开始

### 方式一：打包 exe（推荐普通用户）

```bat
git clone https://github.com/qiqing-bnu/WeChatFileDedup.git
cd WeChatFileDedup
build_exe.bat        :: 需要 Python 3.10+ 与 PyInstaller，产物在 dist\
```

### 方式二：直接运行源码

- Windows 10/11，Python 3.10+（需自带 tkinter，官方 python.org 安装包默认包含）
- 无需 `pip install` 任何运行时依赖

```bat
start_app.vbs        :: 无控制台窗口启动
:: 或
pythonw main.py
```

## 工作原理

1. **枚举**：只读遍历勾选目录，按扩展名（doc/docx/xls/xlsx/ppt/pptx/pdf/rtf/txt/zip/rar/7z/tar/gz）与最小文件大小过滤；
2. **粗筛**：相同文件大小归组；
3. **采样**：首尾各 64 KB 哈希一致的候选进入下一级；
4. **确认**：完整 SHA-256 流式哈希一致 → 判定为重复；
5. **决策**：双栏界面逐组选择保留侧 → 试运行预览 → 二次确认 → 移入回收站。

## 项目结构

```
WeChatFileDedup/
├── main.py            # 程序入口
├── app.py             # 主窗口 GUI（tkinter / ttk）
├── core/
│   ├── models.py      # FileItem / DupGroup 数据模型
│   ├── paths.py       # 微信目录探测与扫描根管理
│   ├── scanner.py     # 只读文件枚举
│   ├── hasher.py      # 三级哈希漏斗与分组
│   ├── cleaner.py     # 回收站清理与还原（Win32 SHFileOperation / $I/$R 解析）
│   └── store.py       # 设置 / 缓存 / 操作日志（%APPDATA% 下的 JSON）
├── sv_ttk/            # 内嵌的 Win11 Fluent 主题（MIT）
├── smoke_test.py      # 核心逻辑冒烟测试（只读）
├── build_exe.bat      # 一键打包 exe
└── start_app.vbs      # 无控制台启动脚本
```

## 安全设计

| 约束 | 实现 |
|---|---|
| 扫描只读 | 扫描阶段不写入、不移动任何文件 |
| 清理可预览 | 「试运行预览」列出全部待清理路径 |
| 删除可恢复 | 只调用系统回收站，绝不永久删除；支持从回收站自动还原 |
| 执行需确认 | 清理前弹窗列出份数与释放空间，需显式确认 |
| 不碰聊天记录 | 只处理用户勾选目录内的普通文件 |

## 已知边界

- 按字节哈希判定：正文相同但保存时间/作者不同的 Word/PDF 不会被识别（宁可漏报不误删）。
  「内容指纹」（剔除元数据后哈希）在规划中，见 Roadmap。
- 图片/视频多为加密 `.dat`，不在处理范围。
- 被微信占用的文件会跳过并在结果中提示，建议关闭微信后重扫。
- 微信 4.x 升级可能使用硬链接迁移旧数据，删除后实际释放的空间以磁盘剩余量为准。

## Roadmap

- [ ] 内容指纹：识别「正文相同但元数据不同」的文档（分档标注，不与完全一致混列）
- [ ] 扫描目录白名单
- [ ] 相似图片检测与硬链接合并模式
- [ ] 国际化（当前仅简体中文界面）

## 测试

```bat
python smoke_test.py
```

冒烟测试覆盖扫描 → 哈希 → 分组 → 推荐方案全链路（在临时目录中运行，只读，不触碰真实文件）。

## 贡献

欢迎 Issue 与 PR。提交前请运行 `python smoke_test.py` 确保通过。

## License

[MIT](LICENSE)
