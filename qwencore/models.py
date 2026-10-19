"""模型目录扫描与别名表。

别名语义严格对齐 ~/.local/bin/qwen-server，避免图形界面与命令行行为漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import paths

# 未登记模型的兜底上下文。必须 >= 64000，
# 否则 Hermes Agent 的辅助压缩模型会拒绝使用。
CTX_UNKNOWN = 65536
# router 模式统一上下文：兼顾 Hermes 门槛与多模型驻留时的内存占用
CTX_ROUTER = 65536

# 别名 -> (文件名, 推荐上下文, /v1/models 上报名, 说明)
ALIAS_TABLE: Dict[str, tuple] = {
    "9b":      ("Qwen3.5-9B-Q4_K_M.gguf",           131072, "Qwen3.5-9B",         "主力模型，可吃满上下文"),
    "unsloth": ("Qwen3.5-9B-Q4_0-unsloth.gguf",     131072, "Qwen3.5-9B-unsloth", "Q4_0 量化版"),
    "4b":      ("Qwen3.5-4B-Q4_K_M.gguf",           131072, "Qwen3.5-4B",         "速度优先"),
    "14b":     ("Qwen2.5-14B-Instruct-Q4_K_M.gguf",  16384, "Qwen2.5-14B",        "上下文需收着点，否则 swap"),
    "gemma":   ("gemma-4-12b-it-Q4_K_M.gguf",        32768, "Gemma-4-12B",        "多模态，自动挂视觉投影"),
    "spark":   ("Spark-X2.5-4B-Q4_K_M.gguf",        131072, "Spark-X2.5-4B",      "混合注意力，KV 极省"),
}

# 别名 -> 视觉投影文件（存在则自动挂载）
MMPROJ_TABLE: Dict[str, str] = {
    "gemma": "gemma-4-12b-mmproj-F16.gguf",
}

_FILE_TO_ALIAS: Dict[str, str] = {v[0]: k for k, v in ALIAS_TABLE.items()}


@dataclass
class ModelInfo:
    """一个可用的 .gguf 模型。"""

    filename: str
    path: Path
    size_bytes: int
    alias: Optional[str] = None
    api_name: Optional[str] = None
    recommended_ctx: int = CTX_UNKNOWN
    mmproj: Optional[Path] = None
    note: str = ""

    @property
    def size_text(self) -> str:
        return paths.human_size(self.size_bytes)

    @property
    def is_multimodal(self) -> bool:
        return self.mmproj is not None

    @property
    def label(self) -> str:
        """下拉框里显示的一行。"""
        prefix = ("%s  ·  " % self.alias) if self.alias else ""
        tail = "  [视觉]" if self.is_multimodal else ""
        return "%s%s  (%s)%s" % (prefix, self.filename, self.size_text, tail)

    @property
    def detail(self) -> str:
        parts = ["上下文 %s" % self.recommended_ctx]
        if self.api_name:
            parts.append("API 名 %s" % self.api_name)
        if self.note:
            parts.append(self.note)
        return "  ·  ".join(parts)


def scan_models(models_dir) -> List[ModelInfo]:
    """扫描目录下所有 .gguf（跳过 mmproj），返回按名称排序的列表。"""
    root = Path(models_dir).expanduser()
    if not root.is_dir():
        return []

    # 先收集视觉投影文件，供配对使用
    mmproj_files: Dict[str, Path] = {}
    for f in root.glob("*.gguf"):
        if "mmproj" in f.name.lower():
            mmproj_files[f.name] = f

    result: List[ModelInfo] = []
    for f in sorted(root.glob("*.gguf"), key=lambda p: p.name.lower()):
        if "mmproj" in f.name.lower():
            continue
        try:
            size = f.stat().st_size
        except OSError:
            size = 0

        alias = _FILE_TO_ALIAS.get(f.name)
        info = ModelInfo(filename=f.name, path=f, size_bytes=size)

        if alias:
            _, ctx, api_name, note = ALIAS_TABLE[alias]
            info.alias = alias
            info.api_name = api_name
            info.recommended_ctx = ctx
            info.note = note
            mmproj_name = MMPROJ_TABLE.get(alias)
            if mmproj_name and mmproj_name in mmproj_files:
                info.mmproj = mmproj_files[mmproj_name]
        else:
            info.recommended_ctx = CTX_UNKNOWN

        result.append(info)

    # 有别名的排前面，再按体积升序（小的通常更快）
    result.sort(key=lambda m: (0 if m.alias else 1, m.size_bytes))
    return result


def find_model(models_dir, filename: str) -> Optional[ModelInfo]:
    for m in scan_models(models_dir):
        if m.filename == filename:
            return m
    return None


def known_aliases() -> List[str]:
    return sorted(ALIAS_TABLE.keys())
