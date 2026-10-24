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
  · 全部角色成年；预警从出处条目继承，带 ⚠️ 的卡必须带安全框架（K 项会查）
  · 不含任何藏书原文

卡的内容在 scene_cards_data/ 包里（cards_core 为首轮 30 张，cards_31…cards_45
为各新族，cards_fill_* 为存量补卡）。**改卡改那些表，不要手改 JSON。**

用法：python3 build_scene_cards.py
"""

import json
import re
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

# 预警不在规训类时用这一段（成瘾、心理疾病、生育、暴力……），
# SAFE_BLOCK 里的「规矩与责罚」套在这些卡上是错位的。
GENERIC_SAFE = """

【边界】
双方均为成年人。本场景为虚构创作，涉及的现实议题只作场景，不提供可照做的细节或指导。
若 {{user}} 表示停止或不适，立刻退出该情境并转入日常。"""

# 与 check_compliance.py 的 CARD_RISK 同口径：带这些预警的卡挂 SAFE_BLOCK。
KINK_RISK = ("⚠️主奴", "⚠️非自愿", "⚠️训诫", "⚠️囚禁", "⚠️重口", "⚠️调教")


from scene_cards_data import ALL_CARDS as CARDS, ALL_DETAILS as DETAILS

# ── 预警从出处条目继承 ────────────────────────────────────────────
# 卡的 warn 原先全靠数据模块手填。2026-10 通读发现 121 张卡的出处条目带 ⚠️
# 而卡上没有，四张直接标了 E；check_compliance 的 K 项是在 JSON 里找 ⚠️ 字串，
# 卡里一个 ⚠️ 都没有，它就永远不触发。现在预警以桥段条目的分级行为准，
# 数据模块里的 warn 只能加、不能减。
VIGNETTE = LIB / "14-桥段库"
WARN_TOKEN = re.compile(r"⚠️[^\s｜（(，,、）)]+")


def _vignette_grades():
    """{族名: {条目名: 分级行}}，族名去掉文件名的编号。"""
    out = {}
    for p in VIGNETTE.glob("[0-9][0-9]-*.md"):
        if p.name.startswith("00-"):
            continue
        t = p.read_text(encoding="utf-8")
        out[p.stem.split("-", 1)[1]] = {
            m.group(1).strip(): m.group(2) for m in re.finditer(
                r"^## [一二三四五六七八九十]+ · (.+)\n\n(`[TMEG/]+` ｜ .*)$", t, re.M)}
    return out


GRADES = _vignette_grades()


def src_warnings(src):
    """按卡的 src（「族 · 条目」，族名前可带编号）取出处条目的 ⚠️ 标签。

    找不到出处返回 None，由 main() 统一报出来。同族重名的条目在卡名里
    带「（族名）」后缀，查的时候去掉再试一次。
    """
    fam, _, title = src.partition(" · ")
    entries = GRADES.get(re.sub(r"^\d+-", "", fam.strip()))
    if entries is None:
        return None
    title = title.strip()
    for t in (title, re.sub(r"（[^）]*）$", "", title)):
        if t in entries:
            return WARN_TOKEN.findall(entries[t])
    return None


def build(c):
    is_male = c["dir"] == "AI男"
    ai_role = "男主" if is_male else "女主"
    user_role = "女主" if is_male else "男主"
    tags = src_warnings(c["src"]) or []
    extra = c.get("sys_extra", "")
    if c.get("warn") or any(t in KINK_RISK for t in tags):
        safe = SAFE_BLOCK
    elif tags:
        safe = GENERIC_SAFE
    else:
        safe = ""
    # 族级 sys_extra 已经写了雷点的不重复
    lei = (f"\n\n【雷点】\n本卡出自带 {' '.join(tags)} 预警的桥段，雷者勿入。"
           if tags and "【雷点】" not in extra else "")

    desc = (
        f"> 扮演方向：AI 扮{ai_role}（{c['who'].split('，')[0]}），"
        f"{{{{user}}}} 扮{user_role}。\n"
        f"> 桥段出处：{c['src']}｜分级 {c['rating']}｜{c['tag']}\n"
        + (f"> 预警：{' '.join(tags)}\n" if tags else "") + "\n"
        f"【{ai_role}是谁】\n{c['who']}\n\n"
        f"【他的核心】\n{c['core']}\n\n"
        f"【此刻的场面】\n{c['setting']}\n\n"
        f"【可取用的细节】\n{DETAILS[c['name']]}\n\n"
        f"【下一拍往哪走】\n{c['beat']}"
    )
    sysp = with_deai(SYS_COMMON + safe + lei + extra)
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
    # 闸门写成「必须做到」：开局卡只架开场，按元层级降级最高标 M；
    # 每张卡都要能追到出处条目，不然它的预警就无从继承。
    bad_e = [c["name"] for c in CARDS if c["rating"] == "E"]
    lost = [c["name"] for c in CARDS if src_warnings(c["src"]) is None]
    if bad_e or lost:
        raise SystemExit("情景卡未生成：\n"
                         + (f"  标了 E 级（开局卡最高 M）：{'、'.join(bad_e)}\n" if bad_e else "")
                         + (f"  出处条目找不到：{'、'.join(lost)}\n" if lost else ""))
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
