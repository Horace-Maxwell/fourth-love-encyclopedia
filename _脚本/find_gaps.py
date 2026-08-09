#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找内容缺口：语料里高频、但本库没收的词。

思路：作者自己在文案与标签里写下的词，就是这个类型实际在用的词表。
把它与本库已收词条一比（实收多少运行时现数，不写死——写死过一次「311」，过期了），
差集就是缺口清单。

比「凭印象想还缺什么」可靠，因为它由语料决定，不由编者的记忆决定。

已修过的一个洞：collected() 早先只认 h3/h4 标题，而 14-桥段库 的条目全是 h2，
291 条桥段名一个都不进已收集合——缺口清单里混着几百个系统性假阳性。
按编号 glob、按标题层级取词的地方，都要想一遍「新卷的体例是不是这一种」。

用法：python3 find_gaps.py [--top N]     词条级缺口（语料标签 − 已收词形）
      python3 find_gaps.py --vignette    桥段级缺口（13-07 的族/组合/链 − 14 卷条目）
"""

import re
import sys
from collections import Counter
from pathlib import Path

from paths import LIB

# 本库已收的词条 = 各卷的 #### 标题 + 速查表的词条列
def collected():
    got = set()
    for p in (LIB / "02-术语百科").glob("*.md"):
        t = p.read_text(encoding="utf-8")
        got |= {m.group(1).strip() for m in re.finditer(r"^#### +(.+?)\s*$", t, re.M)}
        # 速查表的第一列
        got |= {m.group(1).strip() for m in
                re.finditer(r"^\| \[?([^\]|]{1,14})\]?[^|]*\|", t, re.M)}
    # 别称也算已收
    for p in (LIB / "02-术语百科").glob("*.md"):
        t = p.read_text(encoding="utf-8")
        for m in re.finditer(r"别称[：:]\s*([^｜\n]+)", t):
            got |= {x.strip() for x in re.split(r"[、,，/／]", m.group(1)) if x.strip()}
    # 其他卷的三级标题也算覆盖
    for p in LIB.rglob("*.md"):
        if "_整理后" in str(p):
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        got |= {m.group(1).strip() for m in re.finditer(r"^#{3,4} +(.{2,12}?)\s*$", t, re.M)}
    # 14-桥段库的条目是 h2（「## 一 · 等门与热菜」），上面那条 h3/h4 正则收不到，
    # 291 条全部被判成「未收」——这里按 L 项同一判据补收
    for p in (LIB / "14-桥段库").glob("[0-9]*.md"):
        t = p.read_text(encoding="utf-8", errors="ignore")
        got |= {m.group(1).strip() for m in
                re.finditer(r"^## +[一二三四五六七八九十]+ · (.+?)\s*$", t, re.M)}
    return {g for g in got if g and len(g) <= 14}


# 从作者自述文案里抽候选词：方括号标签、斜杠标签、顿号分隔的标签串
TAG_PATTERNS = [
    re.compile(r"[【\[]([^】\]]{2,10})[】\]]"),
    re.compile(r"(?<![一-鿿])([一-鿿A-Za-z0-9]{2,8})(?=[、／/])"),
    re.compile(r"[、／/]([一-鿿A-Za-z0-9]{2,8})(?![一-鿿])"),
]
NOISE = re.compile(r"^\d+$|更新|完结|连载|番外|全本|下载|整理|书单|资源|网盘|微信|QQ|"
                   r"公主号|笨笨|作者|字数|正文|第\d|共\d|万字|^[a-z]$|^[A-Z]$|"
                   r"txt|doc|zip|rar|http")


def vignette_mode():
    """桥段级缺口：13-07 报告里的族/组合/节拍链，逐一核对 14 卷是否接得住。

    此前库里只有词条级缺口检测，桥段层没有任何机器盯防——组合榜第 1 名
    （婚仪+请安+选侍，24 部）无条目、双修族（187 部）无专条，都是人工勘察才发现的。
    """
    from mine_vignette import SCENE, WORLD, BEATS

    lib14 = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                      for p in (LIB / "14-桥段库").glob("[0-9]*.md"))

    # ① 族级：情境族与世界族应当各有归处（反应族是情绪原子，不要求专条）。
    # 判据分两层：提及 0 次 = 缺失；≤2 次 = 疑似薄弱。
    # 只查「出现过没有」会漏报——双修曾只在 21 卷的频次表里被列过一次，
    # 频次表提及不等于有条目，当时它 187 部的体量整个悬空。
    cnt = {fam: lib14.count(fam) for fam in list(SCENE) + list(WORLD)}
    missing = sorted(f for f, n in cnt.items() if n == 0)
    thin = sorted((f, n) for f, n in cnt.items() if 0 < n <= 2)
    print(f"① 族级缺口（{len(cnt)} 个情境/世界族 × 14 卷全文提及次数）：")
    print(f"   缺失（0 次）：{'、'.join(missing) if missing else '无'}")
    print("   疑似薄弱（≤2 次，提及≠条目，逐个人工核）："
          + ("、".join(f"{f}({n})" for f, n in thin) if thin else "无"))

    # ② 组合榜与节拍链：13-07 的表里凡是用 ＋/→ 串起来的行，拆出族名逐拍核对
    rpt = LIB / "13-语料挖掘" / "07-桥段分布.md"
    broken = []
    if rpt.exists():
        for line in rpt.read_text(encoding="utf-8").split("\n"):
            if ("＋" not in line and "→" not in line) or not line.lstrip().startswith("|"):
                continue
            toks = [w.strip() for w in re.split(r"[＋+→｜|]", line) if w.strip()]
            fams = [w for w in toks if w in BEATS]
            if len(fams) < 2:
                continue
            miss = [w for w in fams if w in SCENE and w not in lib14]
            if miss:
                broken.append((line.strip()[:52], miss))
    print(f"\n② 13-07 的组合/链中，含未接住情境族的行：{len(broken)}")
    for row, miss in broken[:20]:
        print(f"   {row} ｜缺 {'、'.join(miss)}")
    if len(broken) > 20:
        print(f"   …另 {len(broken)-20} 行")
    return 1 if (missing or thin or broken) else 0


def main():
    if "--vignette" in sys.argv:
        sys.exit(vignette_mode())

    top = 300
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])

    from aggregate_corpus import R

    got = collected()
    cand = Counter()
    for r in R:
        blob = (r.get("文件名") or "") + " " + " ".join(
            str(v) for v in (r.get("文案") or {}).values())
        for pat in TAG_PATTERNS:
            for m in pat.finditer(blob):
                w = m.group(1).strip()
                if 2 <= len(w) <= 10 and not NOISE.search(w):
                    cand[w] += 1

    gaps = [(w, n) for w, n in cand.most_common(top * 4) if w not in got]
    print(f"本库已收 {len(got)} 个词形｜语料候选 {len(cand)} 个\n")
    print(f"{'缺口词':14}{'篇数':>7}  {'占比':>6}")
    N = len(R)
    for w, n in gaps[:top]:
        if n < 20:
            break
        print(f"  {w:12}{n:>7}  {n/N*100:>5.1f}%")


if __name__ == "__main__":
    main()
