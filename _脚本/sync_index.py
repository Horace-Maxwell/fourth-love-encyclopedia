#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 INDEX.md / README.md 里的统计数字改成**机器生成**，从此不再手写。

为什么需要这个脚本：
  质量审计查出 24 条必修问题，其中 11 条是同一个病——**同一个数在多处手写，
  改了一处忘了另一处**。README 说 71 万字、INDEX 说 103 万字、实测 61.6 万汉字；
  02 卷两篇的条数虚报 8 条与 3 条；易混淆词「16 组」实为 17 组。
  改文档只能修一次，改生成器才能一劳永逸。

口径定义（全库共用一份，别处引用必须与此一致）：
  篇数   —— **进仓库的** .md 文件数（不含 _整理后 与 .gitignore 的目录）
           印在 README 上的数必须是别人 clone 后能数出来的数
  万字   —— **汉字数**。同时给出字符数以免误读，但「万字」一律指汉字。
  语料   —— 见 aggregate_corpus.CANON，本脚本直接引用，不重算
  桥段   —— 直接扫 14-桥段库 各族文件的条目标题现数，与 build_vignette_index 同一判据

用法：python3 sync_index.py       （改动会打印出来）
      python3 sync_index.py --check（只报差异，不落盘，供交付前自查；
                                     有差异/漂移/手写数字不符时返回码为 1，pre-commit 依赖这一点）
"""

import re
import sys
from pathlib import Path

from paths import LIB

sys.path.insert(0, str(LIB / "_脚本"))


def cn(t):
    return len(re.findall(r"[一-鿿]", t))


# 不入库的目录（见 .gitignore）。它们在本机有、在别人 clone 出来的仓库里没有。
# 篇数、汉字、表格数这几个数印在 README 上给别人看，必须是**别人能数出来的数**。
# 曾经印 135 篇，而 fresh clone 只有 120 篇——差的 15 篇全在这两个目录里。
NOT_SHIPPED = ("09-拆解卡", "10-藏书索引")


def stats():
    md = sorted(p for p in LIB.rglob("*.md")
                if "_整理后" not in str(p)
                and not any(d in p.parts for d in NOT_SHIPPED))
    texts = {p: p.read_text(encoding="utf-8", errors="ignore") for p in md}
    s = {
        "篇数": len(md),
        "汉字": sum(cn(t) for t in texts.values()),
        "字符": sum(len(t) for t in texts.values()),
    }

    def count(rel, pat):
        p = LIB / rel
        return len(re.findall(pat, p.read_text(encoding="utf-8"), re.M)) if p.exists() else 0

    s["术语03"] = count("02-术语百科/03-人设与套路标签.md", r"^#### ")
    s["术语04"] = count("02-术语百科/04-尺度预警与社群黑话.md", r"^#### ")
    s["辨析组"] = count("02-术语百科/05-易混淆词辨析.md",
                        r"^### +[⓪①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
    # 精读笔记（原 09 卷）与 10-藏书索引 一样是本机私有、不入库的。
    # fresh clone 上两者都不在，这里给 None 而不是 0——0 会被下面的
    # suspects 当成真值去比对库内的手写数字，把「本机没有」误报成「写错了」。
    cards_dir = LIB / "09-拆解卡"
    s["精读笔记"] = len(list(cards_dir.glob("*.md"))) if cards_dir.is_dir() else None
    s["排期表"] = count("10-藏书索引/精读排期表.md", r"^\| *\d+ *\|")
    s["模板JSON"] = len(list((LIB / "11-模板包").rglob("*.json")))
    s["角色卡"] = len(list((LIB / "11-模板包" / "角色卡").glob("*.json")))
    s["情景卡"] = len(list((LIB / "11-模板包" / "情景卡").glob("*.json")))
    # 术语总数取速查表的实际行数，不取各卷之和：速查表是四卷去重后的成品，
    # 而各卷之和会把跨卷重复的词算两次。早先声明的「311 条」比实际少 4，
    # 就是因为那个数是估的而不是数的。
    s["术语总数"] = count("02-术语百科/06-速查表.md", r"^\| \[")
    # 桥段条数直接扫源文件现数，判据与 build_vignette_index.parse 相同
    # （h2 + 汉字序数 + 「 · 」）。不依赖 00-总表：总表是产物，重建之前也要能对账。
    vig_entries, vig_fams = 0, 0
    vdir = LIB / "14-桥段库"
    if vdir.exists():
        for vf in vdir.glob("[0-9]*.md"):
            if vf.name == "00-总表.md":
                continue
            n = len(re.findall(r"^## [一二三四五六七八九十]+ · ",
                               vf.read_text(encoding="utf-8", errors="ignore"), re.M))
            vig_entries += n
            vig_fams += 1 if n else 0
    s["桥段条数"] = vig_entries
    s["桥段族数"] = vig_fams
    s["桥段卷篇数"] = len(list(vdir.glob("*.md"))) if vdir.exists() else 0
    # 套路数 = 05-01 的 h3 标题数（附录用 h2，不会混入）。NTR 一类新套路入卷后自动 +1
    s["套路数"] = count("05-剧情套路/01-经典套路库.md", r"^### ")
    # HTML 导出的篇数由 build_exports 的排除规则决定，与 md 总数不同。
    # 这个数在 README / INDEX / 12 卷 / 06-发布风险评估 四处手写过，
    # 每次加卷都会漏改，所以纳入归一。
    html = LIB / "index.html"
    s["HTML篇数"] = 0
    if html.exists():
        with html.open(encoding="utf-8", errors="ignore") as fh:
            m = re.match(r"<!--gb-html-docs:(\d+)-->", fh.readline())
        if m:
            s["HTML篇数"] = int(m.group(1))
    s["表格数"] = sum(len(re.findall(r"^ *\|", t, re.M)) for t in texts.values())

    # 语料派生统计只在本机算得出来：aggregate_corpus 一 import 就要读
    # 10-藏书索引/_语料库.jsonl，而那个目录不入库。fresh clone 上必然没有。
    # CLAUDE.md 早就写着「fresh clone 会自动跳过派生统计自查」，但这里没有守卫，
    # 于是 `run.py check` 在别人机器上直接抛 FileNotFoundError 崩掉——
    # 本机永远测不出这个，因为本机有那个文件。克隆一份跑一遍才看得见。
    try:
        from aggregate_corpus import CANON
    except (FileNotFoundError, ImportError):
        s["_无语料"] = True
        return s
    s["语料篇数"] = CANON["分析口径篇数"]
    s["语料字数"] = CANON["分析口径字数"]
    s["独立作品"] = CANON["独立作品数"]
    s["原始文件"] = CANON["原始文件"]
    s["MD5去重"] = CANON["MD5去重"]
    s["剔除"] = CANON["剔除篇数"]
    return s


def build_lines(s):
    scale = (f"> 最后更新：2026-08 ｜ 当前规模：**{s['汉字']/10000:.1f} 万汉字 / "
             f"{s['篇数']} 篇**（{s['字符']/10000:.1f} 万字符）")
    if s.get("_无语料"):
        return scale, None          # 没有语料就不重写语料行，保留仓库里现成的
    corpus = (f"> 语料基础：**{s['语料篇数']:,} 篇 / {s['语料字数']/1e8:.2f} 亿字**"
              f"（原始 {s['原始文件']:,} 文件 → MD5 去重 {s['MD5去重']:,} → "
              f"剔除非本类型 {s['剔除']} 篇；其中 {s['独立作品']:,} 部为独立作品，"
              f"其余是同作品的不同存档）")
    return scale, corpus


# 全库正文里凡是提到语料篇数/字数的地方，一律归一到 CANON。
# 这是第三次手工扫同一类数字之后加的：篇数被硬写进十几个文件的正文，
# 每次语料一变就要全库重扫一遍——改文档只能修一次，改归一器才能一劳永逸。
def normalize_corpus_figures(s_, ok):
    """把过期的语料数字改写成当期值。ok 是 stats() 的结果。"""
    n, chars = ok["语料篇数"], ok["语料字数"]
    yi = f"{chars/1e8:.2f} 亿字"
    reps = []
    # 历史上出现过的所有篇数写法 → 当期值
    for old in ("4,301", "4,703", "5,600", "5,597", "6,045 篇", "237 篇", "231 篇"):
        num = old.split()[0]
        if num.replace(",", "") == str(n):
            continue
        # 「早期版本（237 篇语料）」这类历史注记是正当的，不动
        reps.append((old, f"{n:,} 篇" if old.endswith("篇") else f"{n:,}"))
    for a, b in reps:
        # 只改「不是历史注记」的出现
        out, i = [], 0
        while True:
            j = s_.find(a, i)
            if j < 0:
                out.append(s_[i:])
                break
            ctx = s_[max(0, j - 40):j]
            # 两类不该改：
            #  ① 历史注记（「早期版本（237 篇语料）」）
            #  ② 流水线的中间阶段值（「MD5 去重 6,045 篇」是事实，不是过期口径）
            keep = any(k in ctx for k in
                       ("早期版本", "旧版", "此前", "曾", "原",
                        "MD5", "去重", "原始文件", "剔除", "解出"))
            out.append(s_[i:j])
            out.append(a if keep else b)
            i = j + len(a)
        s_ = "".join(out)
    # 「近 1 亿字」说的是被剔除的那部分，不是入库总量，不能一起替换
    for old_yi in ("5.7 亿字", "5.70 亿字", "5.78 亿字", "5.77 亿字"):
        if old_yi != yi:
            s_ = s_.replace(old_yi, yi)
    return s_


def main():
    check = "--check" in sys.argv
    s = stats()
    scale, corpus = build_lines(s)
    changed = []

    # ① 全库正文的语料数字归一。没有语料就跳过这一整段：
    # 归一的依据是 CANON，拿不到 CANON 就无从判断哪个数字过期了。
    for f in (sorted(LIB.rglob("*.md")) if not s.get("_无语料") else []):
        if "_整理后" in str(f) or f.name == "04-质量审计报告.md":
            continue
        t0 = f.read_text(encoding="utf-8")
        t1 = normalize_corpus_figures(t0, s)
        if t1 != t0:
            changed.append(str(f.relative_to(LIB)))
            if not check:
                f.write_text(t1, encoding="utf-8")

    # ② 两个顶层文件的统计行
    for rel in ("INDEX.md", "README.md"):
        p = LIB / rel
        t0 = t = p.read_text(encoding="utf-8")
        t = re.sub(r"^> 最后更新：.*$", scale, t, count=1, flags=re.M)
        if corpus:
            t = re.sub(r"^> 语料基础：.*$", corpus, t, count=1, flags=re.M)
        # README 的规模写在首段引用块里，格式不同
        if not s.get("_无语料"):
            t = re.sub(r"^> \*\*2026-08 ｜ 当前规模：.*$",
                       f"> **2026-08 ｜ 当前规模：{s['汉字']/10000:.1f} 万汉字 / {s['篇数']} 篇"
                       f" ｜ 语料基础：{s['语料篇数']:,} 篇 / {s['语料字数']/1e8:.2f} 亿字**",
                       t, count=1, flags=re.M)
        # README 首屏徽章行（`106.6 万汉字` ｜ `109 篇` ｜ `25,643 行表格` ｜ …）。
        # 教训：commit 48f4150 把规模数字改成徽章版式后，上面三条锚点全都不再命中，
        # 归一器静默跳过 README，1.9 万字的漂移就这么进了公开仓库。
        # **改任何呈现格式之前，先查这里是不是靠那个格式定位的。**
        t = re.sub(r"^`[\d.]+ 万汉字` ｜ `\d+ 篇` ｜ `[\d,]+ 行表格`",
                   f"`{s['汉字']/10000:.1f} 万汉字` ｜ `{s['篇数']} 篇` ｜ "
                   f"`{s['表格数']:,} 行表格`",
                   t, count=1, flags=re.M)
        if t != t0:
            if rel not in changed:
                changed.append(rel)
            if not check:
                p.write_text(t, encoding="utf-8")

    print("当期真值：")
    for k, v in s.items():
        if v is None:                 # 本机私有、不入库的那几项，缺了不算错
            print(f"  {k:10} —（本机无此目录）")
        else:
            print(f"  {k:10} {v:,}" if isinstance(v, int) else f"  {k:10} {v}")
    print("\n生成的统计行：")
    print("  " + scale)
    print("  " + (corpus or "（本机无语料，语料行保持仓库现状）"))
    print(f"\n{'需要更新' if check else '已更新'}：{changed or '无（已同步）'}")

    # ── 派生统计的自查 ──
    # 语料一变，这些数就跟着变，而它们被硬写在七八个卷里。
    # 前两轮都是靠人眼一个个追出来的，第三次之后做成检查项。
    # 10-藏书索引 是本机私有（gitignore），fresh clone 上没有——跳过而不是崩溃。
    gap_p = LIB / "10-藏书索引/亚型分布报告.md"
    tag_p = LIB / "10-藏书索引/文案标签统计.md"
    drift = []
    if not (gap_p.exists() and tag_p.exists()):
        print("\n（本地真值文件缺失，跳过派生统计自查——需要完整语料索引的机器才有）")
        gap = tag = ""
    else:
        gap = gap_p.read_text(encoding="utf-8")
        tag = tag_p.read_text(encoding="utf-8")

    def grab(t, pat, g=1):
        m = re.search(pat, t, re.M)
        return m.group(g) if m else None

    TRUTH = {
        "E级篇数": grab(gap, r"^\| E \| ([\d,]+) \|"),
        "E级占比": grab(gap, r"^\| E \| [\d,]+ \| ([\d.]+)%"),
        "第一人称": grab(gap, r"第一人称为主 \| [\d,]+ \| ([\d.]+)%"),
        "第三人称": grab(gap, r"第三人称为主 \| [\d,]+ \| ([\d.]+)%"),
        "B桶篇数": grab(gap, r"B 中短篇 3-10万 \| ([\d,]+) \|"),
        "B桶占比": grab(gap, r"B 中短篇 3-10万 \| [\d,]+ \| ([\d.]+)%"),
        "排雷篇数": grab(tag, r"排雷段的只有 ([\d,]+) 篇"),
        "排雷占比": grab(tag, r"占有效文案的 \*\*([\d.]+)%"),
    }
    # 每条：(文件, 正则, 取哪个分组, 对应真值键)
    CITES = [
        ("06-尺度与写法/01-分级镜头控制.md", r"E 级占 ([\d.]+)%\*\*（([\d,]+) / ", 1, "E级占比"),
        ("06-尺度与写法/01-分级镜头控制.md", r"E 级占 [\d.]+%\*\*（([\d,]+) / ", 1, "E级篇数"),
        ("06-尺度与写法/05-预警与分级实操.md", r"只有 ([\d,]+) 篇有明确排雷段", 1, "排雷篇数"),
        ("05-剧情套路/03-开篇钩子与节奏控制.md", r"第一（([\d.]+)%）", 1, "第一人称"),
        ("05-剧情套路/03-开篇钩子与节奏控制.md", r"第三（([\d.]+)%）", 1, "第三人称"),
        ("05-剧情套路/03-开篇钩子与节奏控制.md", r"B 中短篇 3-10万 \| ([\d,]+) \|", 1, "B桶篇数"),
        ("07-语言风格/02-第二人称写作专论.md", r"第一人称 ([\d.]+)%", 1, "第一人称"),
    ]
    for rel, pat, g, key in CITES:
        f = LIB / rel
        if not f.exists() or not TRUTH.get(key):
            continue
        for m in re.finditer(pat, f.read_text(encoding="utf-8"), re.M):
            if m.group(g).replace(",", "") != TRUTH[key].replace(",", ""):
                drift.append(f"{rel}: {key} 写作 {m.group(g)}，当期 {TRUTH[key]}")
    if drift:
        print("\n⚠️ 派生统计已漂移（语料重建后需同步）：")
        for d in dict.fromkeys(drift):
            print("  " + d)

    # 交付前自查：库内若还有与真值不符的手写数字，在这里报出来
    suspects = []
    for p in LIB.rglob("*.md"):
        # 04-审计报告 与 00/07 工作流程都是历史事故记录（「90 条里有 43 条」是当时的事实），
        # 归一与自查都不碰它们。
        # CHANGELOG 记的是「那一版当时是多少」，291 条是历史事实不是过期数字；
        # 04-审计报告与 07-工作流程同理（「90 条里有 43 条」是当时的实况）。
        # 把历史记录纳入归一，等于把史料改成现状。
        if ("_整理后" in str(p)
                or p.name in ("04-质量审计报告.md", "07-工作流程.md", "CHANGELOG.md")):
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        for pat, truth, label in [
            (r"易混淆词?[^\n]{0,8}?(\d+) *组", s["辨析组"], "易混淆词组数"),
            (r"人设与套路标签[^\n|]{0,12}\| *\*{0,2}(\d+) *条", s["术语03"], "术语03条数"),
            (r"尺度预警与社群黑话[^\n|]{0,12}\| *\*{0,2}(\d+) *条", s["术语04"], "术语04条数"),
            # 以下四项是审计后加的。每一项都在三到四处手写过，加卷时必漏改。
            (r"全库 (\d+) 篇内嵌", s["HTML篇数"], "HTML 内嵌篇数"),
            (r"单文件离线百科，(\d+) 篇", s["HTML篇数"], "HTML 内嵌篇数"),
            (r"(\d+) 篇全文", s["HTML篇数"], "HTML 内嵌篇数"),
            (r"内嵌了全部 (\d+) 篇", s["HTML篇数"], "HTML 内嵌篇数"),
            (r"全部 (\d+) 条一张大表", s["术语总数"], "术语总条数"),
            (r"六卷齐，\*\*(\d+) 条\*\*", s["术语总数"], "术语总条数"),
            (r"角色卡 (\d+) 张", s["角色卡"], "角色卡张数"),
            (r"情景开局卡 (\d+) 张", s["情景卡"], "情景卡张数"),
            # 桥段库与套路库的手写数。14 卷扩族那次，「291」在五个文件里各写了一遍，
            # 「90 条」还在两处滞留——从此交给机器盯。
            (r"00-总表\.md\)，\*\*(\d+) 条\*\*", s["桥段条数"], "桥段条数"),
            (r"（(\d+) 族 \*\*\d+ 条\*\*）", s["桥段族数"], "桥段族数"),
            (r"\d+ 族 \*\*(\d+) 条\*\*", s["桥段条数"], "桥段条数"),
            (r"(\d+) 条按情绪", s["桥段条数"], "桥段条数"),
            (r"日常微剧情 <b>(\d+) 条</b>", s["桥段条数"], "桥段条数"),
            (r"条</b>，(\d+) 个族", s["桥段族数"], "桥段族数"),
            (r"(\d+) 篇 / \d+ 条</td>", s["桥段卷篇数"], "14卷篇数"),
            (r"\d+ 篇 / (\d+) 条</td>", s["桥段条数"], "桥段条数"),
            (r"\| L1 套路 \| (\d+) \|", s["套路数"], "套路数"),
            (r"\*\*L3 桥段\*\* \| \*\*(\d+)\*\*", s["桥段条数"], "桥段条数"),
            (r"就是这里，(\d+) 个族文件", s["桥段族数"], "桥段族数"),
            (r"(\d+) 条日常桥段", s["桥段条数"], "桥段条数"),
            (r"另开一卷，(\d+) 条", s["桥段条数"], "桥段条数"),
            (r"(\d+) 个套路按市场量级", s["套路数"], "套路数"),
            (r"(\d+) 个套路的结构拆解", s["套路数"], "套路数"),
        ]:
            for m in re.finditer(pat, t):
                if truth and int(m.group(1)) != truth:
                    suspects.append(f"{p.relative_to(LIB)}: {label} 写作 {m.group(1)}，实为 {truth}")
    if suspects:
        print("\n⚠️ 仍有手写数字与真值不符：")
        for x in dict.fromkeys(suspects):
            print("  " + x)

    # --check 的返回码：有任何待改/漂移/手写不符即非零，供 pre-commit 与 run.py check 拦截。
    # 落盘模式一律返回 0：它是 rebuild 流水线的中间步，后面还有 build_exports 要跑。
    # 手写数字要人改，但那是**交付前**的闸门（--check、pre-commit）该拦的事；
    # 在这里中止只会把 HTML 与导出停在半新半旧的状态——比数字过期更糟。
    return 1 if (check and (changed or drift or suspects)) else 0


if __name__ == "__main__":
    sys.exit(main())
