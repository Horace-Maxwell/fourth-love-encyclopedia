#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量正文挖掘器 —— 从 5,600 篇 / 5.70 亿字正文里提取可复用的创作元素。

与 probe_v2.py 的分工：
  probe_v2  只读每篇开头，抽「作者自述」（文案/标签/排雷）——元数据层
  mine_text 通读全文，抽「作者写出来的东西」——素材层

挖八类元素（全部落成可直接查用的库）：
  1. 人名库        按性别推断分组，附出现频次与共现称谓
  2. 称谓实例库    妻主/正君/夫郎等在真实语境中的用法句
  3. 权力语言库    命令句 / 所有格 / 顺从动词 / 敬称 的真实句式
  4. 设定元素库    信息素气味、宗门、职务爵位、地点、道具
  5. 开场句型库    每篇第一句的类型学
  6. 章节标题库    命名模式与高频词
  7. 场景动词库    高频动作动词（按权力方向分）
  8. 名场面触发    高频场景标志词

设计约束：
  · 只抽**模式与短句**，不抽成段原文（见 00-编纂规约/03-版权与内容红线）
  · 单条实例上限 60 字，且必须来自 ≥3 篇不同作品才收录（去个人风格化）
  · 多进程，每进程只回传计数器，父进程合并——避免 5.7 亿字进内存

用法：
    python3 mine_text.py [--workers N] [--limit N] [--sample-chars N]
"""

import os
import re
import json
import argparse
from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from paths import LIB

JSONL = LIB / "10-藏书索引" / "_语料库.jsonl"
OUT = LIB / "10-藏书索引" / "_正文挖掘.json"

SAMPLE = 600_000          # 每篇采样上限（够覆盖绝大多数中短篇全文）


# ══ 编码 ══════════════════════════════════════════════════════════════
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


# ══ 词表 ══════════════════════════════════════════════════════════════
SAY_VERBS = "说道问答笑喊叫应嘲讽低声轻声冷声沉声怒斥叹"
# 对白归属句：「XX说」「XX笑道」——中文小说提取人名最可靠的锚点。
# 必须锚在句首或引号之后，否则会把「她低声」「轻笑了一」这类碎片当成人名。
NAME_BY_SAY = re.compile(
    r"(?:^|[。！？…\n」』”\"])\s*([一-鿿]{2,4})"
    r"(?:淡淡|冷冷|轻轻|缓缓|忽然|这才)?(?:地)?"
    r"(?:开口|出声)?(?:笑|冷|沉|低|轻|柔|怒|嗤)?"
    r"[" + SAY_VERBS + r"](?:道|了|着)?[:：，,]", re.M)
NAME_BY_ACT = re.compile(
    r"(?:^|[。！？…\n])\s*([一-鿿]{2,4})"
    r"(?:抬眼|抬头|低头|转身|皱眉|挑眉|勾唇|伸手|起身|坐下|停住|顿了|眯了|扯了)", re.M)

# 人名里绝不会出现的字（虚词、方位、程度、感官）——命中即丢弃
NAME_BAD_CHARS = set("的了着地得是不也就还很再又都会能可要没有这那什么怎知声"
                     "一二三四五六七八九十两几多少半每各另同其此以之于与和跟"
                     "上下左右前后里外中间边旁对向从到在为被把将令使让叫做")

# 明确不是人名的高频词（称谓、代词、常见词）
NOT_NAME = set("""
他她它我你您咱们大家自己对方这个那个什么怎么为什么可是但是然后所以因为如果虽然
妻主正君侧君侍君夫郎夫侍男妻父君父后小爹主人大人殿下陛下将军元帅公主王爷太女
先生小姐老板总裁师尊师父师傅老师同学朋友女人男人孩子少年少女老人
心里眼里手里嘴里脸上身上心中脑海时候时间地方东西事情问题办法
一个两个几个所有很多没有还是就是不是可以应该必须开始结束继续
声音眼睛手指头发身体动作表情语气目光笑容
如今此时此刻忽然突然立刻马上终于已经曾经从来
""".split())

TITLES = ["妻主", "正君", "侧君", "侍君", "贵君", "君后", "夫郎", "夫侍", "男妻",
          "父君", "父后", "小爹", "叔爹", "主人", "大人", "殿下", "陛下", "娘子",
          "郎君", "公子", "少爷", "姐姐", "哥哥", "弟弟", "先生", "小姐", "老板",
          "师尊", "师父", "将军", "元帅", "王爷", "王君", "太女", "帝卿", "奴家"]

# 权力语言的句式锚点
CMD_PAT = re.compile(
    r"[「『“\"]([^」』”\"]{2,26}?)[」』”\"]"
    r"(?=[^\n]{0,12}(?:命令|吩咐|下令|开口|冷声|沉声|淡淡|不容置疑|不容拒绝))")
CMD_DIRECT = re.compile(
    r"[「『“\"]((?:过来|跪下|抬头|看着我|张嘴|松手|闭嘴|住手|别动|站住|坐下|说话|回答我|给我|不许|不准|听话|乖)"
    r"[^」』”\"]{0,22})[」』”\"]")
POSSESS = re.compile(r"(我的(?:人|男人|狗|东西|夫郎|正君|所有物|所有品)|"
                     r"(?:是|成了)我的|属于我|归我(?:所有|管))")
SUBMIT_VERB = re.compile(r"(?:他|男主|[一-鿿]{2,3})"
                         r"(跪|叩首|低头|垂眸|垂首|颤抖|发抖|喘|哽|服从|听话|顺从|讨好|示弱|求饶|认错|请罪)")

# 设定元素
# 信息素气味：只取紧贴「味/香」前面的那个词，且必须在「信息素」附近 30 字内。
# 早先版本用惰性匹配会把整个前置从句都吞进来（如「埋在颜先生的冷松」）。
PHEROMONE = re.compile(r"([一-鿿]{2,5})(?:味道|味儿|味|香气|香)(?=[，。、\s」』的])")
PHERO_CTX = re.compile(r"信息素|腺体|易感期|发情期")
# 宗门：「门」「楼」太通用（关上门/肛门/青楼），只保留真正的门派后缀。
SECT = re.compile(r"([一-鿿]{2,4})(宗|派|山庄|仙门|剑阁|书院|学宫|道观)(?=[，。、\s」』的之])")
SECT_BAD = ("反派", "流派", "政府", "正宗", "学派", "党派", "气派", "指派", "委派",
            "分派", "帮派", "各派", "两派", "一派", "这派", "那派", "老派", "新派",
            "做派", "门派", "正派", "顽固", "婉约", "豪放", "保守", "激进", "温和",
            "乐观", "悲观", "祖宗", "列祖", "光宗")
RANK = re.compile(r"([一-鿿]{2,3})(将军|元帅|王爷|王君|亲王|郡主|太女|帝卿|尚书|丞相|统领|少将|上将|司令)")
# 爵位前缀不能是动词/敬辞——「还请王爷」「谢谢将军」不是爵位名
RANK_BAD = ("还请", "谢谢", "多谢", "拜见", "参见", "见过", "知道", "想到", "不知",
            "告诉", "回禀", "禀报", "这位", "那位", "一位", "身为", "作为", "成为")
PROP = re.compile(r"(?:一[把柄枚支根条件]|那[把柄枚支根条件])\s*([一-鿿]{2,6})")


# ── 素材速取用的四类专名（13 卷「设定元素库」原来只有宗门/封号/器物）──
# 写到一半最常卡住的是「这个地方叫什么」「这个家族叫什么」「他是什么官」。
# 「口」「界」「国」这类单字后缀会抓到「咬了一口」「这个世界」，一律不收。
# 只留自带地名感的后缀，且前缀必须是 2–3 个非虚词汉字。
PLACE = re.compile(r"(?<![一-鿿])([一-鿿]{2,3})(城|镇|郡|州|域|星|峰|谷|渊|"
                   r"宫|殿|苑|楼|阁|轩|斋|坊|巷|寨|港)"
                   r"(?=[，。、；：\s」』的之上下里外])")
PLACE_BAD = re.compile(r"[了的是在有和与也就还很再又都会能可要没这那什么怎"
                       r"一二三四五六七八九十出回官进入到去过来上下开关]")
# 「家」单字会抓到「回家」「在家」，去掉；「族」也要求成词。
CLAN = re.compile(r"(?<![一-鿿])([一-鿿]{1,2})(氏|府|门阀|世家|一族)(?=[，。、；\s」』的之])")
OFFICE = re.compile(r"([一-鿿]{2,3})?(尚书|侍郎|御史|太傅|太师|丞相|将军|都督|刺史|太守|县令|"
                    r"郎中|主簿|长史|司马|校尉|统领|指挥使|千户|百户|提督|巡抚|总兵|"
                    r"教习|执事|长老|堂主|舵主|管事|掌柜|账房|护院)")
JOB = re.compile(r"(?<![一-鿿])(大夫|郎中|镖师|捕快|绣娘|织工|铁匠|木匠|船工|车夫|说书|"
                 r"戏子|画师|琴师|舞姬|厨子|药童|书童|侍卫|暗卫|死士|谋士|幕僚|账房|"
                 r"总裁|董事|秘书|助理|律师|医生|护士|教授|讲师|设计师|程序员|记者|编剧|"
                 r"经纪人|制片|导演|演员|模特|调酒师|花艺师|兽医|飞行员|舰长|机甲师|"
                 r"炼丹师|炼器师|阵法师|符修|剑修|体修|药修)(?![一-鿿])")

CH_TITLE = re.compile(
    r"^\s*(?:☆[、,]\s*)?(?:第\s*[0-9一二三四五六七八九十百千零两]+\s*[章节回]"
    r"|Chapter\s*\d+|\d{1,4}[、.．])\s*[:：]?\s*(.{2,26}?)\s*$", re.M)
CH_BAD = re.compile(r"^第?\s*[0-9一二三四五六七八九十百千零两]+\s*[章节回]?$")

# 名场面标志词
SCENE_MARK = {
    "初次交锋": ["第一次见", "初次见面", "打量着", "上下扫了"],
    "下马威": ["下马威", "立规矩", "给你个教训", "谁给你的胆子"],
    "当众护短": ["当着所有人", "众目睽睽", "护在身后", "谁准你动"],
    "破防时刻": ["崩溃", "红了眼", "终于哭", "失控地", "再也忍不住"],
    "跪与不跪": ["跪下", "跪了下来", "屈膝", "单膝"],
    "称谓改变": ["改口", "叫我", "别这么叫", "换个称呼"],
    "第一次触碰": ["第一次碰", "指尖相触", "手腕被握", "被扣住"],
    "掉马": ["身份暴露", "被识破", "认出了", "原来你就是"],
    "示弱": ["示弱", "软下来", "服了软", "低声下气"],
    "权力交还": ["交给你", "你来决定", "听你的", "我不管了"],
}


def mine_one(path_str: str):
    p = Path(path_str)
    try:
        text = decode_bytes(p.read_bytes())
    except OSError:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")[:SAMPLE]
    if len(text) < 3000:
        return None

    res = {}

    # ① 人名（按对白归属 + 动作起句）
    names = Counter()
    TAIL = "笑冷沉低轻柔怒嗤淡缓忽这才开出"

    def clean_n(n):
        while len(n) > 2 and n[-1] in TAIL:
            n = n[:-1]
        return n

    def ok_name(n):
        if n in NOT_NAME or len(n) < 2:
            return False
        if any(c in NAME_BAD_CHARS for c in n):
            return False
        if any(t in n for t in TITLES):
            return False
        return True

    for pat in (NAME_BY_SAY, NAME_BY_ACT):
        for m in pat.finditer(text):
            n = clean_n(m.group(1))
            if ok_name(n):
                names[n] += 1
    # 只保留本篇出现 ≥8 次的（主要角色），并推断性别
    main = {}
    for n, c in names.items():
        if c < 8:
            continue
        # 性别推断三信号，按可靠性加权：
        #  ① 紧跟名字的称谓（最可靠）：「裴叙白公子」「姜昱妻主」
        #  ② 同句内名字之后出现的第三人称代词（较可靠）
        #  ③ 名字与「他/她」在 12 字内共现（兜底）
        seg = text[:250000]
        esc = re.escape(n)
        mt = sum(len(re.findall(esc + t, seg)) for t in
                 ("公子", "少爷", "郎君", "君", "先生", "少将", "将军"))
        ft = sum(len(re.findall(esc + t, seg)) for t in
                 ("妻主", "小姐", "娘子", "殿下", "女士", "夫人"))
        # 同句回指：名字在句首，同一句内后续出现的代词几乎必然指它
        ana = re.findall(r"(?:^|[。！？…\n])" + esc + r"([^。！？…\n]{0,40})", seg, re.M)
        joined = "".join(ana)
        f2 = joined.count("她") * 4
        m2 = len(re.findall(r"他(?!们)", joined)) * 4
        near = "".join(re.findall(r".{0,12}" + esc + r".{0,12}", seg))
        f3 = near.count("她")
        m3 = len(re.findall(r"他(?!们)", near))
        fs, ms = ft * 6 + f2 + f3, mt * 6 + m2 + m3
        if fs > ms * 1.6 and fs >= 8:
            g = "女"
        elif ms > fs * 1.6 and ms >= 8:
            g = "男"
        else:
            g = "?"
        main[n] = (c, g)
    res["names"] = main

    # ② 称谓实例（每种称谓最多取 2 句）
    tex = defaultdict(list)
    for t in TITLES:
        if t not in text:
            continue
        for m in re.finditer(r"[「『“\"]([^」』”\"\n]{0,28}" + t + r"[^」』”\"\n]{0,28})[」』”\"]", text):
            s = m.group(1).strip()
            if 4 <= len(s) <= 40:
                tex[t].append(s)
            if len(tex[t]) >= 2:
                break
    res["title_ex"] = dict(tex)

    # ③ 权力语言
    cmds = [m.group(1).strip() for m in CMD_PAT.finditer(text)][:6]
    cmds += [m.group(1).strip() for m in CMD_DIRECT.finditer(text)][:8]
    res["cmd"] = [c for c in cmds if 2 <= len(c) <= 26]
    res["possess"] = Counter(m.group(1) for m in POSSESS.finditer(text))
    res["submit"] = Counter(m.group(1) for m in SUBMIT_VERB.finditer(text))

    # ④ 设定元素
    # 只在提到信息素/腺体的窗口里找气味词，避免抓到普通的「香味」
    phero = Counter()
    for cm in PHERO_CTX.finditer(text):
        win = text[max(0, cm.start() - 40): cm.end() + 60]
        for m in PHEROMONE.finditer(win):
            w = m.group(1)
            if not any(c in NAME_BAD_CHARS for c in w) and len(w) >= 2:
                phero[w] += 1
    res["phero"] = phero
    sect = Counter(m.group(1) + m.group(2) for m in SECT.finditer(text)
                   if not any(b in m.group(1) + m.group(2) for b in SECT_BAD))
    # 真门派名在全书反复出现；只出现 1~2 次的基本是「XX一派」这类偶发搭配
    res["sect"] = Counter({k: v for k, v in sect.items() if v >= 3})
    res["rank"] = Counter(m.group(1) + m.group(2) for m in RANK.finditer(text)
                          if m.group(1) not in RANK_BAD)
    res["prop"] = Counter(m.group(1) for m in PROP.finditer(text))
    res["place"] = Counter(m.group(1) + m.group(2) for m in PLACE.finditer(text)
                           if not PLACE_BAD.search(m.group(1)))
    res["clan"] = Counter(m.group(1) + m.group(2) for m in CLAN.finditer(text)
                          if not PLACE_BAD.search(m.group(1)))
    res["office"] = Counter((m.group(1) or "") + m.group(2) for m in OFFICE.finditer(text))
    res["job"] = Counter(m.group(1) for m in JOB.finditer(text))

    # ⑤ 开场句（跳过站头广告区）
    body = re.sub(r"^[\s\S]{0,3000}?(?:第\s*[一1]\s*章|☆[、,]|正文)", "", text, count=1)
    first = ""
    for line in body.split("\n"):
        s = line.strip()
        if len(s) >= 12 and not re.search(r"http|www|群|微信|QQ|作者|文案|标签|整理|下载", s):
            first = s[:60]
            break
    res["opening"] = first

    # ⑥ 章节标题
    res["ch_title"] = [t for t in (m.group(1).strip() for m in CH_TITLE.finditer(text))
                       if t and not CH_BAD.match(t) and len(t) >= 2][:40]

    # ⑦ 名场面标志
    res["scene"] = {k: sum(text.count(w) for w in ws)
                    for k, ws in SCENE_MARK.items()}
    return res


# ══ 合并 ══════════════════════════════════════════════════════════════
def merge(results):
    agg = {
        "names_f": Counter(), "names_m": Counter(), "names_x": Counter(),
        "name_docs": defaultdict(set),
        "title_ex": defaultdict(Counter),
        "cmd": Counter(), "possess": Counter(), "submit": Counter(),
        "phero": Counter(), "sect": Counter(), "rank": Counter(), "prop": Counter(),
        "place": Counter(), "clan": Counter(), "office": Counter(), "job": Counter(),
        "opening": [], "ch_title": Counter(), "scene": Counter(),
        "docs": 0,
    }
    for i, r in enumerate(results):
        if not r:
            continue
        agg["docs"] += 1
        for n, (c, g) in r["names"].items():
            agg[{"女": "names_f", "男": "names_m"}.get(g, "names_x")][n] += 1
            agg["name_docs"][n].add(i)
        for t, exs in r["title_ex"].items():
            for e in exs:
                agg["title_ex"][t][e] += 1
        for c in r["cmd"]:
            agg["cmd"][c] += 1
        for k in ("possess", "submit", "phero", "sect", "rank", "prop",
                  "place", "clan", "office", "job"):
            agg[k].update(r[k])
        if r["opening"]:
            agg["opening"].append(r["opening"])
        agg["ch_title"].update(r["ch_title"])
        agg["scene"].update(r["scene"])
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 2))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    # 只挖入库的本类型作品
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
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
    if a.limit:
        files = files[:a.limit]
    print(f"待挖掘 {len(files):,} 篇，{a.workers} 进程\n")

    results, done = [], 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(mine_one, f) for f in files]
        for fut in as_completed(futs):
            done += 1
            try:
                results.append(fut.result())
            except Exception:
                results.append(None)
            if done % 500 == 0:
                print(f"  {done:,}/{len(files):,}")

    agg = merge(results)
    print(f"\n有效 {agg['docs']:,} 篇")

    # 序列化（Counter → 排序后的 list，避免 JSON 太大）
    def top(c, n=400):
        return c.most_common(n) if isinstance(c, Counter) else c

    payload = {
        "docs": agg["docs"],
        "names_f": top(agg["names_f"], 800),
        "names_m": top(agg["names_m"], 800),
        "names_x": top(agg["names_x"], 300),
        "title_ex": {t: c.most_common(12) for t, c in agg["title_ex"].items()},
        "cmd": top(agg["cmd"], 500),
        "possess": top(agg["possess"], 60),
        "submit": top(agg["submit"], 60),
        "phero": top(agg["phero"], 300),
        "sect": top(agg["sect"], 400),
        "rank": top(agg["rank"], 300),
        "place": top(agg["place"], 400),
        "clan": top(agg["clan"], 200),
        "office": top(agg["office"], 200),
        "job": top(agg["job"], 200),
        "prop": top(agg["prop"], 400),
        "opening": agg["opening"][:3000],
        "ch_title": top(agg["ch_title"], 600),
        "scene": dict(agg["scene"]),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"→ {OUT}")
    print(f"  女名 {len(agg['names_f'])}｜男名 {len(agg['names_m'])}｜"
          f"命令句 {len(agg['cmd'])}｜信息素气味 {len(agg['phero'])}｜"
          f"宗门 {len(agg['sect'])}｜开场句 {len(agg['opening'])}")


if __name__ == "__main__":
    main()
