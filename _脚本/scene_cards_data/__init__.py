#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情景卡数据包：每个 cards_*.py 模块提供 CARDS（列表）与 DETAILS（字典）。

为什么拆包：卡涨到几百张后，单文件既翻不动，也没法多人/多包并行补卡。
JSON 仍然全部由 build_scene_cards.py 生成——**改卡改这里的表，不要手改 JSON**。
模块按文件名排序聚合，卡的全局序号由聚合顺序决定。
"""

import importlib
import pkgutil

ALL_CARDS, ALL_DETAILS = [], {}
for m in sorted(m.name for m in pkgutil.iter_modules(__path__)
                if m.name.startswith("cards_")):
    mod = importlib.import_module(f".{m}", __package__)
    ALL_CARDS.extend(mod.CARDS)
    for k, v in getattr(mod, "DETAILS", {}).items():
        if k in ALL_DETAILS and v != ALL_DETAILS[k]:
            raise SystemExit(f"DETAILS 键冲突：{k}（来自 {m}，与先前模块不一致）")
        ALL_DETAILS[k] = v
