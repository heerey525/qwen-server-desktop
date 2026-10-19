#!/usr/bin/env bash
#
# 把 Qwen Server Desktop 安装到 Linux 桌面环境
#
#   ./install_linux.sh
#
# 会在 ~/.local/share/applications 下创建菜单项，
# 并在 ~/.local/bin 下放一个可执行的启动脚本。

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$HERE/.." && pwd)"

BIN_DIR="$HOME/.local/bin"
APP_SHARE="$HOME/.local/share/applications"

mkdir -p "$BIN_DIR" "$APP_SHARE"

# 启动脚本
cat > "$BIN_DIR/qwen-server-desktop" <<EOF
#!/usr/bin/env bash
exec "${HERE}/launch.sh" "\$@"
EOF
chmod +x "$BIN_DIR/qwen-server-desktop"

# 桌面菜单项
sed "s|^Exec=.*|Exec=${BIN_DIR}/qwen-server-desktop|" \
    "$HERE/qwen-server.desktop" > "$APP_SHARE/qwen-server-desktop.desktop"
chmod +x "$APP_SHARE/qwen-server-desktop.desktop"

# 刷新菜单缓存
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_SHARE" >/dev/null 2>&1 || true
fi

echo "✓ 已安装"
echo "  菜单项 : $APP_SHARE/qwen-server-desktop.desktop"
echo "  命令行 : $BIN_DIR/qwen-server-desktop"
echo
echo "如果菜单里没出现，确认 ~/.local/bin 在 PATH 中，或注销后重新登录。"
