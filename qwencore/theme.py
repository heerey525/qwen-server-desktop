"""界面主题：配色、字体探测与 ttk 样式。

统一使用 clam 主题而非各平台原生主题，这样三个操作系统的外观
保持一致——跨平台软件最忌讳"在 Mac 上长这样、到 Windows 上认不出来"。
"""

from __future__ import annotations

from tkinter import font as tkfont
from tkinter import ttk

# ── 浅色主题配色 ────────────────────────────────────────────────────

BG = "#F4F4F6"
CARD = "#FFFFFF"
CARD_ALT = "#FAFAFC"
BORDER = "#DCDCE0"

FG = "#1D1D1F"
FG_MUTED = "#6E6E73"
FG_FAINT = "#9A9AA0"
FG_ON_ACCENT = "#FFFFFF"

ACCENT = "#0071E3"
ACCENT_HOVER = "#0062C4"
ACCENT_DISABLED = "#B7D5F5"

SUCCESS = "#34C759"
SUCCESS_DIM = "#C8EBCF"
WARNING = "#FF9F0A"
DANGER = "#FF3B30"
DANGER_HOVER = "#E02D23"
DANGER_DISABLED = "#F5BDB9"
NEUTRAL = "#B0B0B5"

LOG_BG = "#1C1C1E"
LOG_FG = "#E8E8EA"
LOG_FG_DIM = "#8E8E93"
LOG_SELECT = "#3A3A3C"

# 中文优先的界面字体候选
_UI_FONT_CANDIDATES = (
    "SF Pro Text", "Helvetica Neue", "PingFang SC", "Hiragino Sans GB",
    "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei",
    "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
    "DejaVu Sans", "Arial",
)

_MONO_FONT_CANDIDATES = (
    "SF Mono", "Menlo", "Monaco", "Consolas", "Cascadia Mono",
    "DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono", "Courier New",
)


def _pick(root, candidates, fallback):
    try:
        available = set(tkfont.families(root))
    except Exception:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def pick_ui_font(root) -> str:
    return _pick(root, _UI_FONT_CANDIDATES, "TkDefaultFont")


def pick_mono_font(root) -> str:
    return _pick(root, _MONO_FONT_CANDIDATES, "TkFixedFont")


def apply(root) -> dict:
    """装配 ttk 样式，返回字体字典供其他部件复用。"""
    ui_family = pick_ui_font(root)
    mono_family = pick_mono_font(root)

    fonts = {
        "ui": (ui_family, 11),
        "ui_small": (ui_family, 10),
        "ui_bold": (ui_family, 11, "bold"),
        "title": (ui_family, 15, "bold"),
        "status": (ui_family, 13, "bold"),
        "mono": (mono_family, 10),
        "mono_small": (mono_family, 9),
        "family": ui_family,
        "mono_family": mono_family,
    }

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(background=BG)

    # 容器
    style.configure(".", background=BG, foreground=FG, font=fonts["ui"])
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD, relief="flat")
    style.configure("CardAlt.TFrame", background=CARD_ALT, relief="flat")

    # 文本
    style.configure("TLabel", background=BG, foreground=FG, font=fonts["ui"])
    style.configure("Card.TLabel", background=CARD, foreground=FG)
    style.configure("CardMuted.TLabel", background=CARD, foreground=FG_MUTED,
                    font=fonts["ui_small"])
    style.configure("CardTitle.TLabel", background=CARD, foreground=FG,
                    font=fonts["ui_bold"])
    style.configure("Status.TLabel", background=CARD, foreground=FG,
                    font=fonts["status"])
    style.configure("StatusMuted.TLabel", background=CARD, foreground=FG_MUTED,
                    font=fonts["ui_small"])
    style.configure("Hint.TLabel", background=BG, foreground=FG_FAINT,
                    font=fonts["ui_small"])

    # 分隔线
    style.configure("TSeparator", background=BORDER)

    # 输入控件
    style.configure(
        "TEntry",
        fieldbackground=CARD, foreground=FG, bordercolor=BORDER,
        lightcolor=BORDER, darkcolor=BORDER, insertcolor=FG,
        padding=6,
    )
    style.map("TEntry", bordercolor=[("focus", ACCENT)])

    style.configure(
        "TCombobox",
        fieldbackground=CARD, background=CARD, foreground=FG,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        arrowcolor=FG_MUTED, padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", CARD), ("disabled", CARD_ALT)],
        foreground=[("disabled", FG_FAINT)],
        bordercolor=[("focus", ACCENT)],
        arrowcolor=[("disabled", FG_FAINT)],
    )
    # 下拉列表（macOS 上由系统绘制，这里主要照顾 Win/Linux）
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", FG_ON_ACCENT)
    root.option_add("*TCombobox*Listbox.font", fonts["ui"])

    style.configure("TCheckbutton", background=CARD, foreground=FG,
                    focuscolor=CARD)
    style.map("TCheckbutton", background=[("active", CARD)])

    style.configure("TSpinbox",
                    fieldbackground=CARD, foreground=FG, bordercolor=BORDER,
                    arrowcolor=FG_MUTED, padding=5)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)])

    # 按钮：主操作
    style.configure(
        "Primary.TButton",
        background=ACCENT, foreground=FG_ON_ACCENT,
        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
        focuscolor=ACCENT, relief="flat", padding=(18, 9),
        font=fonts["ui_bold"],
    )
    style.map(
        "Primary.TButton",
        background=[("disabled", ACCENT_DISABLED), ("pressed", ACCENT_HOVER),
                    ("active", ACCENT_HOVER)],
        bordercolor=[("disabled", ACCENT_DISABLED), ("pressed", ACCENT_HOVER),
                     ("active", ACCENT_HOVER)],
        foreground=[("disabled", "#FFFFFF")],
    )

    # 按钮：危险操作（停止）
    style.configure(
        "Danger.TButton",
        background=DANGER, foreground="#FFFFFF",
        bordercolor=DANGER, lightcolor=DANGER, darkcolor=DANGER,
        focuscolor=DANGER, relief="flat", padding=(18, 9),
        font=fonts["ui_bold"],
    )
    style.map(
        "Danger.TButton",
        background=[("disabled", DANGER_DISABLED), ("pressed", DANGER_HOVER),
                    ("active", DANGER_HOVER)],
        bordercolor=[("disabled", DANGER_DISABLED), ("pressed", DANGER_HOVER),
                     ("active", DANGER_HOVER)],
        foreground=[("disabled", "#FFFFFF")],
    )

    # 按钮：次级
    style.configure(
        "Secondary.TButton",
        background=CARD, foreground=FG,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        focuscolor=CARD, relief="flat", padding=(14, 8),
        font=fonts["ui"],
    )
    style.map(
        "Secondary.TButton",
        background=[("disabled", CARD_ALT), ("pressed", "#E8E8EC"),
                    ("active", "#EFEFF2")],
        foreground=[("disabled", FG_FAINT)],
        bordercolor=[("active", BORDER), ("pressed", BORDER)],
    )

    # 按钮：卡片上的小图标按钮
    style.configure(
        "Mini.TButton",
        background=CARD, foreground=FG_MUTED,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        focuscolor=CARD, relief="flat", padding=(10, 6),
        font=fonts["ui_small"],
    )
    style.map(
        "Mini.TButton",
        background=[("pressed", "#E8E8EC"), ("active", "#EFEFF2")],
    )

    return fonts
