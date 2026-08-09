#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长文本角色卡（沉浸式）——落 11-模板包/角色卡-长文本/。

与 11-模板包/角色卡/ 那 36 张的分工：
  角色卡        中文、六字段分列、六百字立一个人。给「快速起一场戏」用
  角色卡-长文本  英文 description 承载设定密度 + 中文 first_mes 承载现场感。
                 给「长期养一个角色」用——模型要反复回读的那部分越具体，
                 它跑偏得越慢

为什么 description 用英文：
  同样的信息密度，英文 token 更省，长上下文里衰减更慢；人名、开场白、
  角色说的话仍然是中文，读者看到的那一面不变。

为什么开场白用中文：
  first_mes 是给人看的第一眼，也是全卡唯一直接决定「读者要不要留下」的部分。

输出格式是 SillyTavern 扁平 v3（顶层字段与 data 双写），拖进酒馆即用；
同时保留 project 字段，供书房导入与本库导出复用。

卡的内容在 longform_cards_data/ 包里，一张卡一个模块。
**改卡改那些表，不要手改 JSON**——JSON 每次重跑全量重建。

用法：python3 build_longform_cards.py
"""

import json
import re
from pathlib import Path

from paths import LIB
from longform_cards_data import ALL_LONGFORM
from card_format import make_card, with_deai

OUT = LIB / "11-模板包" / "角色卡-长文本"
PROJECT = "第四爱百科"

# 全卡共用的扮演约束。写进 system_prompt，不写元评论、不夸自己。
SYS = """本场景为成年角色间的虚构创作。GB / 女攻男受：{{user}} 是关系中主导的一方。

【推进】
一次只推进一拍。先给动作与物件，再给情绪。不要用形容词代替动作。
角色的犹豫、逞强、说漏嘴要写出来，不要让他每句话都恰到好处。

【身体先于意识】
他的反应顺序是：身体动了 → 才意识到自己动了 → 才决定要不要掩饰。
不要跳过中间那一步。

【禁止】
不要替 {{user}} 决定情绪或动作。
不要总结、不要评论自己写得怎么样、不要问「你想怎么发展」。
不要一次给出三个选项。不要让他一路顺从到底——顺从是他选的，不是他没得选。"""

SAFE = """

【边界】
双方均为成年人，关系为自愿。
涉及权力交换的部分是虚构装置，不描写身体伤害，不提供可实施的细节。
若 {{user}} 表示停止或不适，立刻退出该情境并转入日常。
参照社群共识 SSC / RACK / PRICK：安全、理智、知情、可撤回。"""


def build(c):
    head = (f"> 扮演方向：AI 扮男主（{c['name']}），{{{{user}}}} 扮女主。"
            f"GB / 女攻男受。\n"
            f"> 原型：{c['archetype']}｜分级 {c['rating']}"
            + (f"｜预警 {c['warn']}" if c.get("warn") else "｜无预警") + "\n\n")
    data = {
        "name": c["name"],
        "description": head + c["description"].strip(),
        "personality": c.get("personality", ""),
        "scenario": c.get("scenario", ""),
        "mes_example": c.get("mes_example", ""),
        "system_prompt": with_deai(SYS + (SAFE if c.get("warn") else "")),
        "post_history_instructions": c.get("post_history", ""),
        "first_mes": c["first_mes"].strip(),
        "alternate_greetings": [g.strip() for g in c.get("alternate_greetings", [])],
        "tags": ["第四爱", "GB", "女攻男受", c["archetype"], c["tag"]],
        "creator_notes": c["notes"],
        "extensions": {"talkativeness": "0.5", "fav": False, "world": "",
                       "depth_prompt": {"prompt": c.get("depth_prompt", ""),
                                        "depth": 4, "role": "system"}},
    }
    return make_card(data)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    cn = lambda s: len(re.findall(r"[一-鿿]", s))
    for i, c in enumerate(ALL_LONGFORM, 1):
        d = build(c)
        short = re.split(r"[（(]", c["archetype"])[0].strip()
        fn = f"{i:02d}-{c['name']}-{short}.json"
        (OUT / fn).write_text(json.dumps(d, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        print(f"  {fn}｜设定 {len(c['description']):,} 字符"
              f"｜开场 {cn(c['first_mes'])} 汉字"
              f"｜备选开场 {len(c.get('alternate_greetings', []))} 条")
    print(f"生成 {len(ALL_LONGFORM)} 张长文本角色卡 → {OUT.relative_to(LIB)}")


if __name__ == "__main__":
    main()
