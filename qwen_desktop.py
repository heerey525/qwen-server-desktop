#!/usr/bin/env python3
"""Qwen Server Desktop —— llama-server 的图形化启动器。

把 ~/.local/bin/qwen-server 的全部能力收进一个窗口：
一键启停、模型与端口配置、状态监视、实时日志。

仅依赖 Python 标准库（tkinter），无需安装任何第三方包。
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# 允许直接双击运行：把项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qwencore import config as cfgmod  # noqa: E402
from qwencore import models as modelsmod  # noqa: E402
from qwencore import paths, server  # noqa: E402
from qwencore import theme  # noqa: E402

APP_TITLE = "Qwen Server Desktop"
WINDOW_W, WINDOW_H = 960, 900
# 最小高度要能容下全部固定区块；日志区是弹性区，
# 空间不足时优先压缩它，而不是把底部按钮挤出可视区。
MIN_W, MIN_H = 880, 780

KV_CHOICES = ("q4_0", "q8_0", "f16", "bf16", "q4_1", "q5_0", "q5_1")
MODE_LABELS = {
    "router": "Router 多模型（按需加载，省内存）",
    "single": "单模型（启动更快）",
}
MODE_KEYS = {v: k for k, v in MODE_LABELS.items()}

# 强制终止目标：端口 -> (显示名, 说明)
KILL_TARGETS = (
    (3098, "qwen-server", "llama.cpp 本地模型服务"),
    (10100, "opencodex", "Codex 代理，由 OpenCodex.app 托管"),
)
# 端口状态轮询间隔（毫秒）
PORT_POLL_MS = 5000


# ── 状态指示灯 ──────────────────────────────────────────────────────

class StatusLight(tk.Canvas):
    """一个带柔和外圈的状态圆点。"""

    COLORS = {
        server.ServerState.STOPPED: theme.NEUTRAL,
        server.ServerState.STARTING: theme.WARNING,
        server.ServerState.RUNNING: theme.SUCCESS,
        server.ServerState.STOPPING: theme.WARNING,
        server.ServerState.ERROR: theme.DANGER,
    }

    def __init__(self, master, size: int = 22, **kw):
        super().__init__(master, width=size, height=size, highlightthickness=0,
                         background=theme.CARD, **kw)
        self._size = size
        self._ring = self.create_oval(1, 1, size - 1, size - 1,
                                      fill="", outline="", width=0)
        self._dot = self.create_oval(5, 5, size - 5, size - 5,
                                     fill=theme.NEUTRAL, outline="")
        self.set_state(server.ServerState.STOPPED)

    def set_state(self, state) -> None:
        color = self.COLORS.get(state, theme.NEUTRAL)
        self.itemconfigure(self._dot, fill=color)
        # 外圈用同色淡化（用浅色近似，避免引入 alpha）
        ring_color = {
            server.ServerState.RUNNING: theme.SUCCESS_DIM,
            server.ServerState.ERROR: "#FBD5D3",
            server.ServerState.STARTING: "#FFE7C2",
            server.ServerState.STOPPING: "#FFE7C2",
        }.get(state, "")
        self.itemconfigure(self._ring, outline=ring_color, width=2 if ring_color else 0)
        if ring_color:
            self.coords(self._ring, 2, 2, self._size - 2, self._size - 2)
            self.coords(self._dot, 7, 7, self._size - 7, self._size - 7)
        else:
            self.coords(self._dot, 5, 5, self._size - 5, self._size - 5)


# ── 主应用 ──────────────────────────────────────────────────────────

class QwenDesktopApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = cfgmod.Config.load()
        self.models = modelsmod.scan_models(self.cfg.models_dir)

        self._events = queue.Queue()
        self._busy = False
        self._external = False   # 端口上的服务不是本程序启动的

        self.server = server.ServerProcess(
            on_log=lambda line: self._events.put(("log", line)),
            on_state=lambda st: self._events.put(("state", st)),
        )

        self._build_window()
        self._build_ui()
        self._load_config_into_ui()
        self._refresh_model_list()
        self._sync_mode_widgets()
        self._apply_state(server.ServerState.STOPPED)

        # 检查端口上是否已经有别的 llama-server 在跑
        self.root.after(400, self._detect_external)
        # 端口占用状态轮询（探测在后台线程，避免阻塞界面）
        self.root.after(600, self._schedule_port_refresh)
        self.root.after(PORT_POLL_MS, self._periodic_port_refresh)
        self.root.after(80, self._poll_events)

    # ── 窗口 ────────────────────────────────────────────────────

    def _build_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.minsize(MIN_W, MIN_H)
        self.root.configure(background=theme.BG)
        self.fonts = theme.apply(self.root)
        self._center(WINDOW_W, WINDOW_H)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 从终端启动时把窗口拉到前台（macOS 常见问题）
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(350, lambda: self.root.attributes("-topmost", False))
        self.root.after(120, self.root.focus_force)

    def _center(self, w: int, h: int) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(w, max(MIN_W, sw - 80))
        h = min(h, max(MIN_H, sh - 120))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # ── 界面装配 ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="TFrame")
        outer.pack(fill="both", expand=True, padx=18, pady=16)

        self._build_status_card(outer)
        self._build_config_card(outer)
        self._build_log_card(outer)
        self._build_kill_card(outer)
        self._build_footer(outer)

    # 状态卡 ─────────────────────────────────────────────────────

    def _build_status_card(self, parent) -> None:
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", pady=(0, 12))
        card.columnconfigure(1, weight=1)

        inner = ttk.Frame(card, style="Card.TFrame")
        inner.grid(row=0, column=0, sticky="w", padx=(18, 0), pady=16)

        self.light = StatusLight(inner)
        self.light.pack(side="left", padx=(0, 12))

        text_box = ttk.Frame(inner, style="Card.TFrame")
        text_box.pack(side="left")
        self.lbl_status = ttk.Label(text_box, text="已停止", style="Status.TLabel")
        self.lbl_status.pack(anchor="w")
        self.lbl_sub = ttk.Label(text_box, text="", style="StatusMuted.TLabel")
        self.lbl_sub.pack(anchor="w", pady=(3, 0))

        btns = ttk.Frame(card, style="Card.TFrame")
        btns.grid(row=0, column=2, sticky="e", padx=(12, 18), pady=16)

        self.btn_start = ttk.Button(btns, text="启动服务", style="Primary.TButton",
                                    command=self.on_start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="停止服务", style="Danger.TButton",
                                   command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))

    # 配置卡 ─────────────────────────────────────────────────────

    def _build_config_card(self, parent) -> None:
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", pady=(0, 12))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="运行配置", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 10))

        form = ttk.Frame(card, style="Card.TFrame")
        form.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        def field_label(text: str, row: int, col: int) -> None:
            ttk.Label(form, text=text, style="CardMuted.TLabel").grid(
                row=row, column=col, sticky="w",
                padx=(0 if col == 0 else 18, 6), pady=(0, 8))

        # 行 0 ── 运行模式 | 端口
        field_label("运行模式", 0, 0)
        self.var_mode = tk.StringVar()
        self.cmb_mode = ttk.Combobox(form, textvariable=self.var_mode, state="readonly",
                                     values=[MODE_LABELS["router"], MODE_LABELS["single"]])
        self.cmb_mode.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.cmb_mode.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())

        field_label("端口", 0, 2)
        self.var_port = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_port, width=10).grid(
            row=0, column=3, sticky="w", pady=(0, 8))

        # 行 1 ── 模型 | 上下文
        field_label("模型", 1, 0)
        self.var_model = tk.StringVar()
        self.cmb_model = ttk.Combobox(form, textvariable=self.var_model, state="readonly")
        self.cmb_model.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self.cmb_model.bind("<<ComboboxSelected>>", lambda e: self._on_model_change())

        field_label("上下文", 1, 2)
        self.var_ctx = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_ctx, width=10).grid(
            row=1, column=3, sticky="w", pady=(0, 8))

        # 行 2 ── 模型目录 [浏览] | GPU 层数
        field_label("模型目录", 2, 0)
        dir_row = ttk.Frame(form, style="Card.TFrame")
        dir_row.grid(row=2, column=1, sticky="ew", pady=(0, 8))
        dir_row.columnconfigure(0, weight=1)
        self.var_models_dir = tk.StringVar()
        ttk.Entry(dir_row, textvariable=self.var_models_dir).grid(row=0, column=0, sticky="ew")
        ttk.Button(dir_row, text="浏览", style="Mini.TButton",
                   command=self._browse_models_dir).grid(row=0, column=1, padx=(6, 0))

        field_label("GPU 层数", 2, 2)
        self.var_ngl = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_ngl, width=10).grid(
            row=2, column=3, sticky="w", pady=(0, 8))

        # 行 3 ── llama-server [浏览] | 驻留上限
        field_label("llama-server", 3, 0)
        exe_row = ttk.Frame(form, style="Card.TFrame")
        exe_row.grid(row=3, column=1, sticky="ew", pady=(0, 10))
        exe_row.columnconfigure(0, weight=1)
        self.var_llama = tk.StringVar()
        ttk.Entry(exe_row, textvariable=self.var_llama).grid(row=0, column=0, sticky="ew")
        ttk.Button(exe_row, text="浏览", style="Mini.TButton",
                   command=self._browse_llama).grid(row=0, column=1, padx=(6, 0))

        field_label("驻留上限", 3, 2)
        self.var_models_max = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_models_max, width=10).grid(
            row=3, column=3, sticky="w", pady=(0, 10))

        # 行 4 ── 开关组
        switches = ttk.Frame(form, style="Card.TFrame")
        switches.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(2, 0))

        ttk.Label(switches, text="KV 缓存", style="CardMuted.TLabel").pack(
            side="left", padx=(0, 6))
        self.var_kv = tk.StringVar()
        ttk.Combobox(switches, textvariable=self.var_kv, state="readonly",
                     values=list(KV_CHOICES), width=7).pack(side="left")

        self.var_flash = tk.BooleanVar()
        ttk.Checkbutton(switches, text="Flash Attention", variable=self.var_flash).pack(
            side="left", padx=(16, 0))
        self.var_jinja = tk.BooleanVar()
        ttk.Checkbutton(switches, text="Jinja 模板", variable=self.var_jinja).pack(
            side="left", padx=(12, 0))
        self.var_auto_browser = tk.BooleanVar()
        ttk.Checkbutton(switches, text="就绪后打开界面",
                        variable=self.var_auto_browser).pack(side="left", padx=(12, 0))

        # 行 5 ── 附加参数
        extra = ttk.Frame(form, style="Card.TFrame")
        extra.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        extra.columnconfigure(1, weight=1)
        ttk.Label(extra, text="附加参数", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.var_extra = tk.StringVar()
        ttk.Entry(extra, textvariable=self.var_extra).grid(row=0, column=1, sticky="ew")

    # 日志卡 ─────────────────────────────────────────────────────

    def _build_log_card(self, parent) -> None:
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="both", expand=True, pady=(0, 12))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        header = ttk.Frame(card, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="运行日志", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w")
        self.lbl_cmd = ttk.Label(header, text="", style="CardMuted.TLabel")
        self.lbl_cmd.grid(row=0, column=1, sticky="w", padx=(12, 0))

        tools = ttk.Frame(header, style="Card.TFrame")
        tools.grid(row=0, column=2, sticky="e")
        ttk.Button(tools, text="清空", style="Mini.TButton",
                   command=self._clear_log).pack(side="left")
        ttk.Button(tools, text="打开日志文件", style="Mini.TButton",
                   command=self._open_log_file).pack(side="left", padx=(6, 0))

        body = tk.Frame(card, background=theme.LOG_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            body, background=theme.LOG_BG, foreground=theme.LOG_FG,
            insertbackground=theme.LOG_FG, relief="flat", wrap="word",
            font=self.fonts["mono"], padx=12, pady=10,
            highlightthickness=0, borderwidth=0, state="disabled",
            selectbackground=theme.LOG_SELECT, height=5,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(body, orient="vertical", command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)

        self.log_text.tag_configure("err", foreground="#FF6B6B")
        self.log_text.tag_configure("warn", foreground="#FFD166")
        self.log_text.tag_configure("cmd", foreground="#7FD1FF")
        self.log_text.tag_configure("ok", foreground="#7BE495")
        self.log_text.tag_configure("dim", foreground=theme.LOG_FG_DIM)

    # 底部栏 ─────────────────────────────────────────────────────

    def _build_footer(self, parent) -> None:
        bar = ttk.Frame(parent, style="TFrame")
        bar.pack(fill="x")

        self.lbl_hint = ttk.Label(bar, text="", style="Hint.TLabel")
        self.lbl_hint.pack(side="left")

        ttk.Button(bar, text="退出", style="Secondary.TButton",
                   command=self._on_close).pack(side="right")
        self.btn_web = ttk.Button(bar, text="打开 Web 界面", style="Secondary.TButton",
                                  command=self._open_web, state="disabled")
        self.btn_web.pack(side="right", padx=(0, 8))

    # 强制终止卡 ───────────────────────────────────────────────

    def _build_kill_card(self, parent) -> None:
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(fill="x", pady=(0, 12))
        card.columnconfigure(0, weight=1)

        header = ttk.Frame(card, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="强制终止", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(header, text="按端口定位并结束进程", style="CardMuted.TLabel").grid(
            row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Button(header, text="刷新", style="Mini.TButton",
                   command=self._schedule_port_refresh).grid(row=0, column=2, sticky="e")

        grid = ttk.Frame(card, style="Card.TFrame")
        grid.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        grid.columnconfigure(2, weight=1)

        self._kill_rows = {}
        for i, (port, name, note) in enumerate(KILL_TARGETS):
            ttk.Label(grid, text=str(port), style="Card.TLabel",
                      font=self.fonts["mono"]).grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Label(grid, text=name, style="Card.TLabel",
                      font=self.fonts["ui_bold"]).grid(
                row=i, column=1, sticky="w", padx=(12, 0), pady=4)

            status = ttk.Label(grid, text="检测中…", style="CardMuted.TLabel")
            status.grid(row=i, column=2, sticky="w", padx=(12, 0), pady=4)

            btn = ttk.Button(grid, text="终止", style="Mini.TButton",
                             command=lambda p=port, n=name: self._on_kill_port(p, n))
            btn.grid(row=i, column=3, sticky="e", padx=(12, 0), pady=4)

            self._kill_rows[port] = (status, btn)

        # 说明文字：让用户知道自己在杀什么
        ttk.Label(card,
                  text="3098 为本地模型服务；10100 为 Codex 代理，终止后 OpenCodex.app 会断开连接。",
                  style="CardMuted.TLabel").grid(
            row=2, column=0, sticky="w", padx=18, pady=(0, 10))

    # ── 端口状态轮询 ────────────────────────────────────────────

    def _schedule_port_refresh(self) -> None:
        threading.Thread(target=self._probe_ports_bg, daemon=True).start()

    def _probe_ports_bg(self) -> None:
        result = {}
        for port, _name, _note in KILL_TARGETS:
            try:
                result[port] = server.describe_port(port)
            except Exception:
                result[port] = []
        self._events.put(("ports", result))

    def _periodic_port_refresh(self) -> None:
        self._schedule_port_refresh()
        self.root.after(PORT_POLL_MS, self._periodic_port_refresh)

    def _apply_port_status(self, result) -> None:
        for port, rows in result.items():
            widgets = self._kill_rows.get(port)
            if not widgets:
                continue
            status, btn = widgets
            if rows:
                desc = "  ·  ".join("PID %d %s" % (pid, name) for pid, name in rows)
                status.configure(text=desc, foreground=theme.WARNING)
                btn.configure(state="normal")
            else:
                status.configure(text="空闲", foreground=theme.FG_FAINT)
                btn.configure(state="disabled")

    # ── 终止操作 ────────────────────────────────────────────────

    def _on_kill_port(self, port: int, name: str) -> None:
        rows = server.describe_port(port)
        if not rows:
            self._apply_port_status({port: []})
            messagebox.showinfo(APP_TITLE, "端口 %d 当前没有进程在监听。" % port)
            return

        detail = "\n".join("    PID %-8d %s" % (pid, pname) for pid, pname in rows)
        extra = ""
        if port == 10100:
            extra = ("\n\n注意：这是 OpenCodex 的代理进程。终止后 OpenCodex.app\n"
                     "会断开连接；如需恢复，请在应用里重新启动。")
        if not messagebox.askyesno(
                APP_TITLE,
                "即将终止占用端口 %d 的进程（%s）：\n\n%s%s\n\n确定继续吗？"
                % (port, name, detail, extra)):
            return

        self._append_log("=== 请求终止端口 %d 的进程 ===" % port, tag="cmd")
        for pid, pname in rows:
            self._append_log("  目标 PID %d (%s)" % (pid, pname), tag="dim")
        self._kill_rows[port][1].configure(state="disabled")
        threading.Thread(target=self._kill_port_bg, args=(port,), daemon=True).start()

    def _kill_port_bg(self, port: int) -> None:
        try:
            dead, alive = server.kill_port(port)
        except Exception as exc:
            self._events.put(("killed", (port, [], [], str(exc))))
            return
        self._events.put(("killed", (port, dead, alive, None)))

    def _on_killed(self, port: int, dead, alive, error) -> None:
        if error:
            self._append_log("终止失败：%s" % error, tag="err")
            messagebox.showerror(APP_TITLE, "终止失败：\n%s" % error)
        else:
            for pid in dead:
                self._append_log("  已结束 PID %d" % pid, tag="ok")
            for pid in alive:
                self._append_log("  ⚠ PID %d 仍在运行，可能需要管理员权限" % pid, tag="err")
            if dead:
                self._append_log("=== 端口 %d 已释放 ===" % port, tag="ok")

        # 如果被杀掉的正是本程序托管的那个服务，同步界面状态
        my_pid = self.server.pid
        if my_pid and my_pid in list(dead):
            self._append_log("该进程由本程序启动，界面状态已同步为「已停止」。", tag="dim")
            self.server.stop()
            self._external = False
            self._apply_state(server.ServerState.STOPPED)

        # 外部进程被清掉后，启动按钮要重新可用
        if port == self.cfg.port and not server.is_port_free(self.cfg.host, self.cfg.port):
            pass
        elif port == self.cfg.port:
            self._external = False
            if self.server.state == server.ServerState.RUNNING and not self.server.is_running():
                self._apply_state(server.ServerState.STOPPED)

        self._schedule_port_refresh()
        self._update_hint()

    # ── 配置 <-> 界面 ───────────────────────────────────────────

    def _load_config_into_ui(self) -> None:
        c = self.cfg
        self.var_mode.set(MODE_LABELS.get(c.mode, MODE_LABELS["router"]))
        self.var_models_dir.set(c.models_dir)
        self.var_llama.set(c.llama_server)
        self.var_port.set(str(c.port))
        self.var_ctx.set(str(c.ctx))
        self.var_ngl.set(str(c.ngl))
        self.var_models_max.set(str(c.models_max))
        self.var_kv.set(c.kv_cache_type or "q4_0")
        self.var_flash.set(bool(c.use_flash_attn))
        self.var_jinja.set(bool(c.use_jinja))
        self.var_auto_browser.set(bool(c.auto_open_browser))
        self.var_extra.set(c.extra_args)

    def _collect_config(self) -> cfgmod.Config:
        """从界面读回配置，非法数字抛 ValueError。"""

        def as_int(var: tk.StringVar, name: str, low: int, high: int) -> int:
            raw = (var.get() or "").strip()
            if not raw:
                raise ValueError("「%s」不能为空" % name)
            try:
                value = int(raw)
            except ValueError:
                raise ValueError("「%s」必须是整数，当前填的是 %r" % (name, raw))
            if not (low <= value <= high):
                raise ValueError("「%s」应在 %d ~ %d 之间，当前是 %d" % (name, low, high, value))
            return value

        c = self.cfg
        c.mode = MODE_KEYS.get(self.var_mode.get(), "router")
        c.model_file = self._selected_model_file()
        c.models_dir = (self.var_models_dir.get() or "").strip()
        c.llama_server = (self.var_llama.get() or "").strip()
        c.port = as_int(self.var_port, "端口", 1, 65535)
        c.ctx = as_int(self.var_ctx, "上下文", 1, 10_000_000)
        c.ngl = as_int(self.var_ngl, "GPU 层数", 0, 9999)
        c.models_max = as_int(self.var_models_max, "驻留上限", 1, 64)
        c.kv_cache_type = self.var_kv.get() or ""
        c.use_flash_attn = bool(self.var_flash.get())
        c.use_jinja = bool(self.var_jinja.get())
        c.auto_open_browser = bool(self.var_auto_browser.get())
        c.extra_args = (self.var_extra.get() or "").strip()
        return c

    # ── 模型列表 ────────────────────────────────────────────────

    def _refresh_model_list(self) -> None:
        models_dir = (self.var_models_dir.get() or self.cfg.models_dir or "").strip()
        self.models = modelsmod.scan_models(models_dir)

        labels = [m.label for m in self.models]
        self.cmb_model.configure(values=labels)

        if not self.models:
            self.var_model.set("")
            self.lbl_hint.configure(
                text="模型目录里没有 .gguf 文件：%s" % (models_dir or "（未设置）"))
            return

        # 尽量保留原有选择
        want = self.cfg.model_file
        chosen = next((m for m in self.models if m.filename == want), None)
        if chosen is None:
            chosen = next((m for m in self.models if m.alias), self.models[0])
        self.var_model.set(chosen.label)
        # 注意：这里不动「上下文」。Router 模式该用 CTX_ROUTER，
        # 单模型模式该用模型推荐值，两者的切换由 _on_mode_change /
        # _on_model_change 在用户主动操作时处理；初始化阶段只还原配置。

    def _selected_model(self):
        label = self.var_model.get()
        for m in self.models:
            if m.label == label:
                return m
        return None

    def _selected_model_file(self) -> str:
        m = self._selected_model()
        return m.filename if m else ""

    def _sync_ctx_with_model(self, model) -> None:
        """切换模型时把推荐上下文填进去（仅当当前值看起来是自动填的）。"""
        if model is None:
            return
        self.var_ctx.set(str(model.recommended_ctx))

    def _on_model_change(self) -> None:
        m = self._selected_model()
        if m:
            self._sync_ctx_with_model(m)
            self._update_hint()

    def _on_mode_change(self) -> None:
        mode = MODE_KEYS.get(self.var_mode.get(), "router")
        if mode == "router":
            self.var_ctx.set(str(modelsmod.CTX_ROUTER))
        else:
            self._sync_ctx_with_model(self._selected_model())
        self._sync_mode_widgets()

    def _sync_mode_widgets(self) -> None:
        """只调整控件的可用状态，不改变任何取值。"""
        mode = MODE_KEYS.get(self.var_mode.get(), "router")
        if mode == "single":
            self.cmb_model.configure(state="readonly")
        else:
            self.cmb_model.configure(state="disabled")
        self._update_hint()

    def _update_hint(self) -> None:
        mode = MODE_KEYS.get(self.var_mode.get(), "router")
        if mode == "router":
            self.lbl_hint.configure(
                text="Router 模式：%d 个模型全部列出，按需加载，最多同时驻留 %s 个"
                     % (len(self.models), self.var_models_max.get()))
        else:
            m = self._selected_model()
            if m:
                self.lbl_hint.configure(text="单模型：%s" % m.detail)
            else:
                self.lbl_hint.configure(text="单模型：尚未选择模型")

    # ── 浏览 ────────────────────────────────────────────────────

    def _browse_models_dir(self) -> None:
        initial = self.var_models_dir.get() or str(paths.default_models_dir())
        chosen = filedialog.askdirectory(title="选择模型目录", initialdir=initial)
        if chosen:
            self.var_models_dir.set(chosen)
            self.cfg.model_file = ""
            self._refresh_model_list()

    def _browse_llama(self) -> None:
        initial_dir = str(Path(self.var_llama.get()).parent) if self.var_llama.get() else str(paths.home())
        chosen = filedialog.askopenfilename(
            title="选择 llama-server 可执行文件",
            initialdir=initial_dir,
            filetypes=[("可执行文件", "*")] if paths.is_windows() else [("所有文件", "*")],
        )
        if chosen:
            self.var_llama.set(chosen)

    # ── 启动 / 停止 ─────────────────────────────────────────────

    def on_start(self) -> None:
        if self._busy or self.server.is_running():
            return

        if self._external:
            messagebox.showwarning(
                APP_TITLE,
                "端口 %d 上已有一个 llama-server 在运行（不是本程序启动的）。\n\n"
                "请先在原来启动它的地方停止，或改用一个空闲端口。"
                % self.cfg.port)
            return

        try:
            cfg = self._collect_config()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        if not paths.is_executable(cfg.llama_server):
            messagebox.showerror(
                APP_TITLE,
                "找不到可执行的 llama-server：\n%s\n\n"
                "请在上方「llama-server」一栏指定正确路径。" % (cfg.llama_server or "（空）"))
            return

        if cfg.mode == "single":
            model = self._selected_model()
            if model is None:
                messagebox.showerror(APP_TITLE, "单模型模式下请先选择一个模型。")
                return
        else:
            model = None
            if not self.models:
                messagebox.showerror(APP_TITLE, "模型目录里没有可用的 .gguf 文件。")
                return

        if not server.is_port_free(cfg.host, cfg.port):
            messagebox.showerror(
                APP_TITLE,
                "端口 %d 已被占用。\n\n请换一个端口，或先释放它。" % cfg.port)
            return

        try:
            argv = server.build_command(cfg, model)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        cfg.save()
        self.cfg = cfg
        self._append_log("", tag=None)
        self._append_log("=== 启动服务 ===", tag="cmd")
        self._set_busy(True)
        self.lbl_cmd.configure(text="端口 %d" % cfg.port)

        try:
            self.server.start(argv)
        except Exception as exc:
            self._append_log("启动失败：%s" % exc, tag="err")
            self._set_busy(False)
            self._apply_state(server.ServerState.ERROR)
            messagebox.showerror(APP_TITLE, "启动失败：\n%s" % exc)
            return

        threading.Thread(target=self._wait_ready, args=(cfg.host, cfg.port),
                         daemon=True).start()

    def _wait_ready(self, host: str, port: int) -> None:
        ok = self.server.wait_ready(host, port, timeout=180.0)
        self._events.put(("ready", (ok, port)))

    def on_stop(self) -> None:
        if self._busy or not self.server.is_running():
            return
        self._set_busy(True)
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self) -> None:
        ok = self.server.stop()
        self._events.put(("stopped", ok))

    def _detect_external(self) -> None:
        """启动时检查端口上是否已有服务在跑。"""
        if self.server.is_running():
            return
        host, port = self.cfg.host, self.cfg.port
        if server.is_port_free(host, port):
            return
        if server.is_healthy(host, port):
            self._external = True
            self._apply_state(server.ServerState.RUNNING)
            served = server.list_served_models(host, port)
            self.lbl_sub.configure(
                text="端口 %d 上已有服务在运行（非本程序启动）· %d 个模型"
                     % (port, len(served)))
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self.btn_web.configure(state="normal")
            self._append_log(
                "检测到端口 %d 上已有 llama-server 在运行（非本程序启动）。" % port,
                tag="warn")
            self._append_log("本程序不会接管它；如需管理，请先停止原进程。", tag="dim")
        else:
            self.lbl_hint.configure(
                text="端口 %d 被其它程序占用" % port)

    # ── 事件循环 ────────────────────────────────────────────────

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "state":
                    self._apply_state(payload)
                elif kind == "ready":
                    self._on_ready(*payload)
                elif kind == "stopped":
                    self._on_stopped(payload)
                elif kind == "ports":
                    self._apply_port_status(payload)
                elif kind == "killed":
                    self._on_killed(*payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._poll_events)

    def _apply_state(self, state) -> None:
        self.light.set_state(state)
        self.lbl_status.configure(text=server.STATE_TEXT.get(state, str(state)))

        running = state in (server.ServerState.RUNNING, server.ServerState.STARTING)
        if state == server.ServerState.RUNNING:
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal" if not self._external else "disabled")
            self.btn_web.configure(state="normal")
            pid = self.server.pid
            self.lbl_sub.configure(
                text="端口 %d · PID %s · %s"
                     % (self.cfg.port, pid if pid else "—",
                        "本程序托管" if pid else "外部进程"))
        elif state == server.ServerState.STARTING:
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.btn_web.configure(state="disabled")
            self.lbl_sub.configure(text="端口 %d · 正在加载模型，请稍候…" % self.cfg.port)
        elif state == server.ServerState.STOPPING:
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self.btn_web.configure(state="disabled")
        elif state == server.ServerState.ERROR:
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.btn_web.configure(state="disabled")
            self.lbl_sub.configure(text="进程异常退出，详见下方日志")
        else:  # STOPPED
            self.btn_start.configure(state="normal" if not self._external else "disabled")
            self.btn_stop.configure(state="disabled")
            self.btn_web.configure(state="disabled")
            if not self._external:
                self.lbl_sub.configure(text="端口 %d · 待启动" % self.cfg.port)

        if not running and state == server.ServerState.STOPPED:
            self._set_busy(False)

    def _on_ready(self, ok: bool, port: int) -> None:
        self._set_busy(False)
        if ok:
            self._append_log("=== 服务已就绪：http://127.0.0.1:%d ===" % port, tag="ok")
            self._apply_state(server.ServerState.RUNNING)
            self._update_hint()
            if self.var_auto_browser.get():
                self._open_web()
        else:
            self._append_log("等待就绪超时或进程已退出。", tag="err")
            if self.server.is_running():
                self.lbl_sub.configure(text="进程在运行，但健康检查未通过（可能仍在加载）")
            else:
                self._apply_state(server.ServerState.ERROR)

    def _on_stopped(self, ok: bool) -> None:
        self._set_busy(False)
        self._external = False
        self._apply_state(server.ServerState.STOPPED)
        self._update_hint()
        if not ok:
            messagebox.showwarning(APP_TITLE, "进程可能未完全退出，请查看日志。")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="disabled")

    # ── 日志 ────────────────────────────────────────────────────

    def _append_log(self, text: str, tag=None) -> None:
        if tag is None:
            low = text.lower()
            if any(k in low for k in ("error", "failed", "错误", "失败", "异常")):
                tag = "err"
            elif any(k in low for k in ("warn", "警告", "⚠")):
                tag = "warn"
            elif text.startswith("$ "):
                tag = "cmd"
            elif text.startswith("=== "):
                tag = "cmd"
            elif text.startswith("——"):
                tag = "dim"

        self.log_text.configure(state="normal")
        # 行数上限，避免长时间运行后内存膨胀
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 3000:
            self.log_text.delete("1.0", "500.0")
        if tag:
            self.log_text.insert("end", text + "\n", tag)
        else:
            self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _open_log_file(self) -> None:
        path = self.server.log_path
        if not path.is_file():
            messagebox.showinfo(APP_TITLE, "日志文件尚未生成：\n%s" % path)
            return
        self._open_path(path)

    def _open_path(self, path) -> None:
        try:
            if paths.is_macos():
                subprocess.Popen(["open", str(path)])
            elif paths.is_windows():
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "无法打开：%s" % exc)

    # ── Web 界面 ────────────────────────────────────────────────

    def _open_web(self) -> None:
        url = "http://127.0.0.1:%d" % self.cfg.port
        try:
            webbrowser.open(url)
        except Exception:
            messagebox.showinfo(APP_TITLE, "请手动访问：%s" % url)

    # ── 关闭 ────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self.server.is_running():
            answer = messagebox.askyesnocancel(
                APP_TITLE,
                "llama-server 正在运行（端口 %d）。\n\n"
                "「是」  停止服务并退出\n"
                "「否」  保持服务运行，只关闭界面\n"
                "「取消」返回" % self.cfg.port)
            if answer is None:
                return
            if answer:
                self._append_log("正在停止服务…", tag="dim")
                self.server.stop()
        try:
            self._collect_config().save()
        except Exception:
            pass
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    QwenDesktopApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
