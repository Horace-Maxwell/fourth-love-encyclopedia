#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二轮正文挖掘：**文体层**。

与 mine_text.py 的分工：
  mine_text   抽「写了什么」——人名、命令句、设定元素        素材层
  mine_style  抽「怎么写的」——对白密度、段落长度、修饰语偏好  文体层

这一轮存在的理由：
  07 卷《反 AI 味指南》列了 17 条 AI 写作病，但它的对照面一直是**编者的判断**——
  「人不会这么写」。那是一句没有数据的断言。
  这个脚本给出真人作者的**量化基线**：五千多位作者实际的对白占比是多少、
  段落多长、最爱用哪些副词与四字词。有了基线，「AI 味」才从审美判断变成可测量的偏差。

抽六类：
  1. 对白占比        引号内字数 / 总字数
  2. 段落长度分布    中位数、P25、P75，以及超长段占比
  3. 高频副词        「地」字前的修饰语——中文里副词的主要挂载点
  4. 高频四字词      成语与四字格，AI 最爱堆的东西
  5. 句末语气词      呢/吧/啊/嘛/呗——口语度的直接指标
  6. 结局类型        末 2% 文本的 HE/BE/开放判定

用法：python3 mine_style.py [--workers N] [--limit N]
"""

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from paths import LIB

OUT = LIB / "10-藏书索引" / "_文体挖掘.json"
SAMPLE = 400_000


# 零宽水印：资源站往正文里插不可见字符做溯源标记。
# 实测 92 / 6,045 篇含它，最严重的单篇有 62,479 个（占该篇 5.3%）。
# 全库层面只虚增 0.12%，但**这些篇的单篇字数虚高最多 5.6%**，
# 且它会切断词语（「妻​主」匹配不到「妻主」），必须在解码时就剥掉。
ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u180e\u00ad]")


def _strip_zw(s):
    return ZERO_WIDTH.sub("", s)


def decode_bytes(raw: bytes):
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace").lstrip("﻿")
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace").lstrip("﻿")
    if raw.startswith(b"\xef\xbb\xbf"):
        return _strip_zw(raw[3:].decode("utf-8", errors="replace"))
    try:
        return _strip_zw(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return _strip_zw(raw.decode("gb18030", errors="replace"))


QUOTE = re.compile(r"[「『“\"]([^」』”\"\n]{1,400})[」』”\"]")
# 「地」前的词就是副词——中文副词最稳定的锚点。
# 但「他猛地」会被切成「他猛」，所以要把前置代词剥掉。
ADV = re.compile(r"([一-鿿]{2,5})地(?=[一-鿿])")
PRON_HEAD = re.compile(r"^[他她我你它们]+")
IDIOM = re.compile(r"(?<![一-鿿])([一-鿿]{4})(?![一-鿿])")
# 四字格里混进来的：站头词、章节标记、以及「XX说」这类人名+动词
IDIOM_BAD = re.compile(r"章节|编号|更新|未完|待续|完结|番外|作者|正文|字数|收藏|"
                       r"[说道问答笑喊叫想看听]$|^[的了是在有和与]")
MOOD = re.compile(r"([呢吧啊嘛呗哦呀哟嘞])[。！？…，]")
AD = re.compile(r"更新|书单|资源|网盘|汇总|求文|popo|韩漫|公主号|笨笨|整理|微信|QQ|http")

# 只留有判别力的收尾标记。「孩子」「回家」「笑了」这类通用词一放进去，
# 八成的书都会被判 HE——那测的是词表宽度，不是结局分布。
HE = ("白头到老", "一生一世", "长长久久", "从此以后", "余生", "圆满", "团圆",
      "婚礼", "大婚", "成亲", "求婚", "喜结", "百年好合", "永远在一起", "白首")
BE = ("葬礼", "墓前", "永远失去", "再也没有", "遗书", "自尽", "殉", "陪葬",
      "再也不见", "没有以后", "最后一面", "永别", "此生不复", "阴阳两隔")
OPEN = ("也许", "或许", "谁知道", "不知道以后", "故事还没", "未完", "会怎样",
        "谁也说不准", "另一个故事", "留给")


def one(path_str):
    p = Path(path_str)
    try:
        text = decode_bytes(p.read_bytes())
    except OSError:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")[:SAMPLE]
    if len(text) < 5000:
        return None

    cn_total = len(re.findall(r"[一-鿿]", text))
    if cn_total < 3000:
        return None

    # ① 对白占比
    dia = sum(len(re.findall(r"[一-鿿]", m.group(1))) for m in QUOTE.finditer(text))
    dia_ratio = dia / cn_total

    # ② 段落长度（只算有中文的行，跳过站头广告）
    paras = [len(re.findall(r"[一-鿿]", l)) for l in text.split("\n")
             if len(re.findall(r"[一-鿿]", l)) >= 4 and not AD.search(l)]
    paras.sort()
    if len(paras) < 20:
        return None
    n = len(paras)
    p25, p50, p75 = paras[n // 4], paras[n // 2], paras[n * 3 // 4]
    long_ratio = sum(1 for x in paras if x > 200) / n

    # ③④⑤ 词汇偏好
    adv = Counter()
    for m in ADV.finditer(text):
        w = PRON_HEAD.sub("", m.group(1))
        if len(w) >= 2:
            adv[w] += 1
    # 四字词回传的是**本篇是否出现**（文档频次），不是出现次数——
    # 人名与专有名词在单篇里能出现几百次，用词频排就全是它们。
    idiom = Counter(w for w in {m.group(1) for m in IDIOM.finditer(text)}
                    if not IDIOM_BAD.search(w))
    mood = Counter(m.group(1) for m in MOOD.finditer(text))

    # ⑥ 结尾标记命中率
    # 【不做 HE/BE 分类】末 2% 文本判结局本质不可靠：词表放宽则八成判 HE，
    # 收紧则八成判不出——那测的是词表宽度，不是结局分布。
    # 改报**标记命中率**：这是可验证的事实，不是推断。一篇可同时命中多类。
    tail = text[-max(2000, len(text) // 50):]
    ending = {
        "圆满向标记": int(any(w in tail for w in HE)),
        "离散向标记": int(any(w in tail for w in BE)),
        "开放向标记": int(any(w in tail for w in OPEN)),
        "无标记": int(not any(w in tail for w in HE + BE + OPEN)),
    }

    return {
        "dia": dia_ratio, "p25": p25, "p50": p50, "p75": p75, "long": long_ratio,
        "adv": adv.most_common(60), "idiom": idiom.most_common(80),
        "mood": mood.most_common(10), "ending": ending, "cn": cn_total,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    import sys
    sys.path.insert(0, str(LIB / "_脚本"))
    # 【按独立作品挖，不按文件挖】——这一条是版权论证的地基。
    # 本卷「跨 ≥N 篇即类型套话」的豁免依据，前提是那 N 篇是 N 部**不同的作品**。
    # 而语料里同一部作品常有多份存档（5,668 文件 ≈ 2,897 部作品），
    # 按文件挖会让**单篇作品的独特句子**靠自己的副本凑够篇数、冒充成套话。
    # 实测漏过：某部的露骨章节标题因有 6 份存档而进了榜。
    from aggregate_corpus import R as KEEP, _norm_t
    _best = {}
    for _r in KEEP:
        _t = _norm_t(_r.get("文件名") or _r["path"].rsplit("/", 1)[-1])
        if _t not in _best or _r["字数"] > _best[_t]["字数"]:
            _best[_t] = _r
    files = [r["path"] for r in _best.values()]
    if getattr(a, "limit", None):
        files = files[: a.limit]
    print(f"待挖掘 {len(files):,} 篇，{a.workers} 进程")

    dia, p25, p50, p75, long_r = [], [], [], [], []
    adv, idiom, mood, ending = Counter(), Counter(), Counter(), Counter()
    ok = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(one, f) for f in files]
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            if not r:
                continue
            ok += 1
            dia.append(r["dia"]); p25.append(r["p25"]); p50.append(r["p50"])
            p75.append(r["p75"]); long_r.append(r["long"])
            adv.update(dict(r["adv"])); idiom.update(dict(r["idiom"]))
            mood.update(dict(r["mood"]))
            for _k, _v in r["ending"].items():
                ending[_k] += _v
            if i % 500 == 0:
                print(f"  {i:,}/{len(files):,}")

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else 0

    def q(xs, f):
        xs = sorted(xs)
        return xs[int(len(xs) * f)] if xs else 0

    OUT.write_text(json.dumps({
        "docs": ok,
        "dia_p25": q(dia, .25), "dia_p50": med(dia), "dia_p75": q(dia, .75),
        "para_p25": med(p25), "para_p50": med(p50), "para_p75": med(p75),
        "long_para_ratio": med(long_r),
        "adv": adv.most_common(200), "idiom": idiom.most_common(250),
        "mood": mood.most_common(12),
        "ending_marks": {k: v / max(ok, 1) for k, v in ending.items()},
        "ending_n": dict(ending),
    }, ensure_ascii=False), encoding="utf-8")

    print(f"\n有效 {ok:,} 篇 → {OUT}")
    print(f"  对白占比 中位数 {med(dia)*100:.1f}%（P25 {q(dia,.25)*100:.1f}% / P75 {q(dia,.75)*100:.1f}%）")
    print(f"  段落长度 中位数 {med(p50)} 字")
    print(f"  高频副词 {[w for w,_ in adv.most_common(12)]}")
    print(f"  高频四字 {[w for w,_ in idiom.most_common(12)]}")
    print("  结尾标记命中率 " + "｜".join(f"{k} {v/max(ok,1)*100:.0f}%" for k, v in ending.items()))


if __name__ == "__main__":
    main()
