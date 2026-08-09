#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
素材库整理器 —— 把 40 多个来源不明的目录整理成按亚型归类的干净视图。

原始语料的问题：
  · 40+ 个目录，名字含乱码（GBK 目录名被误解码）、日期、来源代号，无法检索
  · 54% 重复（同一部作品在多个合集里各存一份）
  · 文件名带资源站水印（【公主号：笨笨书屋】之类）
  · 混入 445 篇非本类型（男性向巨型合集、BL 名作）

整理策略（**非破坏性**）：
  · 用 **硬链接** 建新视图 → 不占额外磁盘空间，原文件一个字节都不动
  · 按「主亚型」归类到 12 个目录，一篇只进一个目录（选最具区分度的那个）
  · 文件名清洗：剥水印、统一书名号、补上标签后缀
  · 重复的只链一份，混入的单独归到 _排除 目录
  · 生成每个目录的 README 索引

用法：
    python3 organize_corpus.py --dry-run     # 只看会怎么归类，不动文件
    python3 organize_corpus.py               # 实际建立整理视图
    python3 organize_corpus.py --copy        # 用复制代替硬链接（跨盘时用）
"""

import re
import os
import json
import shutil
import argparse
from pathlib import Path
from collections import Counter, defaultdict

ROOT = CORPUS
DEST = ROOT / "_整理后"

# 复用聚合器的词表与清洗逻辑
import sys

from paths import CORPUS, JSONL
from paths import require_corpus
sys.path.insert(0, str(Path(__file__).parent))


# ══ 归类规则 ══════════════════════════════════════════════════════════
# 顺序即优先级：一篇命中多个时，取最靠前的那个作为主亚型。
# 设计原则：先按「最具区分度的设定」分，再按「世界背景」分，最后兜底。
BUCKETS = [
    ("01-女尊",         ["女尊", "妻主", "正君", "侧夫", "夫郎", "父后", "男妻",
                         "女帝", "皇太女", "帝卿", "男德", "一妻多夫"]),
    ("02-女A男O",       ["女A男O", "女a男o", "女Alpha", "女alpha", "女A ", "[女A",
                         "女A、", "女a", "女A男", "ABO", "abo", "Abo"]),
    ("03-训诫调教",     ["训诫", "调教", "BDSM", "bdsm", "SM ", "主奴", "sp ",
                         "SP ", "女S", "女s", "规矩", "家规", "鞭", "项圈"]),
    ("04-修仙玄幻",     ["修仙", "仙侠", "修真", "魔尊", "魔君", "剑修", "师尊",
                         "宗门", "灵根", "飞升", "玄幻", "圣女", "道姑"]),
    ("05-星际末世",     ["星际", "机甲", "末世", "末日", "丧尸", "虫族", "元帅",
                         "上将", "太空", "异能"]),
    ("06-古代江湖",     ["古代", "古言", "武侠", "江湖", "武林", "将军", "王爷",
                         "皇子", "宫廷", "朝堂", "太子", "侍卫", "青楼", "锦衣"]),
    ("07-穿书快穿",     ["穿书", "快穿", "系统", "无限流", "副本", "重生", "穿越",
                         "任务", "位面"]),
    ("08-娱乐圈电竞",   ["娱乐圈", "明星", "爱豆", "顶流", "影帝", "电竞", "主播",
                         "综艺", "剧组"]),
    ("09-校园职场",     ["校园", "学院", "大学", "老师", "学长", "同桌", "职场",
                         "上司", "总裁", "霸总", "秘书", "医生", "律师"]),
    ("10-非人异种",     ["人外", "兽人", "血族", "妖", "怪物", "触手", "半人",
                         "鲛人", "人鱼", "龙", "神明"]),
    ("11-np多男主",     ["np", "NP", "Np", "逆后宫", "总攻", "一女多男", "3p",
                         "4p", "群像"]),
    ("12-现代1v1",      ["现代", "都市", "1v1", "1V1"]),
]
FALLBACK = "13-未分类"
EXCLUDE_DIR = "_排除-非本类型"

# 文件名清洗
WATERMARK = re.compile(
    r"【?(?:公主号|公众号|公號|微信|VX|vx|QQ群|qq群|微博)[:：]?[^】\]\)）]{0,20}】?"
    r"|【?笨笨书屋】?|【?[^】]{0,10}书屋】?|【?[^】]{0,8}整理】?"
    r"|\[?【?(?:MJ|文文|棠|密码\d*|po18|PO18)】?\]?")
MULTISPACE = re.compile(r"[\s　]{2,}")


def clean_name(name: str) -> str:
    """清洗文件名：剥水印、去重复空格、统一括号。"""
    stem = re.sub(r"\.(txt|TXT)$", "", name)
    stem = WATERMARK.sub("", stem)
    stem = stem.replace("（", "(").replace("）", ")")
    stem = re.sub(r"\(\s*\)", "", stem)          # 清空的括号
    stem = re.sub(r"[\[【]\s*[\]】]", "", stem)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)       # 尾部的 (1)(2) 存档序号
    stem = re.sub(r"\s*__\d+\s*$", "", stem)
    stem = re.sub(r"\s*-{2,}\s*", " ", stem)           # -- 分隔符
    stem = MULTISPACE.sub(" ", stem).strip(" -_·、")
    stem = re.sub(r"[/\\:*?\"<>|]", "_", stem)   # 文件系统非法字符
    return (stem[:120] or "未命名") + ".txt"


def pick_bucket(r) -> str:
    hay = r["文件名"] + " " + " ".join(str(v) for v in r.get("文案", {}).values())
    for name, kws in BUCKETS:
        if any(k in hay for k in kws):
            return name
    return FALLBACK


# ══ 同名近重复合并 ════════════════════════════════════════════════════
# MD5 只能抓到逐字节相同的重复。实际语料里大量存在「同一部作品的不同存档」：
#   《XXX》.txt 与 《XXX》(1).txt —— 差几个字节（多一行广告、少一个番外）
#   《XXX》作者：甲.txt 与 XXX.txt —— 同作品不同命名
# 这类必须靠「归一化标题」来合并，否则整理后的目录里仍然一堆重复。
TITLE_NOISE = re.compile(
    r"\(\d+\)$|__\d+$|\s*-+\s*$"                       # (1) __2 结尾
    r"|【?完结】?|【?完结\+?番外\d*】?|\[?完结\]?"        # 完结标记
    r"|更\s*\d+|\[?连载\]?|全本|全文"                    # 连载状态
    r"|作者[:：].*$|作家[:：].*$|[Bb][Yy]\s*\S+$"        # 作者名
    r"|[（(][^)）]{0,30}[)）]|[\[【][^\]】]{0,30}[\]】]")  # 括号内的标签


def norm_title(name: str) -> str:
    """把文件名归一化成「作品标识」，用于识别同作品的不同存档。"""
    s = re.sub(r"\.(txt|TXT)$", "", name)
    s = WATERMARK.sub("", s)
    prev = None
    while prev != s:                      # 反复剥，直到不再变化
        prev = s
        s = TITLE_NOISE.sub("", s).strip(" -_·、—")
    s = re.sub(r"[《》〈〉\"'\s　·、,，.。!！?？~～*]", "", s)
    return s.lower()


def merge_near_dups(records):
    """同一归一化标题下只保留字数最多的一份（内容最全）。"""
    groups = defaultdict(list)
    for r in records:
        t = norm_title(r["文件名"])
        groups[t if len(t) >= 3 else f"__short__{r['md5']}"].append(r)
    kept, merged = [], 0
    for t, items in groups.items():
        if len(items) == 1:
            kept.append(items[0])
            continue
        # 字数最多的那份内容最全；同字数取路径最短
        items.sort(key=lambda r: (-r["字数"], len(r["path"])))
        best = items[0]
        best["_近重复"] = [x["文件名"] for x in items[1:]]
        kept.append(best)
        merged += len(items) - 1
    return kept, merged


def main():
    require_corpus()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--copy", action="store_true", help="用复制代替硬链接")
    a = ap.parse_args()

    # 读取扫描结果并全局去重（保留路径最短的那份）
    best = {}
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            m = r["md5"]
            if m not in best or len(r["path"]) < len(best[m]["path"]):
                best[m] = r
    records = list(best.values())
    print(f"MD5 去重后 {len(records):,} 篇")
    records, merged = merge_near_dups(records)
    print(f"同名近重复合并 {merged:,} 篇 → 剩 {len(records):,} 篇\n")

    # 入库判定（与聚合器同一套规则）
    from aggregate_corpus import classify_inclusion, tag_text_of, CANON as _CANON  # noqa
    keep, drop = [], []
    for r in records:
        ok, why = classify_inclusion(r)
        (keep if ok else drop).append((r, why))

    print(f"本类型 {len(keep):,} 篇｜排除 {len(drop):,} 篇\n")

    # 归类
    plan = defaultdict(list)
    for r, _ in keep:
        plan[pick_bucket(r)].append(r)
    for r, why in drop:
        r["_why"] = why
        plan[EXCLUDE_DIR].append(r)

    print("归类结果：")
    for name in [b[0] for b in BUCKETS] + [FALLBACK, EXCLUDE_DIR]:
        items = plan.get(name, [])
        if items:
            wan = sum(x["万字"] for x in items)
            print(f"  {name:20s} {len(items):5,} 篇  {wan:9,.0f} 万字")

    if a.dry_run:
        print("\n（--dry-run，未动任何文件）")
        return

    # 建立视图
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    total, failed = 0, 0

    for bucket, items in plan.items():
        bdir = DEST / bucket
        bdir.mkdir(parents=True, exist_ok=True)
        used = set()
        rows = []
        for r in sorted(items, key=lambda x: -x["字数"]):
            src = Path(r["path"])
            if not src.exists():
                failed += 1
                continue
            nm = clean_name(r["文件名"])
            base, i = nm[:-4], 2
            while nm in used:
                nm = f"{base}__{i}.txt"
                i += 1
            used.add(nm)
            dst = bdir / nm
            try:
                if a.copy:
                    shutil.copy2(src, dst)
                else:
                    os.link(src, dst)      # 硬链接：不占额外空间
                total += 1
            except OSError:
                try:
                    shutil.copy2(src, dst)
                    total += 1
                except OSError:
                    failed += 1
                    continue
            rows.append((nm[:-4], r["万字"], r["尺度"], r.get("_why", "")))

        # 目录索引
        L = [f"# {bucket}", "",
             f"共 **{len(rows):,} 篇** ／ **{sum(x[1] for x in rows):,.0f} 万字**", ""]
        if bucket == EXCLUDE_DIR:
            L += ["> 这些是**非本类型**的混入作品（男性向巨型合集、BL 名作、"
                  "无任何 GB 标记者）。", "> 保留在此供核查，不参与百科的统计与提炼。", "",
                  "| 作品 | 万字 | 排除理由 |", "|---|---:|---|"]
            for nm, wan, _h, why in rows[:400]:
                L.append(f"| {nm[:56]} | {wan} | {why} |")
        else:
            L += ["| 作品 | 万字 | 尺度 |", "|---|---:|---|"]
            for nm, wan, h, _ in rows[:600]:
                L.append(f"| {nm[:60]} | {wan} | {h} |")
            if len(rows) > 600:
                L.append(f"\n（只列前 600 篇，本目录共 {len(rows):,} 篇）")
        (bdir / "_目录.md").write_text("\n".join(L), encoding="utf-8")

    # 总索引
    L = ["# 素材库 · 整理后视图", "",
         "> **这是硬链接视图，不占额外磁盘空间，原始目录一个字节都没动。**",
         "> 验收满意后可以自行删除外面那些来源不明的旧目录。", "",
         "> 重新生成：`python3 第四爱百科/_脚本/organize_corpus.py`", "",
         "## 整理做了什么", "",
         "| 问题 | 处理 |", "|---|---|",
         "| 40+ 个来源不明的目录（含乱码目录名） | 归并成 14 个按亚型分的目录 |",
         "| 54% 重复（同作品在多个合集里各存一份） | MD5 去重，只保留一份 |",
         "| 文件名带资源站水印 | 剥掉【公主号：xxx】【MJ】【笨笨书屋】等 |",
         "| 混入非本类型作品 | 单独归到 `_排除-非本类型/` |",
         "", "> ### ⚠️ 为什么这里的篇数与《藏书总索引》对不上", "",
         "> **两个数都对，量的不是同一件事——差别在「合并近重复」这一步的位置。**", "",
         "> | | 流程 | 结果 |",
         "> |---|---|---|",
         f"> | **视图口径**（本目录） | MD5 去重 → **合并近重复** → 剔除混入 | {len(keep):,} 篇 |",
         f"> | **分析口径**（全库统计） | MD5 去重 → 剔除混入（**不合并**） | {_CANON['分析口径篇数']:,} 篇 |", "",
         "> `XXX.txt` 与 `XXX(1).txt` 是同一部作品的不同存档。",
         "> **给人翻的目录里应该只出现一次**，所以视图合并了它们；",
         "> 而统计要的是可复现的确定口径，归一标题是启发式的（不同作品可能撞同一个归一标题），",
         "> 所以分析层不做这一步。两边先后顺序也不同，因此两个「独立作品数」不会精确相等。", "",
         "> **全库任何篇数结论一律以分析口径为准**（见 `aggregate_corpus.CANON`）。", "",
         "| 全角/半角括号、多余空格混乱 | 统一 |", "",
         "## 目录", "",
         "| 目录 | 篇数 | 万字 | 说明 |", "|---|---:|---:|---|"]
    desc = {
        "01-女尊": "世界观层面的女尊男卑设定",
        "02-女A男O": "ABO 设定下的女 Alpha × 男 Omega",
        "03-训诫调教": "训诫 / 调教 / BDSM / 主奴向",
        "04-修仙玄幻": "修真、仙侠、魔道背景",
        "05-星际末世": "星际、机甲、末世、虫族",
        "06-古代江湖": "古代非女尊、武侠、宫廷权谋",
        "07-穿书快穿": "穿书、快穿、系统、无限流、重生",
        "08-娱乐圈电竞": "娱乐圈、电竞、直播",
        "09-校园职场": "校园、职场、霸总、医生律师",
        "10-非人异种": "人外、兽人、血族、鲛人",
        "11-np多男主": "一女多男、逆后宫、总攻",
        "12-现代1v1": "现代都市一对一",
        FALLBACK: "未命中任何亚型关键词，需人工过目",
        EXCLUDE_DIR: "⚠️ 非本类型混入，不参与统计",
    }
    for name in [b[0] for b in BUCKETS] + [FALLBACK, EXCLUDE_DIR]:
        items = plan.get(name, [])
        if items:
            L.append(f"| [{name}]({name}/_目录.md) | {len(items):,} | "
                     f"{sum(x['万字'] for x in items):,.0f} | {desc.get(name,'')} |")
    L += ["", "## 归类规则", "",
          "一篇只进一个目录，按上表**从上到下**的优先级取第一个命中的亚型。",
          "例如一篇「女尊 + 修仙 + np」的文会进 `01-女尊`，因为女尊的区分度最高。", "",
          "完整的机器可读元数据（含每篇的全部亚型标签）在 "
          "[`第四爱百科/10-藏书索引/_语料库.jsonl`](../../第四爱百科/10-藏书索引/_语料库.jsonl)。", "",
          "> 想按别的维度重新归类？改脚本里的 `BUCKETS` 常量再重跑即可。"]
    (DEST / "README.md").write_text("\n".join(L), encoding="utf-8")

    print(f"\n{'='*58}")
    print(f"整理完成：{total:,} 个链接建立，{failed} 个失败")
    print(f"→ {DEST}")
    if not a.copy:
        print("（硬链接，未占用额外磁盘空间）")


if __name__ == "__main__":
    main()
