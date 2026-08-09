#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
压缩包解压器 —— 把 素材语料/ 下的 zip 全部摊平成 txt。

处理的坑：
  · zip 里的中文文件名多为 CP936(GBK) 编码，Python 会按 CP437 误解码成乱码
  · 部分包损坏 / 分卷 / 加密，需跳过并记录
  · 嵌套目录、嵌套 zip
  · 同名文件冲突

解压产物落在 素材语料/_解压出的文件/<压缩包名>/ 下，与原始 txt 同级参与后续扫描。
用法：
    python3 extract_archives.py [--dry-run]
"""

import sys
import zipfile
import shutil
import subprocess
from pathlib import Path

from paths import CORPUS
from paths import require_corpus

ROOT = CORPUS
OUT_ROOT = ROOT / "_解压出的文件"
LOG = []


def fix_name(name: str) -> str:
    """修复 zip 里被 CP437 误解码的中文文件名。"""
    # zipfile 在没有 UTF-8 flag 时按 cp437 解码；还原成字节再按 GBK 系解
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name          # 本来就是 UTF-8 正确名，不动
    for enc in ("gb18030", "big5", "shift_jis"):
        try:
            decoded = raw.decode(enc)
            # 解出来含中日韩字符才算成功
            if any("一" <= c <= "鿿" for c in decoded):
                return decoded
        except UnicodeDecodeError:
            continue
    return name


def safe_component(s: str) -> str:
    """把一个路径片段变安全（去掉分隔符与控制字符）。"""
    s = s.replace("/", "_").replace("\\", "_").replace("\x00", "")
    return s.strip() or "_"


def extract_zip(zpath: Path, dest: Path, dry=False) -> tuple:
    """返回 (成功文件数, 状态字符串)"""
    try:
        zf = zipfile.ZipFile(zpath)
    except (zipfile.BadZipFile, OSError) as e:
        # 退回系统 unzip / 7z 试一次
        if not dry:
            dest.mkdir(parents=True, exist_ok=True)
            for cmd in (["unzip", "-o", "-qq", str(zpath), "-d", str(dest)],
                        ["7z", "x", "-y", f"-o{dest}", str(zpath)]):
                try:
                    r = subprocess.run(cmd, capture_output=True, timeout=180)
                    if r.returncode == 0:
                        n = len(list(dest.rglob("*.txt")))
                        if n:
                            return n, f"外部工具解压成功({cmd[0]})"
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            if dest.exists() and not any(dest.iterdir()):
                dest.rmdir()
        return 0, f"损坏/不可读: {type(e).__name__}"

    count = 0
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = fix_name(info.filename)
            if not name.lower().endswith((".txt", ".text")):
                continue
            parts = [safe_component(p) for p in Path(name).parts if p not in ("..", "/")]
            if not parts:
                continue
            target = dest.joinpath(*parts)
            if dry:
                count += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # 同名冲突加后缀
            if target.exists():
                stem, suf = target.stem, target.suffix
                i = 2
                while target.exists():
                    target = target.with_name(f"{stem}__{i}{suf}")
                    i += 1
            try:
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                count += 1
            except (RuntimeError, zipfile.BadZipFile, OSError) as e:
                LOG.append(f"    条目失败 {name[:50]}: {e}")
    return count, "ok"


def main():
    require_corpus()
    dry = "--dry-run" in sys.argv
    zips = sorted(p for p in ROOT.rglob("*.zip") if OUT_ROOT not in p.parents)
    sevenz = sorted(p for p in ROOT.rglob("*.7z") if OUT_ROOT not in p.parents)

    print(f"发现 {len(zips)} 个 zip、{len(sevenz)} 个 7z\n")
    total, ok_n, fail = 0, 0, []

    for i, z in enumerate(zips, 1):
        rel = z.relative_to(ROOT)
        dest = OUT_ROOT / safe_component(str(rel).replace("/", "__")[:-4])
        n, status = extract_zip(z, dest, dry)
        total += n
        if status.startswith("ok") or "成功" in status:
            ok_n += 1
        else:
            fail.append((str(rel), status))
        if i % 20 == 0 or i == len(zips):
            print(f"  [{i}/{len(zips)}] 累计解出 {total} 个 txt")

    for s in sevenz:
        dest = OUT_ROOT / safe_component(s.stem)
        if not dry:
            dest.mkdir(parents=True, exist_ok=True)
            try:
                r = subprocess.run(["7z", "x", "-y", f"-o{dest}", str(s)],
                                   capture_output=True, timeout=300)
                n = len(list(dest.rglob("*.txt")))
                total += n
                print(f"  7z {s.name}: {n} 个 txt")
            except FileNotFoundError:
                fail.append((s.name, "未安装 7z"))

    print(f"\n{'='*60}")
    print(f"解压完成：{ok_n}/{len(zips)} 个包成功，共解出 {total} 个 txt")
    if fail:
        print(f"\n失败 {len(fail)} 个：")
        for name, why in fail[:30]:
            print(f"  · {name[:60]} — {why}")
    if LOG:
        print(f"\n条目级警告 {len(LOG)} 条（前10）：")
        for l in LOG[:10]:
            print(l)


if __name__ == "__main__":
    main()
