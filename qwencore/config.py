"""配置持久化。

配置文件放在平台约定的用户配置目录下，首次启动自动写入默认值。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from . import paths

CONFIG_VERSION = 1


@dataclass
class Config:
    """界面上的全部可调项。"""

    # 运行模式：router（多模型按需加载）| single（单模型）
    mode: str = "router"
    # single 模式下选中的模型文件名
    model_file: str = ""

    # 路径
    models_dir: str = ""
    llama_server: str = ""
    mcp_config: str = ""

    # 网络
    host: str = "127.0.0.1"
    port: int = 3098

    # 推理参数
    ctx: int = 65536
    ngl: int = 99
    models_max: int = 1
    use_flash_attn: bool = True
    kv_cache_type: str = "q4_0"
    use_jinja: bool = True
    parallel: int = 1
    extra_args: str = ""

    # 界面行为
    auto_open_browser: bool = False
    auto_start: bool = False

    version: int = CONFIG_VERSION

    # ── 读写 ────────────────────────────────────────────────────────

    @classmethod
    def load(cls) -> "Config":
        path = paths.config_file()
        if not path.is_file():
            cfg = cls()
            cfg.apply_defaults()
            cfg.save()
            return cfg
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = cls()
            cfg.apply_defaults()
            return cfg
        if not isinstance(raw, dict):
            cfg = cls()
            cfg.apply_defaults()
            return cfg

        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in raw.items() if k in known}
        cfg = cls(**clean)
        cfg.apply_defaults()
        return cfg

    def apply_defaults(self) -> None:
        """补齐空路径，让首次启动即可用。"""
        if not self.models_dir:
            self.models_dir = str(paths.default_models_dir())
        if not self.llama_server:
            found = paths.find_llama_server()
            if found:
                self.llama_server = str(found)
        if not self.mcp_config:
            candidate = paths.home() / ".config" / "llama-mcp.json"
            if candidate.is_file():
                self.mcp_config = str(candidate)
        if self.mode not in ("router", "single"):
            self.mode = "router"

    def save(self) -> None:
        paths.ensure_dir(paths.default_config_dir())
        data = asdict(self)
        tmp = paths.config_file().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(paths.config_file())

    # ── 派生信息 ────────────────────────────────────────────────────

    def extra_arg_list(self) -> List[str]:
        """把附加参数文本框拆成参数列表（支持引号）。"""
        raw = (self.extra_args or "").strip()
        if not raw:
            return []
        try:
            import shlex
            return shlex.split(raw)
        except ValueError:
            return raw.split()

    @property
    def base_url(self) -> str:
        return "http://%s:%d" % (self.host, self.port)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
