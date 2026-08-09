#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引文剥离：ai_taste 与 check_compliance 共用一份。

为什么单独成模块：两边原先各写一条 `[「『“][^」』”\n]{6,}[」』”]`，
遇到**嵌套引号**会提前截断——

    「他的柔软是『玩具性的』，对关系不是依恋，是猎奇。」

正则从「起步，撞见第一个 』 就收工，只剥掉前半截，
后半截「不是依恋，是猎奇」留在原地，被当成本库自己写的机器腔。

这个盲区先前出现过一次，当时是给那一行加行内豁免绕过去的。
绕过去的代价是：同样的碎片在别处照样漏，而且没人知道它漏了。
"""

import re

# 外层「」允许内含一层『』；另收独立的『』与“”
QUOTED = re.compile(
    r"「(?:[^「」\n]|『[^『』\n]*』)*」"
    r"|『(?:[^『』\n]|「[^「」\n]*」)*』"
    r"|“(?:[^“”\n]|‘[^‘’\n]*’)*”")


def strip_quotes(t: str, min_cn: int = 6) -> str:
    """剥掉成句引文。短于 min_cn 汉字的当术语标记，保留。"""
    def sub(m):
        inner = m.group(0)[1:-1]
        return "" if len(re.findall(r"[一-鿿]", inner)) >= min_cn else m.group(0)
    return QUOTED.sub(sub, t)
