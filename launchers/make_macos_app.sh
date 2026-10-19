#!/usr/bin/env bash
#
# 生成 macOS 应用包：Qwen Server.app
#
#   ./make_macos_app.sh             只在项目目录里生成 .app
#   ./make_macos_app.sh --install   额外复制一份到 /Applications
#
# 生成的是本地未签名应用。因为是本机产物、不带 quarantine 属性，
# 双击即可运行，不会被 Gatekeeper 拦。

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$HERE/.." && pwd)"
BUNDLE_NAME="Qwen Server"
BUNDLE="$APP_DIR/${BUNDLE_NAME}.app"
DO_INSTALL=0
[ "${1:-}" = "--install" ] && DO_INSTALL=1

# ── 选一个 python 来生成图标（只用标准库）──
PY=""
for c in "${QWEN_DESKTOP_PYTHON:-}" /usr/bin/python3 /usr/local/bin/python3 \
         /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/3.8/bin/python3; do
  [ -n "$c" ] || continue
  [ -x "$c" ] || continue
  PY="$c"
  break
done
[ -n "$PY" ] || { echo "✗ 找不到 python3（仅用于生成图标）" >&2; exit 1; }

echo "→ 生成图标（使用 ${PY}）"
ICON_PNG="$HERE/icon_1024.png"
ICNS="$HERE/AppIcon.icns"

if [ -f "$ICNS" ] && [ -f "$ICON_PNG" ] && [ "${1:-}" != "--force-icon" ]; then
  echo "  复用已有图标（加 --force-icon 可强制重建）"
else
  "$PY" "$HERE/gen_icon.py" "$ICON_PNG" 1024

  ICONSET="$HERE/AppIcon.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  while read -r px name; do
    [ -n "$px" ] || continue
    sips -z "$px" "$px" "$ICON_PNG" --out "$ICONSET/icon_${name}.png" >/dev/null 2>&1
  done <<'SPECS'
16 16x16
32 16x16@2x
32 32x32
64 32x32@2x
128 128x128
256 128x128@2x
256 256x256
512 256x256@2x
512 512x512
1024 512x512@2x
SPECS

  if iconutil -c icns "$ICONSET" -o "$ICNS" >/dev/null 2>&1; then
    echo "→ 图标已生成：$(basename "$ICNS")"
  else
    echo "⚠ iconutil 失败，将使用系统默认图标"
    ICNS=""
  fi
fi

# ── 组装 bundle ──
echo "→ 组装 ${BUNDLE_NAME}.app"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
[ -n "$ICNS" ] && cp "$ICNS" "$BUNDLE/Contents/Resources/AppIcon.icns"

printf 'APPL????' > "$BUNDLE/Contents/PkgInfo"

cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>              <string>${BUNDLE_NAME}</string>
    <key>CFBundleDisplayName</key>       <string>${BUNDLE_NAME}</string>
    <key>CFBundleIdentifier</key>        <string>local.qwen.desktop</string>
    <key>CFBundleExecutable</key>        <string>QwenServer</string>
    <key>CFBundleIconFile</key>          <string>AppIcon</string>
    <key>CFBundlePackageType</key>       <string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>CFBundleVersion</key>           <string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>    <string>10.15</string>
    <key>NSHighResolutionCapable</key>   <true/>
    <key>LSApplicationCategoryType</key> <string>public.app-category.developer-tools</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
</dict>
</plist>
PLIST

# 启动脚本：路径在生成时写死，避免 Finder 环境下 PATH 过窄导致探测失败。
# "\$@" 必须转发，否则命令行参数会被吞掉（连 --check 都进不来）。
cat > "$BUNDLE/Contents/MacOS/QwenServer" <<LAUNCH
#!/bin/bash
exec "${HERE}/launch.sh" "\$@"
LAUNCH
chmod +x "$BUNDLE/Contents/MacOS/QwenServer"

xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null || true

echo "✓ 已生成：$BUNDLE"

if [ "$DO_INSTALL" = "1" ]; then
  DEST="/Applications/${BUNDLE_NAME}.app"
  echo "→ 安装到 /Applications（可能需要授权）"
  rm -rf "$DEST"
  cp -R "$BUNDLE" "$DEST"
  xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
  echo "✓ 已安装：$DEST"
  echo "  现在可以直接在「启动台」或「应用程序」里双击打开了。"
else
  echo "  提示：加上 --install 参数可自动装到「应用程序」文件夹。"
fi
