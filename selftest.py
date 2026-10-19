#!/usr/bin/env python3
"""核心层无头自检：不启动图形界面，只验证路径探测、模型扫描与参数构建。

用法：
    python3 selftest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qwencore import config as cfgmod  # noqa: E402
from qwencore import models as modelsmod  # noqa: E402
from qwencore import paths, server  # noqa: E402


def line(title: str) -> None:
    print("\n" + "─" * 62)
    print(title)
    print("─" * 62)


def main() -> int:
    line("1. 平台与目录")
    print("  平台        : %s (%s)" % (paths.platform_label(), sys.platform))
    print("  Python      : %s" % sys.version.split()[0])
    print("  模型目录    : %s" % paths.default_models_dir())
    print("  配置目录    : %s" % paths.default_config_dir())
    print("  配置文件    : %s" % paths.config_file())
    print("  日志目录    : %s" % paths.default_log_dir())

    line("2. llama-server 探测")
    found = paths.find_llama_server()
    print("  命中        : %s" % (found or "✗ 未找到"))
    print("  候选顺序：")
    for p in paths.llama_server_candidates()[:8]:
        print("    [%s] %s" % ("✓" if p.is_file() else " ", p))

    line("3. 模型扫描")
    models_dir = paths.default_models_dir()
    items = modelsmod.scan_models(models_dir)
    if not items:
        print("  （%s 下没有可用的 .gguf）" % models_dir)
    for m in items:
        print("  %-34s %8s  别名=%-8s ctx=%-7s%s"
              % (m.filename, m.size_text, m.alias or "-", m.recommended_ctx,
                 "  [视觉]" if m.is_multimodal else ""))
    print("\n  合计 %d 个模型" % len(items))

    line("4. 参数构建")
    cfg = cfgmod.Config()
    cfg.apply_defaults()

    # Router 模式
    cfg.mode = "router"
    cfg.ctx = modelsmod.CTX_ROUTER
    argv = server.build_command(cfg)
    print("  [Router 模式]")
    print("    " + server.preview_command(argv))

    # 单模型模式
    if items:
        cfg.mode = "single"
        target = next((m for m in items if m.alias), items[0])
        cfg.ctx = target.recommended_ctx
        argv = server.build_command(cfg, target)
        print("\n  [单模型模式] %s" % target.filename)
        print("    " + server.preview_command(argv))

    line("5. 配置读写")
    print("  默认配置可序列化 : %s" % bool(cfg.to_dict()))
    print("  附加参数解析     : %r" % cfgmod.Config(extra_args="--verbose --threads 6").extra_arg_list())
    print("  base_url         : %s" % cfg.base_url)

    line("6. 端口探测与占用")
    for port, label in ((3098, "qwen-server"), (10100, "opencodex")):
        rows = server.describe_port(port)
        if rows:
            detail = "  ".join("PID %d %s" % (pid, name) for pid, name in rows)
        else:
            detail = "空闲"
        print("  %-6d %-12s %s" % (port, label, detail))
    print("\n  健康检查（3098）: %s" % server.is_healthy("127.0.0.1", 3098))
    print("  说明：终止操作请用界面上的「强制终止」面板，")
    print("        或命令行 launchers/kill-port.sh <端口>")

    print("\n自检完成。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
