#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成可公开的去标识化语料统计。

为什么需要它：
  `10-藏书索引/` 是本地私人收藏的逐条清单（书名 + 作者 + 尺度），公开它等同于
  发布一份藏书目录，所以整卷不进仓库（见 00-编纂规约/06-发布风险评估）。
  但全库大量结论建立在那批统计上，读者若完全无从核验，结论就成了单方面断言。

  折中办法：发布**聚合层**。本脚本产出的表里没有任何作品标识——
  没有书名、没有作者、没有文件名、没有路径，只有分布与占比。
  风险为零，而它承载了本库绝大部分数据结论的依据。

产物：`10-藏书索引-公开/语料统计.md`（该目录进仓库，`10-藏书索引/` 不进）

用法：python3 build_public_stats.py
"""

import sys
from collections import Counter
from pathlib import Path

from paths import LIB

sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT_DIR = LIB / "10-藏书索引-公开"


def table(rows, cols):
    head = ["| " + " | ".join(cols) + " |",
            "|" + "|".join("---:" if c.endswith(("数", "率", "%", "字")) else "---"
                           for c in cols) + "|"]
    return head + ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]


def main():
    from aggregate_corpus import R, CANON, TAXONOMY, tag_text_of

    N = CANON["分析口径篇数"]
    L = ["# 语料统计（公开版）", "",
         "`G` ｜ 无预警 ｜ `数据表`",
         "来源：本地私人收藏的聚合统计，由 "
         "[`_脚本/build_public_stats.py`](../_脚本/build_public_stats.py) 生成", "",
         "> 提示：本篇只讲分布与占比，不含任何作品标识，没有书名、作者、文件名或路径。",
         "> 逐条清单属私人收藏目录，不随本仓库发布，理由见"
         "[06-发布风险评估](../00-编纂规约/06-发布风险评估.md)。", "",
         "---", "", "## 一、语料规模", ""]
    L += table([
        ("原始文件", f"{CANON['原始文件']:,}"),
        ("MD5 去重后", f"{CANON['MD5去重']:,}"),
        ("剔除非本类型", f"{CANON['剔除篇数']:,}"),
        ("入库（分析口径）", f"**{N:,}**"),
        ("其中独立作品", f"{CANON['独立作品数']:,}"),
        ("总字数", f"{CANON['分析口径字数']:,}（约 {CANON['分析口径字数']/1e8:.2f} 亿）"),
    ], ["阶段", "篇数"])
    L += ["",
          "同一部作品常有多份存档，所以「入库篇数」大于「独立作品数」。",
          "全库统计一律以入库篇数为准，正文挖掘按独立作品去重后进行。", ""]

    # ── 亚型分布 ──
    L += ["---", "", "## 二、亚型分布", "",
          "统计口径：文件名与作者自述文案中出现该类关键词的篇数。这是下限，作者没标的不计入。", ""]
    for dim, items in TAXONOMY.items():
        rows = []
        for canon, alts in items:
            n = sum(1 for r in R if any(w in tag_text_of(r) for w in alts))
            if n:
                rows.append((canon, f"{n:,}", f"{n/N*100:.1f}%"))
        if rows:
            rows.sort(key=lambda x: -int(x[1].replace(",", "")))
            L += [f"### {dim}", ""] + table(rows, ["类别", "篇数", "占比"]) + [""]

    # ── 体量、尺度、人称、编码 ──
    def dist(key, buckets, label):
        rows = []
        for name, test in buckets:
            n = sum(1 for r in R if test(r))
            rows.append((name, f"{n:,}", f"{n/N*100:.1f}%"))
        return [f"## {label}", ""] + table(rows, ["档", "篇数", "占比"]) + [""]

    L += ["---", ""]
    L += dist("万字", [
        ("短篇 <3 万", lambda r: r["万字"] < 3),
        ("中短篇 3–10 万", lambda r: 3 <= r["万字"] < 10),
        ("长篇 10–30 万", lambda r: 10 <= r["万字"] < 30),
        ("大长篇 30–60 万", lambda r: 30 <= r["万字"] < 60),
        ("超长 ≥60 万", lambda r: r["万字"] >= 60),
    ], "三、体量分布")

    L += ["---", ""]
    sc = Counter(r.get("尺度") for r in R)
    L += ["## 四、尺度分布（机器判定）", "",
          "判定依据：露骨词密度（每万字）。"] + [""] + table(
        [(k or "未判定", f"{v:,}", f"{v/N*100:.1f}%")
         for k, v in sorted(sc.items(), key=lambda x: -x[1])],
        ["尺度", "篇数", "占比"]) + [""]

    L += ["---", ""]
    p1 = sum(1 for r in R if r.get("我占比", 0) >= 0.35)
    L += ["## 五、叙事人称分布", "",
          "文件名与文案从不标注人称，这一项只能从正文推定。", ""]
    L += table([("第一人称为主", f"{p1:,}", f"{p1/N*100:.1f}%"),
                ("第三人称为主", f"{N-p1:,}", f"{(N-p1)/N*100:.1f}%")],
               ["人称推定", "篇数", "占比"])

    L += ["", "---", "", "## 六、文件编码分布（工程参考）", ""]
    L += table([(k, f"{v:,}") for k, v in Counter(r["编码"] for r in R).most_common()],
               ["编码", "篇数"])
    L += ["",
          "UTF-8-BOM 与 GB18030 并存，另有少量 UTF-16。",
          "此外 2,316 个文件名是 GBK 字节被按 Mac Roman 解码的乱码，已还原 99.4%。", ""]

    L += ["---", "",
          "相关条目："
          "[13-语料挖掘](../13-语料挖掘/README.md) · "
          "[00-编纂规约/06-发布风险评估](../00-编纂规约/06-发布风险评估.md)", "",
          "> 编纂：2026-08。数字随语料变动，重跑本脚本即可更新。", ""]

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "语料统计.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"→ {OUT_DIR / '语料统计.md'}")
    print(f"  {N:,} 篇的聚合统计，零作品标识")


if __name__ == "__main__":
    main()
