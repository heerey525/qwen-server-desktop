#!/usr/bin/env bash
#
# 用 PyInstaller 打包成完全不依赖 Python 环境的可执行程序。
#
#   ./build_standalone.sh
#
# 产物：
#   macOS   -> dist/Qwen Server.app
#   Windows -> dist/Qwen Server/Qwen Server.exe
#   Linux   -> dist/Qwen Server/Qwen Server
#
# 注意：PyInstaller 不支持交叉编译，必须在目标平台上各自构建。
#
# 国内网络可先设置镜像加速：
#   export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$HERE/.." && pwd)"
cd "$APP_DIR"

# ── 找一个可用的 python ──
PY=""
for c in "${QWEN_DESKTOP_PYTHON:-}" python3 /usr/local/bin/python3 \
         /opt/homebrew/bin/python3 /usr/bin/python3; do
  [ -n "$c" ] || continue
  command -v "$c" >/dev/null 2>&1 || continue
  PY="$c"
  break
done
[ -n "$PY" ] || { echo "✗ 找不到 python3" >&2; exit 1; }

echo "→ 使用解释器：$("$PY" -c 'import sys;print(sys.executable)')"

# ── 准备依赖 ──
if ! "$PY" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "→ 安装 PyInstaller"
  PIP_ARGS=()
  [ -n "${PIP_INDEX_URL:-}" ] || PIP_ARGS+=(-i "https://pypi.tuna.tsinghua.edu.cn/simple")
  "$PY" -m pip install --upgrade pyinstaller "${PIP_ARGS[@]}"
fi

# ── 构建 ──
echo "→ 开始打包（首次约需 1-3 分钟）"
rm -rf build dist "Qwen Server.spec"

EXTRA=()
if [ "$(uname -s)" = "Darwin" ]; then
  EXTRA+=(--windowed)                 # 生成 .app bundle
  [ -f "$HERE/AppIcon.icns" ] && EXTRA+=(--icon "$HERE/AppIcon.icns")
else
  EXTRA+=(--noconsole)
  [ -f "$HERE/icon_1024.png" ] && EXTRA+=(--icon "$HERE/icon_1024.png")
fi

"$PY" -m PyInstaller \
  --noconfirm --clean --onedir \
  --name "Qwen Server" \
  "${EXTRA[@]}" \
  --hidden-import qwencore.paths \
  --hidden-import qwencore.models \
  --hidden-import qwencore.config \
  --hidden-import qwencore.server \
  --hidden-import qwencore.theme \
  qwen_desktop.py

echo
echo "✓ 打包完成，产物在：$APP_DIR/dist/"
ls -1 dist/ 2>/dev/null || true
