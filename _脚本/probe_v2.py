#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语料探针 v2 —— 面向 9000+ 篇规模的全量扫描与内容抽取。

与 v1 的区别：
  · 多进程（v1 单进程，9000 篇要跑很久）
  · 新增「文案抽取」：把每篇开头作者自述的 文案/排雷/内容标签/主角/一句话简介
    结构化抽出来。这是全库信息密度最高的一层——作者在这里主动交代了
    亚型、雷点、人设、CP 结构，且是标准化程度最高的文本。
  · 新增正文特征抽取：称谓词频、权力动词、感官词、句长分布
  · MD5 去重在扫描阶段即完成

产物：`10-藏书索引/_语料库.jsonl`（每行一篇）+ 控制台摘要。

用法：
    python3 probe_v2.py [--workers N] [--limit N]
"""

import os
import re
import sys
import json
import hashlib
import argparse
from pathlib import Path
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

from paths import CORPUS, INDEX_DIR
from paths import require_corpus

ROOT = CORPUS
OUT_DIR = INDEX_DIR
OUT_JSONL = OUT_DIR / "_语料库.jsonl"

HEAD_BYTES = 20000       # 文案抽取读取范围
BODY_SAMPLE = 300_000    # 正文特征采样上限


# ══ 编码 ══════════════════════════════════════════════════════════════
# 零宽水印：资源站往正文里插不可见字符做溯源标记。
# 实测 92 / 6,045 篇含它，最严重的单篇有 62,479 个（占该篇 5.3%）。
# 全库层面只虚增 0.12%，但**这些篇的单篇字数虚高最多 5.6%**，
# 且它会切断词语（「妻​主」匹配不到「妻主」），必须在解码时就剥掉。
ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u180e\u00ad]")


def _strip_zw(s):
    return ZERO_WIDTH.sub("", s)


def decode_bytes(raw: bytes):
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace").lstrip("﻿"), "UTF-16LE"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace").lstrip("﻿"), "UTF-16BE"
    if raw.startswith(b"\xef\xbb\xbf"):
        return _strip_zw(raw[3:].decode("utf-8", errors="replace")), "UTF-8-BOM"
    try:
        return _strip_zw(raw.decode("utf-8")), "UTF-8"
    except UnicodeDecodeError:
        pass
    try:
        return _strip_zw(raw.decode("gb18030")), "GB18030"
    except UnicodeDecodeError:
        return _strip_zw(raw.decode("gb18030", errors="replace")), "GB18030-lossy"


# ══ 文案抽取（本脚本的核心新增能力）══════════════════════════════════
# 各站导出格式的自述字段。顺序有意义：先匹配结构化字段，再退化到自由文案。
BLURB_FIELDS = [
    ("文案", r"文\s*案[:：]?\s*\n?(.{20,1800}?)(?=\n\s*(?:内容标签|标签|搜索关键字|一句话简介|立意|排雷|作品简评|第[一1]章|☆|正文|【正文】|═|─|—{5,}|\Z))"),
    ("内容简介", r"(?:内容简介|简介|详細文案|详细文案|作品简介)[:：]?\s*\n?(.{20,1800}?)(?=\n\s*(?:内容标签|标签|排雷|第[一1]章|☆|正文|\Z))"),
    ("内容标签", r"内容标签[:：]\s*([^\n]{2,200})"),
    ("搜索关键字", r"搜索关键字[:：]\s*([^\n]{2,200})"),
    ("一句话简介", r"一句话简介[:：]\s*([^\n]{2,120})"),
    ("立意", r"立意[:：]\s*([^\n]{2,120})"),
    ("主角", r"主角[:：]\s*([^\n]{2,120})"),
    ("配角", r"配角[:：]\s*([^\n]{2,120})"),
    ("作品简评", r"作品简评[:：]\s*\n?(.{20,600}?)(?=\n\s*(?:第[一1]章|☆|正文|\Z))"),
    ("排雷", r"(?:排雷|避雷|雷点|预警|注意事项|须知)[:：]?\s*\n?(.{10,900}?)(?=\n\s*(?:第[一1]章|☆|正文|内容标签|\Z))"),
    ("CP", r"(?:CP|cp|配对)[:：]\s*([^\n]{2,80})"),
    ("站头体裁", r"(?:Original Novel|原创小说)\s*[-–]\s*(BL|GL|GB|BG)"),
    ("站头分类", r"原创\s*[／/·、\s-]*\s*(男男|女女|男女|GB|BL|GL)"),
    ("文章类型", r"文章类型[:：]\s*([^\n]{1,30})"),
    ("作品视角", r"作品视角[:：]\s*([^\n]{1,30})"),
]

# 站头的斜杠标签串，如「原创 / 男女 / 古代 / 高H / 正剧 / 美攻强受」
SLASH_TAGS = re.compile(
    r"^\s*(?:原创|同人|轉載|转载)?\s*[/／]\s*(?:[^\n/／]{1,12}[/／]){2,10}[^\n/／]{1,12}\s*$",
    re.M)
BRACKET_TAGS = re.compile(r"[【\[]([^】\]]{2,60})[】\]]")


def extract_blurb(head: str):
    """从开头文本抽出作者自述的结构化信息。返回 dict。"""
    out = {}
    for key, pat in BLURB_FIELDS:
        m = re.search(pat, head, re.S)
        if m:
            v = re.sub(r"\s+", " ", m.group(1)).strip()
            v = re.sub(r"^[:：\s]+", "", v)
            if len(v) >= 2:
                out[key] = v[:1500]
    # 斜杠标签串
    st = SLASH_TAGS.findall(head[:4000])
    if st:
        line = re.search(SLASH_TAGS, head[:4000])
        if line:
            out["斜杠标签"] = re.sub(r"\s+", "", line.group(0))[:150]
    # 方括号标签（书名里/开头的 【GB】【1v1 完结】之类）
    br = [b for b in BRACKET_TAGS.findall(head[:1500]) if len(b) <= 40]
    if br:
        out["方括号标签"] = "｜".join(dict.fromkeys(br))[:200]
    return out


# ══ 词表 ══════════════════════════════════════════════════════════════
FEMDOM_LEX = ["妻主", "正君", "侧君", "侍君", "夫郎", "夫侍", "男妻", "父君", "父后",
              "女尊", "女攻", "男受", "第四爱", "女帝", "女皇", "男宠", "小爹",
              "纳夫", "入赘", "女A", "女alpha", "女Alpha", "雌君", "四爱"]
BL_LEX = ["男男", "耽美", "纯爱文", "BL文", "双男主"]
FEM_NARR = ["裙子", "裙摆", "长裙", "高跟鞋", "口红", "眉笔", "化妆", "胸罩", "文胸",
            "内衣", "月经", "大姨妈", "长发", "马尾", "丝袜", "耳环", "指甲油",
            "我一个女人", "我是女人", "身为女人", "女朋友", "闺蜜"]
MASC_NARR = ["喉结", "胡茬", "胡子", "刮胡", "领带", "西装裤", "我一个男人",
             "我是男人", "身为男人", "兄弟们", "哥们"]
EXPLICIT = ["性器", "阴茎", "肉棒", "抽插", "情潮", "高潮", "呻吟", "湿润",
            "喘息", "交合", "巨物", "腿间", "腺体", "信息素"]

# 权力关系语言标记（供 07-语言风格卷用）
POWER_MARK = {
    "命令句": ["过来", "跪下", "抬头", "看着我", "不许", "闭嘴", "住手", "给我"],
    "所有格": ["我的人", "我的男人", "我的狗", "属于我", "我的东西"],
    "称谓-敬": ["主人", "大人", "殿下", "妻主", "陛下", "小姐", "姐姐", "老板"],
    "称谓-昵": ["宝贝", "乖", "小狗", "崽", "小东西", "小可怜"],
    "顺从动词": ["跪", "低头", "颤抖", "服从", "听话", "求", "讨好", "示弱"],
}

CH_PAT = [re.compile(p) for p in (
    r"^\s*☆[、,]", r"^\s*第\s*[0-9一二三四五六七八九十百千零两]+\s*[章节回]",
    r"^\s*Chapter\s*\d+", r"^\s*\d{1,4}\s*[、.．]\s*\S")]


def probe_one(path_str: str):
    p = Path(path_str)
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    if len(raw) < 800:                       # 太小的多半是目录/广告页
        return {"path": path_str, "skip": "过小"}
    md5 = hashlib.md5(raw).hexdigest()
    text, enc = decode_bytes(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    chars = sum(1 for c in text if not c.isspace())
    head = text[:HEAD_BYTES]
    sample = text[:BODY_SAMPLE]

    ta, she, me = sample.count("他"), sample.count("她"), sample.count("我")
    t3 = ta + she
    she_r = round(she / t3, 3) if t3 else 0.0
    me_r = round(me / (me + t3), 3) if (me + t3) else 0.0

    femdom = sum(sample.count(w) for w in FEMDOM_LEX)
    blw = sum(sample.count(w) for w in BL_LEX)
    fem_n = sum(sample.count(w) for w in FEM_NARR)
    masc_n = sum(sample.count(w) for w in MASC_NARR)

    ex_hits = sum(sample.count(w) for w in EXPLICIT)
    per10k = ex_hits / max(len(sample) / 10000, 1)
    heat = ("E" if per10k >= 8 else "M" if per10k >= 2
            else "T" if per10k >= 0.3 else "G/T")

    chapters = sum(1 for line in text.split("\n")
                   if any(r.search(line) for r in CH_PAT))

    power = {k: sum(sample.count(w) for w in ws) for k, ws in POWER_MARK.items()}

    # 句长（只在采样前 5 万字算，够稳）
    seg = re.split(r"[。！？…\n]", sample[:50000])
    lens = [len(s.strip()) for s in seg if 2 <= len(s.strip()) <= 200]
    avg_len = round(sum(lens) / len(lens), 1) if lens else 0

    return {
        "path": path_str,
        "文件名": p.name,
        "目录": str(p.parent.relative_to(ROOT)) if ROOT in p.parents else "",
        "md5": md5,
        "字节": len(raw),
        "字数": chars,
        "万字": round(chars / 10000, 1),
        "编码": enc,
        "章节数": chapters,
        "他": ta, "她": she, "我": me,
        "她占比": she_r, "我占比": me_r,
        "女尊词": femdom, "BL词": blw,
        "女性叙述旁证": fem_n, "男性叙述旁证": masc_n,
        "露骨密度": round(per10k, 2),
        "尺度": heat,
        "平均句长": avg_len,
        "权力标记": power,
        "文案": extract_blurb(head),
    }


def main():
    require_corpus()
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 2))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    # 必须排除派生目录。`_整理后/` 是 organize_corpus.py 用**硬链接**建的归类视图，
    # 扫进来会让「原始文件数」凭空多出三千多个（实测 13,285 → 16,425）。
    # MD5 去重虽然能挡住它们进入分析口径，但那个统计数字已经失去意义了。
    DERIVED = ("_整理后", "_收件箱", "_排除")
    files = [str(p) for p in ROOT.rglob("*.txt") if not any(d in p.parts for d in DERIVED)]
    files += [str(p) for p in ROOT.rglob("*.TXT") if not any(d in p.parts for d in DERIVED)]
    files = sorted(set(files))
    if a.limit:
        files = files[:a.limit]
    print(f"待扫描 {len(files)} 个文件，{a.workers} 进程\n")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seen_md5, records, skipped = {}, [], 0
    done = 0

    with ProcessPoolExecutor(max_workers=a.workers) as ex, \
            open(OUT_JSONL, "w", encoding="utf-8") as fout:
        futs = {ex.submit(probe_one, f): f for f in files}
        for fut in as_completed(futs):
            done += 1
            try:
                r = fut.result()
            except Exception:
                r = None
            if r is None:
                skipped += 1
            elif "skip" in r:
                skipped += 1
            else:
                if r["md5"] in seen_md5:
                    r["重复于"] = seen_md5[r["md5"]]
                else:
                    seen_md5[r["md5"]] = r["文件名"]
                    r["重复于"] = None
                records.append(r)
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            if done % 800 == 0:
                print(f"  {done}/{len(files)} …")

    uniq = [r for r in records if not r["重复于"]]
    tot = sum(r["字数"] for r in uniq)
    print(f"\n{'='*62}")
    print(f"扫描 {len(files)} 文件 → 有效 {len(records)}，跳过 {skipped}")
    print(f"去重后 {len(uniq)} 篇 / {tot:,} 字 ({tot/100_000_000:.2f} 亿字)")
    print(f"重复 {len(records)-len(uniq)} 篇（{(len(records)-len(uniq))/max(len(records),1)*100:.0f}%）")
    print(f"\n编码：{Counter(r['编码'] for r in uniq).most_common()}")
    print(f"尺度：{Counter(r['尺度'] for r in uniq).most_common()}")
    has_blurb = sum(1 for r in uniq if r["文案"])
    print(f"抽到文案信息的：{has_blurb} 篇（{has_blurb/max(len(uniq),1)*100:.0f}%）")
    field_cnt = Counter(k for r in uniq for k in r["文案"])
    print(f"文案字段命中：{field_cnt.most_common(12)}")
    print(f"\n→ {OUT_JSONL}")


if __name__ == "__main__":
    main()
