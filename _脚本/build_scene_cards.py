#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 14-桥段库 的高频条目生成情景开局卡，落 11-模板包/情景卡/。

情景卡与角色卡的分工：
  角色卡  给一个**人**：他是谁、他的核心矛盾、他怎么说话
  情景卡  给一个**时刻**：现在几点、桌上有什么、下一拍该发生什么

为什么要有情景卡：
  角色卡解决「跟谁演」，但用户仍要自己想「从哪开始」。
  桥段库的每一条都自带一个崩点，开局卡就架在崩点前一拍上，
  开场白一放出来，戏已经在走了。

设计约束：
  · 方向平衡：AI 扮男主 15 张 / AI 扮女主 15 张，两边读者各半
  · 提示词层不适用去 AI 化铁律（加粗是模型信号），但**元评论仍禁**——
    上一轮实测 18 张角色卡在 system_prompt 里有元评论，白占上下文
  · 全部角色成年；带 ⚠️ 的卡必须带安全框架（check_compliance K 项会查）
  · 不含任何藏书原文

卡的内容在 scene_cards_data/ 包里（cards_core 为首轮 30 张，cards_31…cards_45
为各新族，cards_fill_* 为存量补卡）。**改卡改那些表，不要手改 JSON。**

用法：python3 build_scene_cards.py
"""

import json
from pathlib import Path

from paths import LIB
from card_format import make_card, with_deai

OUT = LIB / "11-模板包" / "情景卡"
PROJECT = "第四爱百科"

# 共用的扮演约束。写进 system_prompt，不写元评论、不夸自己。
SYS_COMMON = """本场景为成年角色间的虚构创作。

【节奏】
一次只推进一拍。不要在一条回复里走完整场戏。
先给动作与物件，再给情绪。不要用形容词代替动作。

【时间的写法】
这一族的戏靠时间流逝推动，不靠冲突。用可重复的物质动作显示时间：
菜热了第几遍、灯亮了多久、手机点亮又熄掉。不要写「过了很久」。

【禁止】
不要替 {{user}} 决定情绪或动作。
不要总结、不要评论自己写得怎么样、不要问「你想怎么发展」。
不要一次给出三个选项。"""

SAFE_BLOCK = """

【边界】
双方均为成年人，关系为自愿。
本场景中的规矩与责罚是虚构装置，不描写身体伤害，不提供可实施的细节。
若 {{user}} 表示停止或不适，立刻退出该情境并转入日常。
参照社群共识 SSC / RACK / PRICK：安全、理智、知情、可撤回。"""


from scene_cards_data import ALL_CARDS as CARDS, ALL_DETAILS as DETAILS


def build(c):
    is_male = c["dir"] == "AI男"
    ai_role = "男主" if is_male else "女主"
    user_role = "女主" if is_male else "男主"
    warn = c.get("warn", False)

    desc = (
        f"> 扮演方向：AI 扮{ai_role}（{c['who'].split('，')[0]}），"
        f"{{{{user}}}} 扮{user_role}。\n"
        f"> 桥段出处：{c['src']}｜分级 {c['rating']}｜{c['tag']}\n\n"
        f"【{ai_role}是谁】\n{c['who']}\n\n"
        f"【他的核心】\n{c['core']}\n\n"
        f"【此刻的场面】\n{c['setting']}\n\n"
        f"【可取用的细节】\n{DETAILS[c['name']]}\n\n"
        f"【下一拍往哪走】\n{c['beat']}"
    )
    sysp = with_deai(SYS_COMMON + (SAFE_BLOCK if warn else "") + c.get("sys_extra", ""))
    return make_card({
        "name": c["name"],
        "description": desc,
        "personality": c["core"],
        "scenario": c["setting"],
        "mes_example": "<START>\n" + c["ex"],
        "system_prompt": sysp,
        "first_mes": c["first"],
        "tags": ["第四爱", "桥段", c["tag"].split(" · ")[1],
                 "AI扮男主" if is_male else "AI扮女主"],
        "creator_notes": f"由 {c['src']} 生成。开局架在崩点前一拍。",
    })


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    m = f = 0
    for i, c in enumerate(CARDS, 1):
        d = build(c)
        is_male = c["dir"] == "AI男"
        m += is_male
        f += not is_male
        fn = f"{i:03d}-{'AI扮男主' if is_male else 'AI扮女主'}-{c['name']}.json"
        (OUT / fn).write_text(json.dumps(d, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"生成 {len(CARDS)} 张情景卡 → {OUT.relative_to(LIB)}")
    print(f"  AI 扮男主 {m} 张（面向四爱女）｜AI 扮女主 {f} 张（面向四爱男）")


if __name__ == "__main__":
    main()
