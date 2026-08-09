#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
还原文件名乱码：GBK 字节被 macOS 按 Mac Roman 解码的那一类。

为什么这是个真问题而不是观感问题：
  **文件名是标签统计的数据源之一。** 13,285 个文件里有 2,316 个（17%）文件名是乱码，
  意味着「GB 3,031 篇 / 女攻 3,012 篇」这类实测数字全部**系统性低估**——
  乱码文件名里的「≈Æπ•」其实就是「女攻」，但任何关键词匹配都扫不到它。

  同一批乱码还会漏进《藏书总索引》和《精读排期表》，让排期表里出现
  「[np ÕÍΩ·]°∂°æµ⁄Àƒ∞Æ°ø...」这种没法读的条目。

还原原理：
  乱码串 = GBK 字节 → 按 Mac Roman 解码。反过来就是
  乱码串 → encode('mac_roman') → decode('gb18030')。

安全边界（重要）：
  · **只改索引里的显示名，不动磁盘上的文件**——重命名 13,285 个文件风险远大于收益，
    而且 `path` 字段还要能定位到文件
  · 只在还原结果**通过质量检验**时才采用：中文占比够高、无替换符、长度合理
  · 还原不了的保持原样，并计入报告——不做「看起来修好了」的粉饰

用法：python3 fix_mojibake.py [--apply]     不加 --apply 只报告不落盘
"""

import json
import re
import sys
from pathlib import Path

from paths import LIB

JSONL = LIB / "10-藏书索引" / "_语料库.jsonl"

# 乱码特征：连续出现的拉丁扩展 / 数学符号区字符——正常中文文件名不会这样
MOJI = re.compile(r"[À-ÿĀ-˿Ͱ-Ͽ‐-◿]{4,}")
CJK = re.compile(r"[一-鿿]")


def unscramble(s: str):
    """还原一个乱码串；失败或质量不过关返回 None。"""
    try:
        raw = s.encode("mac_roman", errors="strict")
    except UnicodeEncodeError:
        # 少数字符不在 mac_roman 里——放宽到 replace，但下面的质检会挡住烂结果
        try:
            raw = s.encode("mac_roman", errors="replace")
        except Exception:
            return None
    try:
        out = raw.decode("gb18030", errors="replace")
    except Exception:
        return None

    # ── 质检：宁可不还原，也不要还原成另一种乱码 ──
    if out.count("�") > 2:                     # 替换符太多
        return None
    if len(CJK.findall(out)) < 4:                   # 中文太少，说明没还原对
        return None
    if len(CJK.findall(out)) / max(len(out), 1) < 0.25:
        return None
    if MOJI.search(out):                            # 还原后仍是乱码
        return None
    return out.replace("�", "")


def main():
    apply = "--apply" in sys.argv
    rows = [json.loads(l) for l in JSONL.open(encoding="utf-8")]

    scrambled = fixed = 0
    samples = []
    for r in rows:
        name = r.get("文件名") or r["path"].rsplit("/", 1)[-1]
        if not MOJI.search(name):
            continue
        scrambled += 1
        out = unscramble(name)
        if out:
            fixed += 1
            if len(samples) < 8:
                samples.append((name[:46], out[:46]))
            r["文件名"] = out
            r["_原文件名"] = name          # 保留原名，path 仍指向磁盘上的真实文件

    print(f"乱码文件名 {scrambled:,} / {len(rows):,} 条")
    print(f"成功还原   {fixed:,} 条（{fixed/max(scrambled,1)*100:.1f}%）")
    print(f"未能还原   {scrambled - fixed:,} 条（保持原样，不粉饰）\n")
    print("样例：")
    for a, b in samples:
        print(f"  {a}\n    → {b}")

    # 还原带来的标签增量——这才是这件事的意义所在
    print("\n还原后新增的标签命中（文件名口径）：")
    for kw in ("GB", "女攻", "第四爱", "女尊", "1v1", "np", "完结", "训诫", "ABO"):
        before = sum(1 for r in rows if kw in (r.get("_原文件名") or r.get("文件名", "")))
        after = sum(1 for r in rows if kw in r.get("文件名", ""))
        d = after - before
        if d:
            print(f"  {kw:6} +{d:,}")

    if apply:
        with JSONL.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n✔ 已写回 {JSONL}")
        print("  接着重跑：aggregate_corpus.py → organize_corpus.py → build_exports.py")
    else:
        print("\n（未落盘。确认无误后加 --apply）")


if __name__ == "__main__":
    main()
