#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长文本角色卡数据包：每个 card_*.py 模块提供一个 CARD 字典。

一张卡一个模块，便于并行补卡与单卡改写。模块按文件名排序聚合，
卡的编号由聚合顺序决定（改名会改编号，链接指向文件名而非编号即可）。

CARD 必填：name / archetype / rating / tag / description / first_mes / notes
CARD 选填：warn / personality / scenario / mes_example / alternate_greetings /
          depth_prompt / post_history
"""

import importlib
import pkgutil

ALL_LONGFORM = []
for _m in sorted(m.name for m in pkgutil.iter_modules(__path__)
                 if m.name.startswith("card_")):
    _mod = importlib.import_module(f".{_m}", __package__)
    ALL_LONGFORM.append(_mod.CARD)
