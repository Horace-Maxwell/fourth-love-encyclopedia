#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全库统一的路径解析。所有脚本一律从这里取路径，不写死。

为什么：脚本里原先硬编码 `/Users/horacedong/Desktop/GB/...`，泄露用户名与
目录结构，别人 clone 下来也跑不了。

解析顺序：
  LIB（本库根目录）   环境变量 GB_LIB   → 否则按本文件位置上溯一级
  CORPUS（藏书目录）  环境变量 GB_CORPUS → 否则 LIB 的同级目录 `素材语料`

藏书目录不随仓库发布（见 00-编纂规约/06-发布风险评估）。需要跑语料相关脚本时：

    export GB_CORPUS=/path/to/your/corpus
"""

import os
from pathlib import Path

LIB = Path(os.environ.get("GB_LIB") or Path(__file__).resolve().parent.parent)
CORPUS = Path(os.environ.get("GB_CORPUS") or LIB.parent / "素材语料")

INDEX_DIR = LIB / "10-藏书索引"
JSONL = INDEX_DIR / "_语料库.jsonl"
CARDS_DIR = LIB / "09-拆解卡"
EXPORT_DIR = LIB / "12-导出"
TEMPLATE_DIR = LIB / "11-模板包"


def require_corpus():
    """需要藏书目录的脚本先调这个，给出可操作的报错而不是 FileNotFoundError。"""
    if not CORPUS.exists():
        raise SystemExit(
            f"找不到藏书目录：{CORPUS}\n"
            "藏书不随本仓库发布。请设置环境变量指向你自己的语料目录：\n"
            "    export GB_CORPUS=/path/to/your/corpus\n"
            "只使用本库的分析结果（不重跑统计）则无需藏书目录。")


if __name__ == "__main__":
    print(f"LIB    = {LIB}")
    print(f"CORPUS = {CORPUS}  {'（存在）' if CORPUS.exists() else '（不存在）'}")
