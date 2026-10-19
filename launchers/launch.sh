#!/usr/bin/env bash
# Qwen Server Desktop 启动器（macOS / Linux 通用）
#
# 要点：从 Finder 或桌面双击启动时，PATH 极窄（通常只有 /usr/bin:/bin），
# 所以不能依赖 `which python3`，必须按固定路径逐个探测，
# 并且用 `import tkinter` 实测，确保选中的解释器真的能画界面。

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$HERE/.." && pwd)"
ENTRY="$APP_DIR/qwen_desktop.py"

if [ ! -f "$ENTRY" ]; then
  echo "找不到入口文件：$ENTRY" >&2
  exit 1
fi

collect_candidates() {
  # 1) 用户显式指定优先
  [ -n "${QWEN_DESKTOP_PYTHON:-}" ] && printf '%s\n' "$QWEN_DESKTOP_PYTHON"

  # 2) python.org 官方安装包（macOS 最常见）
  for v in 3.13 3.12 3.11 3.10 3.9 3.8; do
    printf '%s\n' "/Library/Frameworks/Python.framework/Versions/$v/bin/python3"
  done

  # 3) 包管理器
  printf '%s\n' "/opt/homebrew/bin/python3" "/usr/local/bin/python3"

  # 4) 系统自带
  printf '%s\n' "/usr/bin/python3"

  # 5) PATH 里能找到的
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  fi
  if command -v python3.13 >/dev/null 2>&1; then
    command -v python3.13
  fi
}

find_python() {
  local candidate
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    [ -x "$candidate" ] || continue
    if "$candidate" -c "import tkinter" >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done < <(collect_candidates)
  return 1
}

PY="$(find_python)" || {
  cat >&2 <<'MSG'
✗ 找不到带 tkinter 的 Python 3。

请安装 Python 3.9 或更高版本：
  macOS : https://www.python.org/downloads/
  Ubuntu: sudo apt install python3-tk
  Fedora: sudo dnf install python3-tkinter

装好后重新双击本程序即可。
MSG
  exit 1
}

# 自检模式：只报告探测结果，不启动界面
if [ "${1:-}" = "--check" ]; then
  echo "解释器 : $PY"
  echo "入口   : $ENTRY"
  "$PY" -c "import sys, tkinter; print('版本   : Python %s / Tk %s' % (sys.version.split()[0], tkinter.TkVersion))"
  exit 0
fi

# GUI 程序：把标准输出留一份到日志，便于排查启动失败
mkdir -p "${HOME}/Library/Logs/qwen-desktop" 2>/dev/null || true

exec "$PY" "$ENTRY" "$@"
