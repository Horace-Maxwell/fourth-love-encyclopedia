#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第四爱百科的统一入口。所有流程走这里，不要单独记十几条命令。

    python3 _脚本/run.py check      交付前自查（写完任何内容都跑）
    python3 _脚本/run.py rebuild    重建导出产物（改了主库正文之后）
    python3 _脚本/run.py mine       重跑全部语料统计（加了新素材之后，约 50 分钟）
    python3 _脚本/run.py publish    发布前全套：check + rebuild + preflight
    python3 _脚本/run.py doctor     体检：报出当前状态与待办，不改任何文件

为什么要有这个文件：
  流程一多，人就会漏步骤。本轮踩过的真实错误：
    · 先跑 organize_corpus 再跑 probe_v2，派生目录被当成源，原始文件数虚增 3,140
    · 忘了在 aggregate 之前跑 fix_mojibake，68 篇 GB 文被误判剔除
    · 改完主库忘了重建导出，HTML 里留着旧数字
  顺序不是风格问题，是正确性问题。把它写进代码，就不用记。

probe_v2 不在任何流水线里，是有意的：
  增量加书走 MINE 第一步的 check_new --ingest；probe_v2 是**全量重扫**（换机、重建索引
  时手动跑），且必须在 organize_corpus 之前——否则 _整理后 的硬链接视图会被当成源文件
  （上面第一条事故）。手动跑探针时自己守住这个顺序。
"""

import subprocess
import sys
import time
from pathlib import Path

from paths import LIB, CORPUS

S = LIB / "_脚本"

# ── 流水线定义。顺序即依赖，不可随意调换 ──────────────────────────────
MINE = [
    ("check_new.py --ingest", "查重，只把真新的入库"),
    ("fix_mojibake.py --apply", "还原乱码文件名（必须在聚合之前：文件名是标签统计的数据源）"),
    ("aggregate_corpus.py", "重算统计与四份索引"),
    ("organize_corpus.py", "重建整理视图（必须在探针之后：它产出的硬链接目录不能被当成源）"),
    ("mine_text.py", "正文挖掘（约 40 分钟）"),
    ("mine_vignette.py", "桥段节拍共现挖掘"),
    ("render_mining.py", "渲染 13 卷"),
    ("render_vignette.py", "渲染桥段分布"),
    ("mine_style.py", "文体层挖掘"),
    ("render_style.py", "渲染文体基线"),
    ("build_public_stats.py", "生成可公开的去标识化统计"),
    ("build_langpack.py", "重建权力语言包"),
]
REBUILD = [
    ("build_vignette_index.py", "从 14 卷各族文件重建桥段总表（必须在归一之前：总表里有条数）"),
    ("build_scene_cards.py", "重建情景卡（卡内容在 scene_cards_data/，张数进数字归一）"),
    ("sync_index.py", "全库数字归一"),
    ("build_exports.py", "重建三种导出"),
]
CHECK = [
    ("check_compliance.py", "规约合规（三行头 / 分级 / 安全框架 / 文风铁律 / 引用配额 / 卡片 / 渲染种子）"),
    ("sync_index.py --check", "数字漂移自查"),
]
# 先重建再检查：检查的对象是最终树。旧顺序（先 CHECK）会在数字尚未归一时
# 把 publish 卡死在第一步，而那些数字本来就是接下来那步 rebuild 要修的。
PUBLISH = REBUILD + CHECK + [("preflight.py", "发布前风险扫描")]


def run(cmd, why, stop_on_fail=True):
    print(f"\n\033[1m▶ {cmd}\033[0m　{why}")
    t0 = time.time()
    r = subprocess.run([sys.executable] + cmd.split(), cwd=S)
    dt = time.time() - t0
    ok = r.returncode == 0
    print(f"  {'✔' if ok else '✗'} {dt:.0f}s")
    if not ok and stop_on_fail:
        print(f"\n\033[31m在「{cmd}」处中止。修好再继续，不要跳过。\033[0m")
        sys.exit(1)
    return ok


def doctor():
    """只读体检。"""
    print("═══ 体检 ═══\n")
    print(f"库根目录  {LIB}")
    print(f"藏书目录  {CORPUS}  {'✔ 存在' if CORPUS.exists() else '✗ 不存在（语料类脚本不可用）'}")

    md = [p for p in LIB.rglob("*.md") if "_整理后" not in str(p)]
    import re
    cn = sum(len(re.findall(r"[一-鿿]", p.read_text(encoding="utf-8", errors="ignore")))
             for p in md)
    cards = len(list((LIB / "11-模板包" / "角色卡").glob("*.json")))
    # 精读笔记目录（原 09 卷）不入库，fresh clone 上没有——报「本机无」而不是 0，
    # 0 会读成「一篇都没读过」，那是另一件事
    notes_dir = LIB / "09-拆解卡"
    notes = len(list(notes_dir.glob("*.md"))) if notes_dir.is_dir() else None
    print(f"\n规模      {cn/10000:.1f} 万汉字 / {len(md)} 篇")
    print(f"角色卡    {cards} 张")
    print(f"精读笔记  {notes if notes is not None else '—（本机无，该目录不入库）'}")

    print("\n── 检查项 ──")
    for cmd, why in CHECK:
        run(cmd, why, stop_on_fail=False)
    if (LIB / ".gitignore").exists():
        run("preflight.py", "发布前风险扫描", stop_on_fail=False)

    print("\n── 待办 ──")
    sched = LIB / "10-藏书索引" / "精读排期表.md"
    if sched.exists():
        n = len(re.findall(r"^\| *\d+ *\|", sched.read_text(encoding="utf-8"), re.M))
        print(f"  精读排期表还有 {n} 篇候选未成卡")
    else:
        print("  （精读排期表不在仓库内，属本地私有）")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "rebuild", "mine", "publish", "doctor"):
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]

    if cmd == "doctor":
        doctor(); return

    steps = {"check": CHECK, "rebuild": REBUILD, "mine": MINE, "publish": PUBLISH}[cmd]
    if cmd == "mine":
        if not CORPUS.exists():
            print(f"藏书目录不存在：{CORPUS}\n"
                  "先 export GB_CORPUS=/path/to/your/corpus")
            sys.exit(1)
        print("注意：mine 会重跑全部语料统计，约 50 分钟。")

    t0 = time.time()
    for c, why in steps:
        run(c, why)
    print(f"\n\033[32m✅ {cmd} 完成，用时 {(time.time()-t0)/60:.1f} 分钟\033[0m")
    if cmd == "mine":
        print("语料变了，接着跑：python3 _脚本/run.py rebuild")
    if cmd == "publish":
        print("可以推送了。首次：git remote add origin <url> && git push -u origin main")


if __name__ == "__main__":
    main()
