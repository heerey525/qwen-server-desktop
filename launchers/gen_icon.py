#!/usr/bin/env python3
"""生成应用图标（纯标准库，不依赖 Pillow）。

产出 1024×1024 的 PNG：深色圆角底 + 三条堆叠横条（象征多层服务）+ 状态点。
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

SIZE = 1024
SS = 3  # 超采样倍数，用于抗锯齿

# 配色
BG_TOP = (0x18, 0x25, 0x38)
BG_BOTTOM = (0x0A, 0x11, 0x1B)
BAR = (0x4D, 0xA3, 0xFF)
BAR_DIM = (0x2C, 0x6B, 0xB0)
DOT = (0x34, 0xC7, 0x59)


def in_round_rect(px: float, py: float, x0: float, y0: float,
                  x1: float, y1: float, r: float) -> bool:
    """点是否落在圆角矩形内（标准距离场做法）。"""
    cx = min(max(px, x0 + r), x1 - r)
    cy = min(max(py, y0 + r), y1 - r)
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= r * r


def in_circle(px: float, py: float, cx: float, cy: float, r: float) -> bool:
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= r * r


def mix(a, b, t: float):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def render() -> bytes:
    s = SIZE
    radius = s * 0.2237          # macOS 圆角比例
    margin = s * 0.20            # 内容区留白

    # 三条横条的几何参数
    bar_x0 = margin
    bar_x1 = s - margin
    bar_h = s * 0.088
    gap = s * 0.055
    bars_top = s * 0.275
    bar_radius = bar_h / 2

    # 状态点（右下角，压在第三条横条右端）
    dot_r = s * 0.075
    dot_cx = bar_x1 - dot_r * 0.55
    dot_cy = bars_top + (bar_h + gap) * 2 + bar_h / 2

    rows = []
    inv = 1.0 / (SS * SS)
    for y in range(s):
        row = bytearray()
        row.append(0)  # PNG 每行的 filter 字节
        for x in range(s):
            r_acc = g_acc = b_acc = a_acc = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    px = x + (sx + 0.5) / SS
                    py = y + (sy + 0.5) / SS

                    if not in_round_rect(px, py, 0, 0, s, s, radius):
                        continue  # 圆角外透明

                    # 背景竖直渐变
                    t = py / s
                    color = mix(BG_TOP, BG_BOTTOM, t)
                    alpha = 1.0

                    # 横条
                    for i in range(3):
                        by0 = bars_top + (bar_h + gap) * i
                        by1 = by0 + bar_h
                        if in_round_rect(px, py, bar_x0, by0, bar_x1, by1, bar_radius):
                            color = BAR if i != 1 else BAR_DIM
                            break

                    # 状态点
                    if in_circle(px, py, dot_cx, dot_cy, dot_r):
                        color = DOT

                    r_acc += color[0] * alpha
                    g_acc += color[1] * alpha
                    b_acc += color[2] * alpha
                    a_acc += alpha

            if a_acc <= 0:
                row += b"\x00\x00\x00\x00"
            else:
                n = a_acc * inv
                # 预乘还原
                row += bytes((
                    min(255, int(r_acc * inv)),
                    min(255, int(g_acc * inv)),
                    min(255, int(b_acc * inv)),
                    min(255, int(n * 255)),
                ))
        rows.append(bytes(row))
    return b"".join(rows)


def write_png(path: Path, raw: bytes, size: int) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("icon.png")
    size = int(sys.argv[2]) if len(sys.argv) > 2 else SIZE
    raw = render()
    write_png(out, raw, size)
    print("已生成 %s (%d×%d, %.1f KB)" % (out, size, size, out.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
