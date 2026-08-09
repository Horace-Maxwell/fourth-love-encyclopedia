#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
藏书阅读器 —— 精读时用它取文本，自动处理编码地狱（GBK/UTF-16/BOM/CRLF）。

用法：
    python3 read_book.py "关键词"                    # 模糊匹配文件并显示概况
    python3 read_book.py "关键词" --at 0 --len 8000  # 读指定位置的片段
    python3 read_book.py "关键词" --pct 50 --len 6000 # 读全文 50% 处的片段
    python3 read_book.py "关键词" --toc              # 只列章节目录
    python3 read_book.py "关键词" --chapter 12       # 读第 12 章
    python3 read_book.py --list                      # 列出全部藏书
"""

import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from probe_corpus import decode_bytes, CORPUS_DIRS, CHAPTER_PATTERNS


# 走语料索引，不走目录扫描。两个理由：
#   ① CORPUS_DIRS 是 v1 时代的两个目录且非递归，语料扩容后覆盖不全
#   ② **磁盘上有 2,301 个文件名是乱码**（见 _脚本/fix_mojibake.py），
#      按磁盘名搜中文书名必然搜不到；索引里的「文件名」字段是还原后的
INDEX = Path(__file__).resolve().parent.parent / "10-藏书索引" / "_语料库.jsonl"


def all_books():
    """返回 [(显示名, 磁盘路径), ...]，按显示名排序。"""
    import json
    seen, out = set(), []
    for line in INDEX.open(encoding="utf-8"):
        r = json.loads(line)
        if r["md5"] in seen:
            continue
        seen.add(r["md5"])
        name = r.get("文件名") or r["path"].rsplit("/", 1)[-1]
        out.append((name, Path(r["path"])))
    return sorted(out)


def find_book(keyword):
    books = all_books()
    hits = [(n, p) for n, p in books if keyword in n]
    if not hits:
        norm = re.sub(r"[^\w]", "", keyword)
        hits = [(n, p) for n, p in books
                if norm and norm in re.sub(r"[^\w]", "", n)]
    if not hits:
        # 最后再退化到磁盘名（少数索引外的文件）
        hits = [(p.name, p) for p in Path(INDEX).parent.parent.parent.rglob("*.txt")
                if keyword in p.name][:5]
    if not hits:
        print(f"未找到匹配「{keyword}」的藏书。用 --list 查看全部。")
        sys.exit(1)
    if len(hits) > 1:
        print(f"匹配到 {len(hits)} 个，取第一个：{hits[0][0][:60]}")
        for n, _ in hits[1:6]:
            print(f"   · {n[:60]}")
    return hits[0][1]


def load(path):
    text, enc = decode_bytes(path.read_bytes())
    return text.replace("\r\n", "\n").replace("\r", "\n"), enc


def chapters_of(text):
    out = []
    pos = 0
    for line in text.split("\n"):
        if any(p.search(line) for p in CHAPTER_PATTERNS):
            out.append((pos, line.strip()[:60]))
        pos += len(line) + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--toc", action="store_true")
    ap.add_argument("--at", type=int, default=None, help="起始字符位置")
    ap.add_argument("--pct", type=float, default=None, help="起始位置(全文百分比)")
    ap.add_argument("--len", type=int, default=6000, dest="length")
    ap.add_argument("--chapter", type=int, default=None, help="第 N 章(1起)")
    a = ap.parse_args()

    if a.list:
        for p in all_books():
            print(f"{p.stat().st_size/1024:8.0f}KB  {p.name}")
        return

    if not a.keyword:
        ap.print_help()
        return

    path = find_book(a.keyword)
    text, enc = load(path)
    chs = chapters_of(text)
    total = len(text)

    if a.at is None and a.pct is None and a.chapter is None and not a.toc:
        print(f"《{path.name}》")
        print(f"编码 {enc} ／ {total:,} 字符 ／ {total/10000:.1f} 万字 ／ {len(chs)} 章")
        print(f"路径 {path}")
        print("\n── 开头 2500 字 ──")
        print(text[:2500])
        return

    if a.toc:
        print(f"《{path.name}》 {len(chs)} 章 ／ {total/10000:.1f} 万字\n")
        for i, (pos, title) in enumerate(chs, 1):
            print(f"{i:4d}  [{pos/total*100:5.1f}%  字符{pos:>9,}]  {title}")
        return

    if a.chapter is not None:
        if not 1 <= a.chapter <= len(chs):
            print(f"章号越界，本书 {len(chs)} 章")
            sys.exit(1)
        start = chs[a.chapter - 1][0]
        end = chs[a.chapter][0] if a.chapter < len(chs) else total
        seg = text[start:min(end, start + a.length)]
        print(f"── 第{a.chapter}章 [{start/total*100:.1f}%] "
              f"{'(截断)' if end - start > a.length else ''} ──")
        print(seg)
        return

    start = a.at if a.at is not None else int(total * a.pct / 100)
    print(f"── 字符 {start:,} [{start/total*100:.1f}%] 起 {a.length} 字 ──")
    print(text[start:start + a.length])


if __name__ == "__main__":
    main()
