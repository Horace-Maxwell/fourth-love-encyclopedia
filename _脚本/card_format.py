#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""角色卡的**唯一**格式出口。所有生成卡的脚本都从这里出，不各写各的。

为什么要有这个文件：
  库内 474 张卡曾经全部无法导入 SillyTavern。根因是卡被写成
      {"project": ..., "card": {"spec": ..., "data": {...}}}
  而那是**书房导入 API 的请求体格式**（见 12-导出/README.md），
  不是卡本身的格式。SillyTavern 认的是顶层的 spec/data（v2/v3）
  或顶层的扁平字段（v1）；顶层只有 project 与 card 两个陌生键时，
  它既读不到 spec 也读不到 name，直接判为无效卡。

  更要命的是这个错误**通过了交付验证**——当时只验了「JSON 可解析」。
  可解析不等于可导入。凡是给外部工具用的产物，验收判据必须是
  「那个工具真的能吃进去」，不是「它长得像那个格式」。

本模块同时输出三层，取最大兼容：
  · 顶层 spec/spec_version/data   —— v2/v3 导入器读这里
  · 顶层扁平 name/description/…   —— v1 与老导入器读这里
  · 顶层 project                  —— 书房导入用；ST 忽略不认识的键

用 chara_card_v2 而不是 v3：v2 是所有版本都认的最小公倍数，
本库的卡没有用到 v3 独有的特性（character_book 的资产、decorators 等）。
"""

import json
from pathlib import Path

PROJECT = "第四爱百科"

# v2 规范要求 data 里存在的全部键。缺键的卡在部分导入器上会静默丢字段，
# 所以一律补齐，宁可给空值。
V2_KEYS = ("name", "description", "personality", "scenario", "first_mes",
           "mes_example", "creator_notes", "system_prompt",
           "post_history_instructions", "alternate_greetings",
           "character_book", "tags", "creator", "character_version",
           "extensions")
# v1 扁平层要写哪些（老导入器只认这几个）
FLAT_KEYS = ("name", "description", "personality", "scenario",
             "first_mes", "mes_example")


def make_card(data: dict, project: str = PROJECT) -> dict:
    """把一份 data 包成可被 SillyTavern 直接导入的卡。"""
    d = dict(data)
    for k in V2_KEYS:
        if k not in d:
            d[k] = {"alternate_greetings": [], "tags": [],
                    "extensions": {}, "character_book": None}.get(k, "")
    d.setdefault("creator", project)
    d.setdefault("character_version", "1.0")

    card = {k: d[k] for k in FLAT_KEYS}
    card.update({
        "creatorcomment": d.get("creator_notes", ""),
        "avatar": "none",
        "talkativeness": "0.5",
        "fav": False,
        "tags": d.get("tags", []),
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": d,
        "project": project,      # 书房用；ST 会忽略
    })
    return card


def write_card(path: Path, data: dict, project: str = PROJECT) -> None:
    path.write_text(
        json.dumps(make_card(data, project), ensure_ascii=False, indent=2),
        encoding="utf-8")


def importable(obj: dict) -> tuple:
    """按 SillyTavern 的判定顺序检查一份 JSON 能不能被当成卡读进去。

    返回 (是否可导入, 说明)。检查器 K 项与交付验证都用它，
    保证「能导入」这件事有唯一判据，不靠人眼看格式像不像。
    """
    if not isinstance(obj, dict):
        return False, "顶层不是对象"
    spec = obj.get("spec")
    if spec in ("chara_card_v2", "chara_card_v3"):
        data = obj.get("data")
        if not isinstance(data, dict):
            return False, f"声明了 {spec} 但顶层没有 data 对象"
        if not data.get("name"):
            return False, "data.name 为空"
        if not data.get("first_mes"):
            return False, "data.first_mes 为空（导入后无开场白）"
        miss = [k for k in V2_KEYS if k not in data]
        if miss:
            return False, f"data 缺字段：{'/'.join(miss)}"
        return True, f"{spec} 可导入"
    # 没有 spec 时按 v1 读顶层扁平字段
    if obj.get("name") and obj.get("description"):
        return True, "v1 扁平格式可导入"
    return False, ("顶层既无 spec 也无 name/description"
                   f"（顶层键：{'/'.join(list(obj)[:6])}）")

# ── 去 AI 味约束：所有卡共用一份 ──
# 为什么写在这里：卡是这个库唯一「直接驱动 AI 生成文字」的产物。
# 库里的正文只要写好就行，卡不一样——它每次被调用都在生产新文本，
# 病是复制出去的。所以约束必须跟卡一起走。
#
# 条目来自 100 篇真人小说的实测（阈值见 ai_taste.py）与外部调研。
# 只放最硬的五条：**预设太长模型反而不跟随**，这一点 11-模板包/预设与正则
# 的 README 里有教训——十几条禁令同时生效，模型会写得畏首畏尾。
DEAI = """

【文字】
情绪不要点名。不写「他感到一阵委屈」，写他把碗放下、没再夹菜。
禁用套话：不由得一愣、眉头紧锁、深吸一口气、嘴角微微上扬、心中一凛、瞳孔骤缩、
后背一凉、握紧了拳头、沉默了片刻、目光复杂、语气不容置疑、空气仿佛凝固。
少用「不是……，是……」这个句式，真人写小说几乎不用它。
句子长短要不齐。该断的地方断开，一段里放一两个三五字的短句。
每段不要都收一句金句。多数段落平着结束。"""


def with_deai(system_prompt: str) -> str:
    """给 system_prompt 挂上去 AI 味约束。三个卡生成器都从这里过。"""
    return system_prompt + DEAI
