#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前扫描：检查**将要进入仓库的文件**里有没有不该公开的东西。

与 check_compliance.py 的分工：
  check_compliance  查内容质量与规约合规（面向读者）
  preflight         查发布风险（面向公开）——路径、密钥、藏书清单、隐私

它按 .gitignore 判断哪些文件会进仓库，所以先有 .gitignore 再跑它。

用法：python3 preflight.py
退出码非 0 表示有阻断项，不应发布。
"""

import re
import subprocess
import sys
from pathlib import Path

from paths import LIB

FAIL, WARN = [], []

# 会泄露发布者身份或本机环境的模式
BLOCKERS = [
    ("本机绝对路径", re.compile(r"/Users/[a-z][a-z0-9_.-]*/|/home/[a-z][a-z0-9_.-]*/", re.I)),
    ("疑似密钥", re.compile(r"(?i)(api[_-]?key|secret|passwd|password)\s*[=:]\s*['\"][^'\"]{8,}")),
    # 排除 URL 路径段里的十六进制串（如高校站点的文章 ID），那不是密钥
    ("裸 token", re.compile(r"(?<![/\w])[A-Fa-f0-9]{32,}(?![\w./-])")),
]
# 藏书清单的特征：连续多行「书名 + 作者」
CATALOG = re.compile(r"(作者[：:]\s*\S+.*\n.*){5,}")


def tracked_files():
    """按 .gitignore 判断会进仓库的文件。未 git init 时用 check-ignore 逐个判。"""
    files = [p for p in LIB.rglob("*")
             if p.is_file() and ".git/" not in str(p)]
    gi = LIB / ".gitignore"
    if not gi.exists():
        return files
    try:
        rel = [str(p.relative_to(LIB)) for p in files]
        # git 默认对非 ASCII 路径做八进制转义（core.quotePath），
        # 直接比对字符串必然落空。用 -z 拿原始字节，按 NUL 切分。
        r = subprocess.run(["git", "-c", "core.quotePath=false",
                            "check-ignore", "-z", "--stdin"], cwd=LIB,
                           input="\0".join(rel).encode(), capture_output=True)
        ignored = set(r.stdout.decode("utf-8", "replace").split("\0"))
    except FileNotFoundError:
        ignored = set()
    return [p for p in files if str(p.relative_to(LIB)) not in ignored]


def main():
    files = tracked_files()
    text_files = [p for p in files
                  if p.suffix in (".md", ".py", ".json", ".html", ".txt", ".yml", ".toml")]

    for p in text_files:
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(p.relative_to(LIB))
        for name, pat in BLOCKERS:
            hits = pat.findall(t)
            if hits:
                # paths.py 的文档字符串里会举例，属说明性质
                if rel == "_脚本/paths.py":
                    continue
                FAIL.append(f"{name}｜{rel}｜{len(hits)} 处｜样例 {str(hits[0])[:44]}")
        if p.suffix == ".md" and CATALOG.search(t) and "作者" in t:
            n = len(re.findall(r"作者[：:]", t))
            if n >= 30:
                FAIL.append(f"疑似藏书清单｜{rel}｜{n} 处「作者：」")
            elif n >= 8:
                WARN.append(f"作者名较多｜{rel}｜{n} 处")

    # 目录级检查
    for d, why in (("10-藏书索引", "藏书逐条清单"), ("素材语料", "藏书本体"),
                   ("_收件箱", "未消化素材")):
        if any(d in p.parts for p in files):
            FAIL.append(f"应被忽略的目录仍在仓库内｜{d}（{why}）")
    for pat, why in (("*.jsonl", "原始语料索引"),
                     ("_正文挖掘.json", "未过滤的逐字串"),
                     ("_文体挖掘.json", "未过滤的逐字串")):
        for p in LIB.rglob(pat):
            if p in files:
                FAIL.append(f"应被忽略的文件仍在仓库内｜{p.relative_to(LIB)}（{why}）")

    # 必备文件
    for need in (".gitignore", "LICENSE.md", "README.md"):
        if not (LIB / need).exists():
            FAIL.append(f"缺少必备文件｜{need}")

    print(f"扫描 {len(files)} 个文件（其中文本 {len(text_files)} 个）\n")
    if WARN:
        print(f"⚠️ 提示 {len(WARN)} 项：")
        for w in WARN[:10]:
            print("   " + w)
        print()
    if FAIL:
        print(f"✗ 阻断 {len(FAIL)} 项：")
        for f in FAIL:
            print("   " + f)
        return 1
    print("✅ 未发现阻断项，可以发布")
    return 0


if __name__ == "__main__":
    sys.exit(main())
