#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新素材查重器 —— 加了新书之后先跑这个，看有多少是真新的。

本库的语料来自多个重叠的合集打包，实测重复率极高（一次 4025 篇的
「新增」经 MD5 校验 100% 是已有内容的副本）。先查重再入库，能省掉
大量无意义的扫描与统计失真。

用法：
    python3 check_new.py                 # 扫全库，报告新增/重复
    python3 check_new.py --ingest        # 查重后把真新的增量扫描入库
    python3 check_new.py --path 某目录    # 只查某个目录
"""

import os
import sys
import json
import hashlib
import argparse
import tempfile
from pathlib import Path
from collections import Counter

from paths import CORPUS, JSONL
from paths import require_corpus

ROOT = CORPUS


def md5_of(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    require_corpus()
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=None, help="只查这个目录")
    ap.add_argument("--ingest", action="store_true", help="把真新的扫描入库")
    a = ap.parse_args()

    known_md5, known_path = set(), set()
    if JSONL.exists():
        with open(JSONL, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                known_md5.add(r["md5"])
                known_path.add(r["path"])
    print(f"库内已知 {len(known_md5):,} 个唯一内容 / {len(known_path):,} 条路径记录\n")

    scan_root = Path(a.path) if a.path else ROOT
    files = sorted(set(str(p) for p in scan_root.rglob("*.txt")) |
                   set(str(p) for p in scan_root.rglob("*.TXT")))
    print(f"扫描 {scan_root}：{len(files):,} 个 txt")

    new_path = [f for f in files if f not in known_path]
    print(f"  路径未记录的：{len(new_path):,}\n")
    if not new_path:
        print("✅ 没有任何新文件。")
        return

    print("正在校验内容指纹…")
    truly_new, dup_of_known, seen_now = [], 0, {}
    for i, f in enumerate(new_path, 1):
        p = Path(f)
        try:
            m = md5_of(p)
        except OSError:
            continue
        if m in known_md5 or m in seen_now:
            dup_of_known += 1
        else:
            seen_now[m] = f
            truly_new.append(f)
        if i % 1500 == 0:
            print(f"  {i:,}/{len(new_path):,}")

    print(f"\n{'='*60}")
    print(f"路径新增 {len(new_path):,} 个")
    print(f"  其中内容重复（已在库中或批内自重）：{dup_of_known:,}"
          f"（{dup_of_known/len(new_path)*100:.1f}%）")
    print(f"  ✨ 真正的新内容：{len(truly_new):,}")

    if truly_new:
        size = sum(Path(f).stat().st_size for f in truly_new)
        print(f"     合计 {size/1e6:.0f} MB")
        c = Counter(str(Path(f).parent.relative_to(ROOT)).split("/")[0]
                    for f in truly_new)
        print("\n  新内容所在目录：")
        for d, n in c.most_common(10):
            print(f"    {n:5d}  {d[:58]}")
        print("\n  样例：")
        for f in truly_new[:8]:
            print(f"    · {Path(f).name[:70]}")

        # 清单落临时目录，不落库内（落进去就进公开仓库、被检查器扫）。
        # 原先这里硬编码着某一次会话的 scratchpad 路径，换会话就写不出去。
        out = Path(os.environ.get("GB_TMP") or tempfile.gettempdir()) / "truly_new.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(truly_new), encoding="utf-8")
        print(f"\n  清单已写入 {out}")

        if a.ingest:
            print("\n开始增量入库…")
            sys.path.insert(0, str(Path(__file__).parent))
            from probe_v2 import probe_one
            from concurrent.futures import ProcessPoolExecutor, as_completed
            recs, done = [], 0
            with ProcessPoolExecutor(
                    max_workers=max(2, (os.cpu_count() or 4) - 2)) as ex:
                futs = [ex.submit(probe_one, f) for f in truly_new]
                for fu in as_completed(futs):
                    done += 1
                    try:
                        r = fu.result()
                    except Exception:
                        r = None
                    if r and "skip" not in r:
                        r["重复于"] = None
                        recs.append(r)
                    if done % 500 == 0:
                        print(f"  {done}/{len(truly_new)}")
            with open(JSONL, "a", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"已入库 {len(recs)} 篇。")
            print("接着跑：python3 _脚本/aggregate_corpus.py")
    else:
        print("\n✅ 全部是已有内容的副本，无需入库。")


if __name__ == "__main__":
    main()
