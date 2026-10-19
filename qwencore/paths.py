"""跨平台路径解析与 llama-server 二进制探测。

三个平台的文件布局差异全部收敛在这里，其余模块只管调用。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

APP_NAME = "qwen-desktop"


# ── 平台判定 ────────────────────────────────────────────────────────

def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def platform_label() -> str:
    if is_macos():
        return "macOS"
    if is_windows():
        return "Windows"
    if is_linux():
        return "Linux"
    return sys.platform


def home() -> Path:
    return Path.home()


def _env_path(name: str) -> Optional[Path]:
    raw = os.environ.get(name)
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return None


# ── 目录约定 ────────────────────────────────────────────────────────

def default_models_dir() -> Path:
    """模型目录。优先 MODELS_DIR，与 qwen-server 脚本保持一致。"""
    return _env_path("MODELS_DIR") or (home() / "models")


def default_config_dir() -> Path:
    override = _env_path("QWEN_DESKTOP_HOME")
    if override:
        return override
    if is_windows():
        base = os.environ.get("APPDATA") or str(home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if is_macos():
        return home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config")
    return Path(base) / APP_NAME


def default_log_dir() -> Path:
    if is_windows():
        return default_config_dir() / "logs"
    if is_macos():
        return home() / "Library" / "Logs" / APP_NAME
    base = os.environ.get("XDG_STATE_HOME") or str(home() / ".local" / "state")
    return Path(base) / APP_NAME / "logs"


def config_file() -> Path:
    return default_config_dir() / "config.json"


def ensure_dir(path) -> Path:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── llama-server 探测 ───────────────────────────────────────────────

def llama_server_candidates() -> List[Path]:
    """按优先级列出 llama-server 可能的位置。

    顺序即优先级：环境变量 > 本机既有约定 > 包管理器路径 > PATH。
    """
    exe = "llama-server.exe" if is_windows() else "llama-server"
    out: List[Path] = []

    for var in ("LLAMA_SERVER", "LLAMA_SERVER_PATH"):
        p = _env_path(var)
        if p:
            out.append(p)

    # 本机既有约定（qwen-server 脚本用的就是这一套）
    out.append(home() / ".local" / "bin" / exe)
    out.append(home() / "llama.cpp" / exe)
    out.append(home() / "llama.cpp" / "build" / "bin" / exe)

    if is_windows():
        out.append(home() / "llama.cpp" / "build" / "bin" / "Release" / exe)
        for base_var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            raw = os.environ.get(base_var)
            if raw:
                out.append(Path(raw) / "llama.cpp" / exe)
        profile = os.environ.get("USERPROFILE")
        if profile:
            out.append(Path(profile) / "scoop" / "shims" / exe)
            out.append(Path(profile) / "scoop" / "apps" / "llama.cpp" / "current" / exe)
    else:
        for d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/opt/local/bin"):
            out.append(Path(d) / exe)

    which = shutil.which("llama-server")
    if which:
        out.append(Path(which))

    # 去重但保留优先级顺序
    seen = set()
    uniq: List[Path] = []
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def find_llama_server() -> Optional[Path]:
    """返回第一个真实存在且可执行的 llama-server。"""
    for p in llama_server_candidates():
        try:
            if p.is_file() and os.access(str(p), os.X_OK):
                return p
        except OSError:
            continue
    return None


def is_executable(path) -> bool:
    try:
        p = Path(path).expanduser()
        return p.is_file() and os.access(str(p), os.X_OK)
    except OSError:
        return False


# ── 杂项 ────────────────────────────────────────────────────────────

def human_size(num_bytes: float) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return "%d B" % int(value)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%.1f TB" % value
