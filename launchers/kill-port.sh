#!/usr/bin/env bash
#
# 按端口定位并终止进程 —— qwen-server / opencodex 的"手动拔电源"
#
#   ./kill-port.sh 3098              # 优雅终止占用 3098 的进程
#   ./kill-port.sh 10100 -f -y       # 强杀 10100，不询问
#   ./kill-port.sh --all             # 依次处理 3098 与 10100
#   ./kill-port.sh 3098 --list       # 只看谁占着，不动手
#
# 先发 SIGTERM 给机会优雅退出，超时才升级为 SIGKILL。

set -uo pipefail

# 预设端口：3098 = qwen-server，10100 = opencodex
DEFAULT_PORTS=(3098 10100)

FORCE=0
ASSUME_YES=0
LIST_ONLY=0
USE_ALL=0
PORTS=()

usage() {
  cat <<'MSG'
按端口定位并终止进程

用法:
  kill-port.sh <端口> [选项]       终止占用该端口的进程
  kill-port.sh --all [选项]        处理预设端口（3098 qwen-server / 10100 opencodex）

选项:
  -f, --force    跳过优雅等待，直接强杀 (SIGKILL)
  -y, --yes      不询问，直接执行
  -l, --list     只列出占用情况，不做任何终止
  -h, --help     显示本帮助

示例:
  kill-port.sh 3098                 # 优雅终止占用 3098 的进程
  kill-port.sh 10100 -f -y          # 强杀 10100，不询问
  kill-port.sh --all                # 依次处理 3098 与 10100
  kill-port.sh 3098 --list          # 只看谁占着 3098
MSG
}

# ── 参数解析 ────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    -f|--force) FORCE=1 ;;
    -y|--yes)   ASSUME_YES=1 ;;
    -l|--list)  LIST_ONLY=1 ;;
    -h|--help)  usage; exit 0 ;;
    --all)      USE_ALL=1 ;;
    -*)         echo "未知选项：$1" >&2; echo >&2; usage >&2; exit 2 ;;
    *)          PORTS+=("$1") ;;
  esac
  shift
done

if [ "$USE_ALL" = "1" ]; then
  PORTS=("${DEFAULT_PORTS[@]}")
fi

if [ ${#PORTS[@]} -eq 0 ]; then
  usage
  exit 2
fi

for p in "${PORTS[@]}"; do
  case "$p" in
    ''|*[!0-9]*) echo "端口必须是数字：$p" >&2; exit 2 ;;
  esac
done

# ── 平台探测 ────────────────────────────────────────────────────────
is_windows() {
  case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

# ── 按端口找进程：输出 "PID|进程名" ─────────────────────────────────
# 优先用 lsof 的机器可读输出（-F pc），一次拿到 PID 和命令名，
# 避免依赖 ps —— 部分受限环境里 ps 会被拦下，只能拿到"未知进程"。
find_entries() {
  local port="$1"

  if is_windows; then
    netstat -ano -p TCP 2>/dev/null \
      | awk -v suffix=":$port" '
          $1 ~ /^TCP/ && $2 ~ suffix "$" && $4 ~ /LISTEN/ { print $5 }
        ' \
      | sort -u | while read -r pid; do
          [ -n "$pid" ] && printf '%s|%s\n' "$pid" "$(proc_name "$pid")"
        done
    return
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -F pc 2>/dev/null | awk '
      /^p/ { pid = substr($0, 2); next }
      /^c/ { if (pid != "") { print pid "|" substr($0, 2); pid = "" } }
    '
    return
  fi

  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$port" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' | sort -u \
      | while read -r pid; do printf '%s|%s\n' "$pid" "$(proc_name "$pid")"; done
    return
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -lptnH "sport = :$port" 2>/dev/null \
      | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u \
      | while read -r pid; do printf '%s|%s\n' "$pid" "$(proc_name "$pid")"; done
  fi
}

# ── 进程名 ──────────────────────────────────────────────────────────
proc_name() {
  local pid="$1" name
  if is_windows; then
    name=$(tasklist //FI "PID eq $pid" //FO CSV //NH 2>/dev/null | head -1 | cut -d, -f1 | tr -d '"')
  else
    name=$(ps -p "$pid" -o comm= 2>/dev/null)
    [ -n "$name" ] && name=$(basename "$name")
  fi
  printf '%s' "${name:-未知进程}"
}

# ── 终止与等待 ──────────────────────────────────────────────────────
kill_one() {
  local pid="$1" hard="$2"
  if is_windows; then
    if [ "$hard" = "1" ]; then
      taskkill //PID "$pid" //F //T >/dev/null 2>&1
    else
      taskkill //PID "$pid" >/dev/null 2>&1
    fi
  else
    if [ "$hard" = "1" ]; then
      kill -9 "$pid" 2>/dev/null
    else
      kill -TERM "$pid" 2>/dev/null
    fi
  fi
}

is_alive() {
  local pid="$1"
  if is_windows; then
    tasklist //FI "PID eq $pid" //FO CSV //NH 2>/dev/null | grep -q "$pid"
  else
    kill -0 "$pid" 2>/dev/null
  fi
}

wait_gone() {
  local pid="$1" seconds="${2:-6}" ticks=0 limit
  limit=$((seconds * 10))
  while [ "$ticks" -lt "$limit" ]; do
    is_alive "$pid" || return 0
    sleep 0.1
    ticks=$((ticks + 1))
  done
  return 1
}

# ── 单个端口处理 ────────────────────────────────────────────────────
handle_port() {
  local port="$1"
  echo "── 端口 $port ──────────────────────────────"

  local entries
  entries=$(find_entries "$port")

  if [ -z "$entries" ]; then
    echo "  空闲，无需处理"
    return 0
  fi

  echo "  占用进程："
  local pid name
  while IFS='|' read -r pid name; do
    [ -n "$pid" ] || continue
    printf "    PID %-8s %s\n" "$pid" "${name:-未知进程}"
  done <<< "$entries"

  local pids
  pids=$(printf '%s\n' "$entries" | cut -d'|' -f1 | sort -u)

  if [ "$LIST_ONLY" = "1" ]; then
    echo "  （--list 模式，未做任何改动）"
    return 0
  fi

  if [ "$ASSUME_YES" != "1" ]; then
    if [ -t 0 ]; then
      printf "  确认终止以上进程？[y/N] "
      read -r answer
      case "$answer" in
        y|Y|yes|YES) ;;
        *) echo "  已跳过"; return 0 ;;
      esac
    else
      echo "  非交互环境，需要显式加 -y 才会执行" >&2
      return 3
    fi
  fi

  # 第一轮：优雅终止
  for pid in $pids; do
    kill_one "$pid" "$FORCE"
  done

  if [ "$FORCE" = "1" ]; then
    sleep 0.4
  fi

  # 复核，没走的升级为强杀
  local stubborn=""
  for pid in $pids; do
    if ! wait_gone "$pid" 6; then
      stubborn="$stubborn $pid"
    fi
  done

  if [ -n "$stubborn" ]; then
    echo "  以下进程未响应 TERM，升级为强杀：$stubborn"
    for pid in $stubborn; do
      kill_one "$pid" 1
    done
    sleep 0.4
  fi

  # 最终确认
  local left
  left=$(find_entries "$port" | cut -d'|' -f1 | sort -u | tr '\n' ' ')
  left="${left% }"
  if [ -z "$left" ]; then
    echo "  ✓ 端口 $port 已释放"
    return 0
  else
    echo "  ✗ 端口 $port 仍被占用：$left" >&2
    echo "    可能需要管理员权限（sudo）" >&2
    return 1
  fi
}

# ── 主流程 ──────────────────────────────────────────────────────────
exit_code=0
for port in "${PORTS[@]}"; do
  handle_port "$port" || exit_code=$?
  echo
done

exit "$exit_code"
