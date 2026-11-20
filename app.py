"""主窗口 GUI（tkinter / ttk，全程图形界面，无控制台交互）。"""

import html
import os
import queue
import re
import subprocess
import tarfile
import threading
import tkinter as tk
import zipfile
from tkinter import filedialog, messagebox, ttk

import sv_ttk

from core import cleaner, hasher, scanner, store
from core.models import CLEAN, KEEP, format_size
from core.paths import DEFAULT_EXTS, Root, detect_roots

# Win11 Fluent 配色
ACCENT = "#005FB8"          # 系统强调色（选中高亮）
GREEN = "#0F7B0F"           # 保留 / 成功
RED = "#C42B1C"             # 清理 / 危险
GRAY = "#5D5D5D"
BORDER = "#DFDFDF"          # 常规行边框
ROW_KEEP_BG = "#F3FAEE"     # 保留行底色
ROW_CLEAN_BG = "#FEF4F4"    # 清理行底色
BADGE_KEEP_BG, BADGE_KEEP_FG = "#DFF6DD", "#0F7B0F"
BADGE_CLEAN_BG, BADGE_CLEAN_FG = "#FDE7E9", "#C42B1C"


class ScrollFrame(ttk.Frame):
    """带垂直滚动条的内容容器。"""

    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, event):
        if isinstance(getattr(event, "widget", None), tk.Text):
            return  # 预览窗格的文本框自己滚动
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()


class DedupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("微信文件去重助手")
        self.geometry("1040x720")
        self.minsize(880, 600)

        self.settings = store.load_settings()
        self.cache = store.load_cache()
        self.oplog = store.OpLog.load()

        self.groups: list = []
        self._refs: dict = {}   # FileItem -> 状态 Label
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._q: queue.Queue = queue.Queue()
        self._root_vars: list = []   # (Root, BooleanVar)
        self._ext_vars: dict = {}

        # Win11 Fluent 主题（sv-ttk，随项目内嵌，不依赖外部安装）
        try:
            sv_ttk.set_theme("light")
        except tk.TclError:
            style = ttk.Style(self)
            for theme in ("vista", "xpnative", "clam"):
                if theme in style.theme_names():
                    style.theme_use(theme)
                    break
        style = ttk.Style(self)
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 9, "bold"))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self._build_scan_tab()
        self._build_result_tab()
        self._build_log_tab()

        status = ttk.Label(self, text="扫描只读 · 清理进回收站 · 可撤销",
                           foreground=GRAY)
        status.pack(fill="x", padx=12, pady=(0, 6))
        self.refresh_roots()
        self.refresh_log()

    # ---------- Tab 1：扫描 ----------

    def _build_scan_tab(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text=" ① 扫描 ")

        lf = ttk.LabelFrame(tab, text=" 扫描目录（勾选启用） ", padding=8)
        lf.pack(fill="x")
        self.roots_frame = ttk.Frame(lf)
        self.roots_frame.pack(fill="x")

        btns = ttk.Frame(lf)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="重新探测目录", command=self.on_detect).pack(side="left")
        ttk.Button(btns, text="添加文件夹…", command=self.on_add_folder).pack(side="left", padx=6)
        ttk.Button(btns, text="移除所选", command=self.on_remove_root).pack(side="left")

        sf = ttk.LabelFrame(tab, text=" 扫描设置 ", padding=8)
        sf.pack(fill="x", pady=8)
        row = ttk.Frame(sf)
        row.pack(fill="x")
        ttk.Label(row, text="最小文件大小 (KB)：").pack(side="left")
        self.min_size_var = tk.StringVar(value=str(self.settings.get("min_size_kb", 4)))
        ttk.Entry(row, textvariable=self.min_size_var, width=8).pack(side="left", padx=(0, 16))
        ttk.Label(row, text="文件类型：").pack(side="left")
        self.ext_frame = ttk.Frame(row)
        self.ext_frame.pack(side="left", fill="x", expand=True)
        self._build_ext_checks()

        act = ttk.LabelFrame(tab, text=" 开始（扫描全程只读） ", padding=8)
        act.pack(fill="x")
        row2 = ttk.Frame(act)
        row2.pack(fill="x")
        self.scan_btn = ttk.Button(row2, text="开始扫描", style="Accent.TButton", command=self.on_scan)
        self.scan_btn.pack(side="left")
        self.stop_btn = ttk.Button(row2, text="停止", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.scan_bar = ttk.Progressbar(row2, mode="determinate", maximum=100)
        self.scan_bar.pack(side="left", fill="x", expand=True, padx=10)
        self.scan_status = tk.StringVar(value="就绪。先勾选扫描目录，再点击「开始扫描」。")
        ttk.Label(act, textvariable=self.scan_status, foreground=GRAY).pack(fill="x", pady=(6, 0))

    def _build_ext_checks(self):
        for w in self.ext_frame.winfo_children():
            w.destroy()
        self._ext_vars.clear()
        enabled = set(self.settings.get("exts", DEFAULT_EXTS))
        cols = 7
        for i, ext in enumerate(DEFAULT_EXTS):
            var = tk.BooleanVar(value=ext in enabled)
            self._ext_vars[ext] = var
            ttk.Checkbutton(self.ext_frame, text=ext, variable=var)\
                .grid(row=i // cols, column=i % cols, sticky="w", padx=4, pady=1)

    def refresh_roots(self):
        for w in self.roots_frame.winfo_children():
            w.destroy()
        self._root_vars.clear()
        saved = {r["path"]: r.get("enabled", True) for r in self.settings["roots"]}
        for root in detect_roots():
            enabled = saved.get(root.path, True)
            var = tk.BooleanVar(value=enabled)
            self._root_vars.append((root, var))
            ttk.Checkbutton(self.roots_frame, text=f"{root.label} — {root.path}",
                            variable=var).pack(anchor="w", pady=1)
        for r in self.settings["roots"]:
            if any(os.path.normcase(r["path"]) == os.path.normcase(rt.path) for rt, _ in self._root_vars):
                continue
            root = Root(r["path"], r.get("label", "自定义"))
            var = tk.BooleanVar(value=r.get("enabled", True))
            self._root_vars.append((root, var))
            ttk.Checkbutton(self.roots_frame, text=f"{root.label} — {root.path}",
                            variable=var).pack(anchor="w", pady=1)

    def on_detect(self):
        saved = self._collect_root_settings()
        self.settings["roots"] = saved
        store.save_settings(self.settings)
        self.refresh_roots()
        self.scan_status.set("已重新探测。未自动找到微信目录时，请用「添加文件夹…」手动添加。")

    def _collect_root_settings(self):
        out = []
        for root, var in self._root_vars:
            out.append({"path": root.path, "label": root.label, "enabled": bool(var.get())})
        return out

    def on_add_folder(self):
        from tkinter import simpledialog
        # tkinter 自带目录选择
        path = filedialog.askdirectory(title="选择要纳入对比的文件夹")
        if not path:
            return
        self.settings["roots"].append({"path": os.path.normpath(path),
                                       "label": "自定义", "enabled": True})
        store.save_settings(self.settings)
        self.refresh_roots()

    def on_remove_root(self):
        # 移除最后选中的（focus）或弹选择框：简单实现——弹输入序号
        from tkinter import simpledialog
        items = [f"{i + 1}. {rt.label} — {rt.path}" for i, (rt, _) in enumerate(self._root_vars)]
        if not items:
            return
        idx = simpledialog.askstring("移除目录", "输入要移除的序号：\n" + "\n".join(items),
                                     parent=self)
        if not idx or not idx.strip().isdigit():
            return
        i = int(idx.strip()) - 1
        if not (0 <= i < len(self._root_vars)):
            return
        rt, _ = self._root_vars.pop(i)
        # 自定义目录直接删除；自动探测的目录记为停用（否则下次探测会重新出现）
        saved = {os.path.normcase(r["path"]) for r in self.settings["roots"]}
        if os.path.normcase(rt.path) in saved:
            self.settings["roots"] = [r for r in self.settings["roots"]
                                      if os.path.normcase(r["path"]) != os.path.normcase(rt.path)]
        else:
            self.settings["roots"].append({"path": rt.path, "label": rt.label, "enabled": False})
        store.save_settings(self.settings)
        self.refresh_roots()

    def on_scan(self):
        if self._worker and self._worker.is_alive():
            return
        enabled = [rt for rt, var in self._root_vars if var.get()]
        if not enabled:
            messagebox.showinfo("提示", "请先勾选至少一个扫描目录。", parent=self)
            return
        try:
            min_kb = max(0, int(self.min_size_var.get().strip() or "0"))
        except ValueError:
            messagebox.showinfo("提示", "最小文件大小必须是数字（KB）。", parent=self)
            return
        exts = {e for e, var in self._ext_vars.items() if var.get()}
        self.settings["roots"] = self._collect_root_settings()
        self.settings["min_size_kb"] = min_kb
        self.settings["exts"] = sorted(exts)
        store.save_settings(self.settings)

        self._cancel.clear()
        self.scan_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.scan_bar.config(value=0)
        self.scan_status.set("扫描中…（只读，不改动文件）")
        self._worker = threading.Thread(
            target=self._scan_worker,
            args=([Root(rt.path, rt.label) for rt in enabled], exts, min_kb * 1024),
            daemon=True)
        self._worker.start()
        self.after(120, self._poll)

    def on_stop(self):
        self._cancel.set()
        self.scan_status.set("正在停止…")

    def _scan_worker(self, roots, exts, min_size):
        cancel = self._cancel
        try:
            self._q.put(("status", "正在枚举文件…"))
            counter = {"n": 0}

            def prog(n):
                counter["n"] = n
                self._q.put(("scan_prog", n))

            files, skipped = scanner.scan(roots, exts, min_size, prog, cancel)
            if cancel.is_set():
                self._q.put(("stopped",))
                return
            self._q.put(("scan_done", len(files), skipped))

            def hprog(d, t, phase):
                self._q.put(("hash_prog", d, t, phase))

            groups, locked = hasher.build_groups(files, self.cache, hprog, cancel)
            if cancel.is_set():
                self._q.put(("stopped",))
                return
            store.save_cache(self.cache)
            self._q.put(("hash_done", groups, locked))
        except Exception as e:  # noqa: BLE001
            self._q.put(("error", str(e)))

    def _poll(self):
        """轮询后台事件，直到收到终止事件（hash_done / stopped / error）才结束。

        不能以"线程是否存活"作为继续轮询的依据：worker 可能在两次轮询之间
        恰好入队终止事件并退出，导致终止事件永远无人消费、界面永久卡在
        最后一条进度上（表现为进度条满、按钮全部禁用）。
        """
        try:
            try:
                while True:
                    ev = self._q.get_nowait()
                    kind = ev[0]
                    if kind == "status":
                        self.scan_status.set(ev[1])
                    elif kind == "scan_prog":
                        self.scan_status.set(f"已枚举 {ev[1]} 个文件…")
                    elif kind == "scan_done":
                        self.scan_status.set(f"枚举完成：{ev[1]} 个文件（{ev[2]} 个无法访问已跳过）。正在比对哈希…")
                    elif kind == "hash_prog":
                        d, t, phase = ev[1], ev[2], ev[3]
                        pct = int(d * 100 / t) if t else 100
                        self.scan_bar.config(value=pct)
                        self.scan_status.set(f"{phase}：{d} / {t}")
                    elif kind == "hash_done":
                        self._on_hash_done(ev[1], ev[2])
                        return
                    elif kind == "stopped":
                        self._finish_scan("已停止。")
                        return
                    elif kind == "error":
                        self._finish_scan(f"出错：{ev[1]}")
                        messagebox.showerror("错误", ev[1], parent=self)
                        return
            except queue.Empty:
                pass
            # 兜底：线程已退出却迟迟等不到终止事件（正常不应发生）
            if (self._worker is not None and not self._worker.is_alive()
                    and self._q.empty() and str(self.scan_btn["state"]) == "disabled"):
                self._idle_polls = getattr(self, "_idle_polls", 0) + 1
                if self._idle_polls > 25:  # 约 3 秒无事件则强制收尾
                    self._idle_polls = 0
                    self._finish_scan("扫描结束。")
                    return
            else:
                self._idle_polls = 0
            self.after(120, self._poll)
        except Exception as e:  # noqa: BLE001  防止轮询链意外中断导致界面卡死
            try:
                self._finish_scan(f"出错：{e}")
            except Exception:
                pass

    def _finish_scan(self, msg: str):
        self.scan_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.scan_status.set(msg)

    def _on_hash_done(self, groups, locked):
        self.groups = groups
        self.render_results()
        self._finish_scan(
            f"完成：发现 {len(groups)} 组重复文件。"
            + (f" {len(locked)} 个文件被占用已跳过。" if locked else ""))
        if groups:
            self.nb.select(1)

    # ---------- Tab 2：重复项确认（双栏） ----------

    def _build_result_tab(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text=" ② 重复项确认 ")

        top = ttk.Frame(tab)
        top.pack(fill="x")
        self.stats_var = tk.StringVar(value="尚未扫描。")
        ttk.Label(top, textvariable=self.stats_var).pack(side="left")
        ttk.Button(top, text="应用推荐方案", style="Accent.TButton",
                   command=self.on_apply_rec).pack(side="right")
        ttk.Button(top, text="导出 CSV", command=self.on_export).pack(side="right", padx=6)

        pane = ttk.Panedwindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True, pady=8)
        self.results = ScrollFrame(pane)
        pane.add(self.results, weight=3)

        pv = ttk.LabelFrame(pane, text=" 文件预览（点击上方任一文件） ", padding=6)
        pane.add(pv, weight=1)
        head = ttk.Frame(pv)
        head.pack(fill="x")
        self.pv_name = tk.StringVar(value="")
        self.pv_meta = tk.StringVar(value="尚未选择文件。点击列表中任意文件，这里会显示详情与内容预览。")
        tk.Label(head, textvariable=self.pv_name, font=("Microsoft YaHei UI", 10, "bold"),
                 anchor="w").pack(side="left")
        ttk.Button(head, text="打开文件", command=self._open_file).pack(side="right")
        ttk.Button(head, text="打开所在文件夹", command=self._open_folder).pack(side="right", padx=6)
        ttk.Label(pv, textvariable=self.pv_meta, foreground=GRAY,
                  wraplength=900, justify="left").pack(fill="x", pady=(4, 2), anchor="w")
        text_holder = ttk.Frame(pv)
        text_holder.pack(fill="both", expand=True)
        self.pv_text = tk.Text(text_holder, height=7, wrap="none", state="disabled",
                               relief="flat", background="#FFFFFF",
                               foreground="#1A1A1A", insertbackground="#1A1A1A")
        pv_scroll = ttk.Scrollbar(text_holder, orient="vertical", command=self.pv_text.yview)
        self.pv_text.configure(yscrollcommand=pv_scroll.set)
        self.pv_text.pack(side="left", fill="both", expand=True)
        pv_scroll.pack(side="right", fill="y")
        self._selected = None

        bottom = ttk.Frame(tab)
        bottom.pack(fill="x")
        self.summary_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.summary_var).pack(side="left")
        ttk.Button(bottom, text="试运行预览", command=self.on_preview).pack(side="right")
        self.clean_btn = ttk.Button(bottom, text="确认清理", style="Accent.TButton",
                                    command=self.on_clean, state="disabled")
        self.clean_btn.pack(side="right", padx=6)

    def render_results(self):
        self.results.clear()
        self._refs.clear()
        self._selected = None
        for i, g in enumerate(self.groups, 1):
            box = ttk.LabelFrame(
                self.results.inner,
                text=f" {i}. {g.files[0].file_name} · 共 {len(g.files)} 份 · 单份 {format_size(g.files[0].size)} ",
                padding=8)
            box.pack(fill="x", pady=(0, 8), padx=2)
            grid = ttk.Frame(box)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1, uniform="col")
            grid.columnconfigure(1, weight=1, uniform="col")

            left = ttk.Frame(grid)
            left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            right = ttk.Frame(grid)
            right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
            ttk.Label(left, text="我的文档 / 自定义", foreground=GRAY).pack(anchor="w")
            ttk.Label(right, text="微信", foreground=GRAY).pack(anchor="w")

            for f in g.files:
                parent = right if f.from_wechat else left
                self._build_file_row(parent, f)

        self._show_preview(None)
        self.update_summary()

    def _build_file_row(self, parent, f):
        keep = f.decision == KEEP
        bg = ROW_KEEP_BG if keep else ROW_CLEAN_BG
        row = tk.Frame(parent, bg=bg, highlightthickness=1,
                       highlightbackground=BORDER, cursor="hand2")
        row.pack(fill="x", pady=3)
        inner = tk.Frame(row, bg=bg)
        inner.pack(fill="x", padx=6, pady=4)
        top = tk.Frame(inner, bg=bg)
        top.pack(fill="x")
        badge = tk.Label(top, text="保留" if keep else "清理",
                         bg=BADGE_KEEP_BG if keep else BADGE_CLEAN_BG,
                         fg=BADGE_KEEP_FG if keep else BADGE_CLEAN_FG,
                         font=("Microsoft YaHei UI", 9, "bold"), padx=8, pady=2)
        badge.pack(side="left")
        name_lbl = tk.Label(top, text=f.file_name, bg=bg,
                            font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
        name_lbl.pack(side="left", padx=6, fill="x", expand=True)
        path_lbl = tk.Label(inner, text=f.full_path, bg=bg, fg="#555555",
                            wraplength=340, justify="left", anchor="w")
        path_lbl.pack(fill="x")
        info_lbl = tk.Label(inner, text=f.info_text, bg=bg, fg="#555555", anchor="w")
        info_lbl.pack(fill="x")
        btn = tk.Button(inner, text="设为清理" if keep else "设为保留", width=12,
                        relief="flat", bg="#FFFFFF", cursor="hand2",
                        command=lambda: self.on_toggle(f))
        btn.pack(anchor="w", pady=(4, 0))
        bg_widgets = [row, inner, top, name_lbl, path_lbl, info_lbl]
        for w in bg_widgets:
            w.bind("<Button-1>", lambda e, item=f: self.on_select(item))
        self._refs[f] = {"row": row, "bg_widgets": bg_widgets, "badge": badge, "btn": btn}

    def _refresh_row(self, f):
        refs = self._refs.get(f)
        if refs is None:
            return
        keep = f.decision == KEEP
        bg = ROW_KEEP_BG if keep else ROW_CLEAN_BG
        for w in refs["bg_widgets"]:
            w.config(bg=bg)
        refs["badge"].config(text="保留" if keep else "清理",
                             bg=BADGE_KEEP_BG if keep else BADGE_CLEAN_BG,
                             fg=BADGE_KEEP_FG if keep else BADGE_CLEAN_FG)
        refs["btn"].config(text="设为清理" if keep else "设为保留")

    def on_toggle(self, f):
        f.decision = KEEP if f.decision == CLEAN else CLEAN
        self._refresh_row(f)
        self.update_summary()

    def on_select(self, f):
        self._selected = f
        for item, refs in self._refs.items():
            refs["row"].config(highlightbackground=ACCENT if item is f else BORDER)
        self._show_preview(f)

    def on_apply_rec(self):
        for g in self.groups:
            g.recommend()
        for f in self._refs:
            self._refresh_row(f)
        self.update_summary()

    # ---------- 文件预览窗格 ----------

    PREVIEW_LIMIT = 4000

    def _show_preview(self, f):
        if f is None:
            self.pv_name.set("")
            self.pv_meta.set("尚未选择文件。点击列表中任意文件，这里会显示详情与内容预览。")
            self._set_preview_text("")
            return
        import datetime
        t = datetime.datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M:%S")
        self.pv_name.set(f.file_name)
        self.pv_meta.set(
            f"{f.full_path}\n{format_size(f.size)} · {t} · 来源：{f.source} · SHA-256 {f.hash[:16]}")
        self._set_preview_text(self._preview_content(f))

    def _set_preview_text(self, s):
        self.pv_text.config(state="normal")
        self.pv_text.delete("1.0", "end")
        self.pv_text.insert("1.0", s or "")
        self.pv_text.config(state="disabled")

    def _open_file(self):
        if not self._selected:
            return
        try:
            os.startfile(self._selected.full_path)  # noqa: S606
        except OSError as e:
            messagebox.showwarning("打开失败", str(e), parent=self)

    def _open_folder(self):
        if not self._selected:
            return
        subprocess.Popen(["explorer", "/select,", os.path.normpath(self._selected.full_path)])

    def _preview_content(self, f):
        ext = os.path.splitext(f.file_name)[1].lower()
        try:
            if ext in (".txt", ".rtf"):
                with open(f.full_path, "rb") as fh:
                    raw = fh.read(16_000)
                text = self._decode(raw)
                if ext == ".rtf":  # 粗略去掉 RTF 控制字，便于阅读
                    text = re.sub(r"\{\\\*[^{}]*\}", "", text)
                    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
                    text = text.replace("{", "").replace("}", "")
                return text[:self.PREVIEW_LIMIT]
            if ext == ".docx":
                with zipfile.ZipFile(f.full_path) as z:
                    xml = z.read("word/document.xml").decode("utf-8", "ignore")
                xml = xml.replace("</w:p>", "\n")
                return html.unescape(re.sub(r"<[^>]+>", "", xml))[:self.PREVIEW_LIMIT]
            if ext == ".pptx":
                parts = []
                with zipfile.ZipFile(f.full_path) as z:
                    slides = sorted(
                        (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)", n).group(1)))
                    for n in slides:
                        xml = z.read(n).decode("utf-8", "ignore")
                        texts = re.findall(r"<a:t>(.*?)</a:t>", xml)
                        parts.append(f"— {os.path.basename(n)} —\n" + " ".join(texts))
                body = html.unescape("\n\n".join(parts))
                return body[:self.PREVIEW_LIMIT] if body.strip() else "（幻灯片无文本内容）"
            if ext == ".xlsx":
                with zipfile.ZipFile(f.full_path) as z:
                    xml = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
                strings = re.findall(r"<t[^>]*>(.*?)</t>", xml)
                body = html.unescape("\n".join(strings))
                return body[:self.PREVIEW_LIMIT] if body.strip() else "（无共享字符串）"
            if ext == ".zip":
                with zipfile.ZipFile(f.full_path) as z:
                    names = z.namelist()
                head = "\n".join(names[:100])
                more = f"\n… 共 {len(names)} 个条目" if len(names) > 100 else ""
                return f"压缩包内共 {len(names)} 个条目：\n{head}{more}"
            if ext in (".tar", ".gz"):
                try:
                    with tarfile.open(f.full_path) as t:
                        names = t.getnames()
                    head = "\n".join(names[:100])
                    more = f"\n… 共 {len(names)} 个条目" if len(names) > 100 else ""
                    return f"压缩包内共 {len(names)} 个条目：\n{head}{more}"
                except tarfile.ReadError:
                    return "gzip 压缩文件（非 tar 归档），无法列出内部内容。"
            if ext == ".pdf":
                return "PDF 内容无法在本窗格直接预览，请点击「打开文件」查看。"
            return "该格式不支持内容预览，请点击「打开文件」查看。"
        except OSError as e:
            return f"无法读取内容（文件可能被占用）：{e}"
        except Exception as e:  # noqa: BLE001
            return f"无法读取内容：{e}"

    @staticmethod
    def _decode(raw: bytes) -> str:
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "ignore")

    def update_summary(self):
        n_files = sum(len(g.files) for g in self.groups)
        n_clean = sum(g.clean_count for g in self.groups)
        reclaim = sum(g.reclaim for g in self.groups)
        self.stats_var.set(
            f"重复组 {len(self.groups)} · 涉及文件 {n_files} · 全部清理可释放 {format_size(reclaim)}")
        self.summary_var.set(f"已选保留 {n_files - n_clean} 份 · 将清理 {n_clean} 份 · 释放 {format_size(reclaim)}")
        self.clean_btn.config(state="normal" if n_clean else "disabled")

    def _clean_items(self):
        return [f for g in self.groups for f in g.files if f.decision == CLEAN]

    def on_preview(self):
        items = self._clean_items()
        if not items:
            messagebox.showinfo("试运行预览", "当前没有标记为「将清理」的文件。", parent=self)
            return
        total = sum(f.size for f in items)
        win = tk.Toplevel(self)
        win.title("试运行预览（不做任何改动）")
        win.geometry("760x520")
        txt = tk.Text(win, wrap="none")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        lines = [f"将清理 {len(items)} 个文件 · 释放 {format_size(total)}（本次预览不做任何改动）",
                 "-" * 60]
        for f in items:
            lines.append(f"[{f.source}] {f.full_path}")
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 8))

    def on_clean(self):
        items = self._clean_items()
        if not items:
            return
        total = sum(f.size for f in items)
        if not messagebox.askyesno(
                "确认清理",
                f"将把 {len(items)} 个文件移入系统回收站，释放 {format_size(total)}。\n\n"
                "不会永久删除，可在「清理记录」页一键撤销。\n\n确定继续吗？",
                parent=self):
            return
        ok, fail = cleaner.execute(items)
        now = __import__("time").time()
        self.oplog.add_batch([{"path": f.full_path, "size": f.size, "time": now} for f in ok])
        cleaned_paths = {f.full_path for f in ok}
        for g in self.groups:
            g.files = [f for f in g.files if f.full_path not in cleaned_paths]
        self.groups = [g for g in self.groups if len(g.files) > 1]
        self.render_results()
        self.refresh_log()
        if fail:
            messagebox.showwarning("清理完成（部分失败）",
                                   f"成功 {len(ok)} 个，失败 {len(fail)} 个。\n"
                                   "失败文件可能正被微信占用，请关闭微信后重试。",
                                   parent=self)
        else:
            messagebox.showinfo("清理完成",
                                f"已把 {len(ok)} 个文件移入回收站，释放 {format_size(total)}。\n"
                                "可在「清理记录」页撤销。",
                                parent=self)

    def on_export(self):
        if not self.groups:
            messagebox.showinfo("提示", "还没有扫描结果。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="导出 CSV 报告", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")], initialfile="去重报告.csv")
        if not path:
            return
        store.export_csv(path, self.groups)
        messagebox.showinfo("已导出", f"报告已保存到：\n{path}", parent=self)

    # ---------- Tab 3：清理记录 ----------

    def _build_log_tab(self):
        tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(tab, text=" ③ 清理记录 ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="撤销上次清理", command=self.on_undo).pack(side="left")
        ttk.Button(bar, text="刷新", command=self.refresh_log).pack(side="left", padx=6)

        cols = ("time", "file", "size", "status")
        self.log_tree = ttk.Treeview(tab, columns=cols, show="headings", height=18)
        for c, w, t in (("time", 150, "时间"), ("file", 520, "文件（原路径）"),
                        ("size", 90, "大小"), ("status", 90, "状态")):
            self.log_tree.heading(c, text=t)
            self.log_tree.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(tab, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=vsb.set)
        self.log_tree.pack(fill="both", expand=True, pady=8, side="top")
        vsb.place(relx=1.0, rely=0.0, y=30, relheight=0.8, anchor="ne")
        ttk.Label(tab, text="清理的文件都在系统回收站中，即使不通过本软件也可手动还原。",
                  foreground=GRAY).pack(anchor="w")

    def refresh_log(self):
        import time as _t
        tree = self.log_tree
        for iid in tree.get_children():
            tree.delete(iid)
        for batch in reversed(self.oplog.batches):
            for e in batch["entries"]:
                tree.insert("", "end", values=(
                    _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(e["time"])),
                    e["path"], format_size(e["size"]), "已清理"))

    def on_undo(self):
        batch = self.oplog.last_batch()
        if batch is None:
            messagebox.showinfo("提示", "没有可撤销的清理记录。", parent=self)
            return
        entries = batch["entries"]
        if not messagebox.askyesno(
                "撤销清理",
                f"将把最近一次清理的 {len(entries)} 个文件从回收站还原到原位置。\n\n继续吗？",
                parent=self):
            return
        restored, failed = [], []
        for e in entries:
            ok, msg = cleaner.restore(e["path"], e["size"], e["time"])
            (restored if ok else failed).append((e, msg))
        if restored:
            self.oplog.drop_entries(batch, {e["path"] for e, _ in restored})
        self.refresh_log()
        msg = f"已还原 {len(restored)} 个文件到原位置。"
        if failed:
            msg += f"\n{len(failed)} 个未能还原（可能已被回收站清空），请手动检查回收站。"
        messagebox.showinfo("撤销结果", msg, parent=self)
