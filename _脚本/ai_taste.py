#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量「AI 味」。

check_compliance 的 J 项查的是**规约里写下的**七条铁律，
那是本库自己定的标准。这个模块查的是另一件事：
外部研究总结出的、机器写作在统计上区别于人的那些痕迹。

两者的关系：J 项是「我们说好不这么写」，本模块是「人不这么写」。
后者更难改，因为它不在词表上，在分布上。

指标分三层：
  分布层  句长的方差与节奏（burstiness）、段落长度的均匀度、标点的丰富度
  句法层  可枚举的句式模式（不是X是Y、三项列举、破折号插入、自问自答）
  词汇层  词表命中（另见 AI_WORDS）

用法：python3 ai_taste.py <文件或目录>…      逐文件报告
      python3 ai_taste.py --lib               扫全库并给排行
      python3 ai_taste.py --narrative <文件>   按小说标准查（比百科严）
      cat 稿子.txt | python3 ai_taste.py -     查管道里的文本

查自己的稿子用 --narrative。百科体与叙事体的阈值不同：
说明文里破折号、术语引号天然多，小说里不该有。
"""

import re
import statistics
import sys
from pathlib import Path

from paths import LIB
from quote_strip import strip_quotes

# ── 词汇层 ──
# 高置信度：出现即可疑，人类写作里罕见（尤其在同一篇里反复出现）
AI_WORDS_HIGH = [   # 例外:M 词表本身不是病
    "值得注意的是", "值得一提的是", "需要指出的是", "不难看出", "不难发现",
    "综上所述", "总而言之", "一言以蔽之", "由此可见", "众所周知",
    "在当今", "在这个[^，。\n]{0,6}(时代|背景|意义|层面|领域|语境|环境)", "随着.{0,6}的不断", "扮演着.{0,6}角色",
    "至关重要", "不可或缺", "息息相关", "举足轻重",
    "让我们", "我们不妨", "拭目以待", "未来可期",
    "赋能", "抓手", "闭环", "颗粒度", "底层逻辑", "顶层设计", "生态位",
    "深入探讨", "全方位", "多维度", "立体化",
]
# 低置信度：单独出现无罪，密度高才是问题
AI_WORDS_LOW = [    # 例外:M 词表本身不是病
    "此外", "同时", "另外", "然而", "因此", "从而", "进而",
    "实际上", "事实上", "换句话说", "某种程度上", "某种意义上",
    "可能", "或许", "似乎", "往往", "通常", "一般来说",
    "显著", "极大", "有效", "充分", "进一步", "更好地",
]

# ── 句法层 ──
PATTERNS = {
    "不是X是Y": re.compile(r"不是[^。！？\n]{1,24}?[，,]\s*(?:而是|是)"),
    "并非X而是Y": re.compile(r"并非[^。！？\n]{1,24}?[，,]\s*而是"),
    "与其说": re.compile(r"与其说[^。！？\n]{1,20}[，,]不如说"),
    "破折号插入": re.compile(r"——[^\n]{4,}"),
    "自问自答": re.compile(r"[？?]\s*(?:答案是|答案很简单|原因在于|因为)"),
    "特殊用法引号": re.compile(r"[「\"“][^」\"”\n]{1,6}[」\"”](?=[的地得是])"),
}


# ── 中文特有:欧化句法 ──   # 例外:M 词表与正则本身不是病
# 来源:调研得出的根本诊断——中文 AI 味 ≈ 骨架是英文的中文句子;
# 以及余光中《中文的常态与变态》(1987) 的反西化清单。
# 这一层比词表更耐用:词表会过期(delve 被点名后频率就掉了),句法模式不会。

# 一、把思考写成物理动作。中文 AI 味的头号症状,也是本项目自己的重灾区。
# 这些词按字符串匹配，物理本义的合成词会被误伤：
# 落地扇/落地窗/落地灯、对齐格式（排版）、承接工程。
# 所以「落地」加负向前瞻排掉常见家具，其余靠人工判断——
# 词表宁可略宽，但**不能逼人把「落地扇」改成「电风扇」**（真发生过）。
METAPHOR_RE = re.compile(
    r"接住|接得住|击穿|锋利|收口|撑不住|不崩|不爆|打穿|收紧|扛住|拉齐|咬合|承接"
    r"|对齐(?!格式)"
    # 「落地」的物理本义在小说里很常见：脚落地、雨落地、飞机落地。
    # 黑话义（方案落地）后面通常直接收句，物理义后面跟方位或时间。
    # 第三次为这个词收窄了——前两次是家具（落地扇/窗），这次是身体动作
    # （「走法落地全在脚掌前半」）。宁可放过黑话，不可误伤描写。
    r"|落地(?!扇|窗|灯|镜|钟|式|全|在|时|后|声|一)")

# 二、形容词先下判断再上冒号。删掉形容词、只留后半句事实即可。
ADJ_COLON = re.compile(r"(问题|结论|逻辑|原因|答案|道理|区别|差别|判据|做法)"
                       r"(很|非常|极其)?(直接|明确|清晰|简单|明显|清楚|干净)[：:]")

CN_WESTERN = {
    # 万能弱动词:作出决定 → 决定
    "弱动词": re.compile(r"(作出|进行|加以|给予|予以|开展)[一二三]?[个种项次]?[^，。！？\n]{1,6}"),
    # 「的」字连用
    "的字连用": re.compile(r"的[^，。！？\n]{1,6}的[^，。！？\n]{1,6}的"),
    # 伪术语后缀:具有很高的知名度 → 很有名
    "性度化": re.compile(r"(具有|有)[^，。\n]{0,6}(性|度|化)(很|较|颇)?[高强好]"),
    # 介词滥用:关于王教授的为人 → 王教授的为人
    "介词开头": re.compile(r"^(关于|对于|作为|基于)[^，。\n]{2,}", re.M),
    # 之一
    # 「三分之一」「四分之一」是分数，不是「名著之一」那个滥用
    "之一": re.compile(r"(?<![一二三四五六七八九十百千万两几半分])之一"),
    # 时间从句西化:当你把稿子写好之后 → 你稿子一写好
    "当X之后": re.compile(r"当[^，。！？\n]{2,20}(之后|的时候|以后)"),
}

# ── 叙事文特有:小说 AI 模板 ──
# 前者是被反复点名的套话,后者是「情绪被点名」——
# 规则是情绪词出现即应改写成动作或物件。
FICTION_SLOP = ["不由得一愣", "眉头紧锁", "深吸一口气", "嘴角微微上扬", "心中一凛",
                "瞳孔骤缩", "后背一凉", "握紧了拳头", "沉默了片刻", "目光复杂",
                "语气不容置疑", "空气仿佛凝固", "时间仿佛静止", "心跳漏了一拍"]
EMOTION_NAMED = re.compile(r"[他她](感到|觉得|心中|心里|心头)(一阵|一丝|一股|微微|猛地)")


def zh(s):
    return len(re.findall(r"[一-鿿]", s))


EXEMPT = re.compile(r"<!-- ?例外[:：]")


def strip_noise(t):
    # 带 `<!-- 例外:规则号 理由 -->` 的行整行跳过，与 check_compliance 同一套机制。
    # 库里有两处故意写坏的教学样本（易混淆词辨析的题眼句、反AI味指南病 5 的
    # 三连示例），它们是内容本身，不是病；没有这一层，那两篇会永远标红，
    # 而长期挂着的红灯等于没有红灯。
    if "例外" in t:
        t = "\n".join(l for l in t.split("\n") if not EXEMPT.search(l))

    """去掉代码块、表格、引文、链接、YAML 头，只留散文。"""
    t = re.sub(r"```[\s\S]*?```", "", t)
    # 只剥**文件开头**的 YAML front matter。
    # 原来写的是 flags=re.M 的 ^---，于是正文里任意两条 --- 分隔线之间的
    # 整段都被当成 front matter 删掉——一篇有 6 条分隔线的文档，3 个整段
    # 不参与统计，测出来的密度全是低估。**锚点错一个字符，整套数据失真。**
    t = re.sub(r"\A---\n[\s\S]*?\n---\n", "", t)
    t = "\n".join(l for l in t.split("\n") if not l.lstrip().startswith("|"))
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"`[^`\n]+`", "", t)
    # 剥引号内的成句引文，与 check_compliance 的 J 项 prep() 同一行为。
    # 理由：引文不是本库写的字，不该参与本库文风的统计。
    # 红线 1.3 禁止为文风指标改动引文，那么也不该让引文替本库背指标——
    # 反过来也一样：引文会稀释分母，把本库自己的密度盖下去。
    # 01-总论/05 的「不是X是Y」5 处全在社群原话与波伏瓦名句里，就是这个情况。
    t = strip_quotes(t)
    return t


def sentences(t):
    parts = re.split(r"(?<=[。！？!?])\s*", t)
    return [zh(p) for p in parts if zh(p) >= 2]


def measure(text):
    t = strip_noise(text)
    cn = zh(t) or 1
    sl = sentences(t)
    paras = [zh(p) for p in re.split(r"\n{2,}", t) if zh(p) >= 10]

    m = {"汉字": cn, "句数": len(sl)}

    # 分布层：句长的均值、标准差、变异系数。
    # 人类写作的句长分布是「爆发式」的：短句与长句交替，CV 通常 > 0.5；
    # 模型倾向把每句都写成中等长度，CV 会明显偏低。
    # 节奏类指标要求足够的样本。门槛原是 8 句，太低——
    # 10-藏书索引 那种整篇是数据表的文档，散文只剩几句标题说明，
    # 量出来的「句长 CV 0.41」说的是那几句话，不是这篇文档的写法。
    # 25 句以下不给节奏判据，只查词表与句式（那两类由渲染种子决定，改得动）。
    if len(sl) >= 25:
        mu = statistics.mean(sl)
        sd = statistics.pstdev(sl)
        m["句长均值"] = round(mu, 1)
        m["句长CV"] = round(sd / mu, 2) if mu else 0
        # 极短句（≤6 汉字）的比例。人写东西会甩短句，模型很少
        m["短句占比"] = round(sum(1 for x in sl if x <= 6) / len(sl), 2)
        m["长句占比"] = round(sum(1 for x in sl if x >= 45) / len(sl), 2)
    if len(paras) >= 4:
        pmu = statistics.mean(paras)
        m["段长CV"] = round(statistics.pstdev(paras) / pmu, 2) if pmu else 0

    # 标点丰富度：模型少用逗号以外的标点，尤其是分号、括号、问号
    for name, ch in (("分号", "；;"), ("括号", "（(")):
        m[f"{name}/千字"] = round(len(re.findall(f"[{ch}]", t)) / cn * 1000, 1)

    # 句法层
    for k, p in PATTERNS.items():
        m[f"{k}/千字"] = round(len(p.findall(t)) / cn * 1000, 2)

    # 词汇层
    hi = sum(len(re.findall(w, t)) for w in AI_WORDS_HIGH)
    lo = sum(len(re.findall(w, t)) for w in AI_WORDS_LOW)
    m["高危词"] = hi
    m["高危词/千字"] = round(hi / cn * 1000, 2)
    m["低危词/千字"] = round(lo / cn * 1000, 1)
    # 与 check_compliance 的 J 项同一算法：剥掉引文/代码块之后再算，
    # 否则分母偏小、密度虚高（同一篇会出现「J 绿而这里红」的自相矛盾）
    m["加粗/千字"] = round(len(re.findall(r"\*\*[^*\n]{1,40}\*\*", t)) / cn * 1000, 1)
    # 整句被加粗 = 段末金句。加粗密度超标的真身多半是这个：
    # 不是术语强调，是把整句话捧成警句。摘掉星号即可，一个字都不用删。
    m["整句加粗/千字"] = round(
        len(re.findall(r"\*\*[^*\n]{12,}[。！？…]\*\*", t)) / cn * 1000, 2)
    # 中文欧化句法与叙事套话
    m["物理隐喻/千字"] = round(len(METAPHOR_RE.findall(t)) / cn * 1000, 2)
    m["形容词冒号/千字"] = round(len(ADJ_COLON.findall(t)) / cn * 1000, 2)
    for k, pat in CN_WESTERN.items():
        m[f"{k}/千字"] = round(len(pat.findall(t)) / cn * 1000, 2)
    m["小说套话/千字"] = round(sum(t.count(w) for w in FICTION_SLOP) / cn * 1000, 2)
    m["情绪点名/千字"] = round(len(EMOTION_NAMED.findall(t)) / cn * 1000, 2)
    return m


# ── 阈值：全部来自语料实测，不是拍脑袋 ──
# 做法：从 5,668 篇真人小说里随机抽 100 篇，各取 2 万字切片，算每个指标的分布。
# 复算：python3 ai_taste.py --baseline
#
#                     真人 P10 / 中位 / P90
#   句长CV              0.55 / 0.67 / 0.84
#   短句占比            0.04 / 0.09 / 0.17
#   不是X是Y/千字       0.00 / 0.00 / 0.18   ← 真人**中位数为 0**
#   破折号插入/千字     0.00 / 0.06 / 1.10
#   特殊用法引号/千字   0.00 / 0.12 / 0.31
#   高危词/千字         0.00 / 0.06 / 0.18
#
# 头两轮我拍过一版阈值，被实测推翻了两条：短句占比定成 ≥0.12（真人中位数才 0.09），
# 「三项列举」当成 AI 特征（真人中位数 7.16，比库里高五倍，中文本来就爱顿号列举）。
# 那条指标已删。**凡是靠直觉定的文风阈值，先去语料里量一遍。**
#
# 百科正文与小说是两种文体：说明文的破折号、术语引号天然多于叙事。
# 所以分两套——叙事类（示例段、开场白、卡片）按真人 P90 收，说明类放宽到 2 倍，
# 唯独「不是X是Y」两套一样严：它不是文体差异，是纯粹的机器腔。
# 破折号**不进硬阈值**，只作参考项打印。
# 理由有两层：①外部研究实测 70 万词已出版文学，破折号密度 4.76/千词，
#   《哈克贝利·费恩》10.13，GPT-4.1 10.62——GPT 只相当于马克·吐温；
#   检测器自己的告警线是 20/千词，通行的「破折号禁令」比人类写作还严。
# ②本库实测：42 张卡按 1.10 的阈值全部触线，逐条看下去，
#   命中的是「——他每年这个时候都不吃枣。谁问他他都说酸。」这类正当插入语。
# 判据误报就改判据，不能拿错判据去逼人改好文字。
# 真正的信号是节奏均匀度（句长 CV），那一项照查。
REFERENCE_ONLY = {"破折号插入/千字"}

HUMAN_P90 = {"不是X是Y/千字": 0.18, "破折号插入/千字": 1.10,
             "特殊用法引号/千字": 0.31, "高危词/千字": 0.18,
             # 欧化句法层，同样是 100 篇真人小说实测的 P90
             "物理隐喻/千字": 0.24, "弱动词/千字": 0.26, "的字连用/千字": 0.43,
             "介词开头/千字": 0.06, "之一/千字": 0.07, "当X之后/千字": 0.12,
             "小说套话/千字": 0.12}

# 真人 P99 都是 0 的三项，零容忍。
# 「问题很直接：」这种「形容词下判断＋冒号」在 100 篇真人小说里一次都没出现过；
# 「他感到一阵……」的情绪点名同理。这不是文体差异，是机器腔的指纹。
HUMAN_ZERO = {"形容词冒号/千字": 0.0, "情绪点名/千字": 0.06, "性度化/千字": 0.06}

# 「整句加粗」单独定，不走语料基线——小说是纯文本，本来就不用 markdown 加粗，
# 拿它的 0 当阈值不诚实。这条的依据是规约铁律 2 本身：
# 加粗只标术语首现与真正的例外。整句话被加粗，两样都不是，它是段末金句。
# 实测：加粗密度超标的篇目，超的几乎全是这一种；摘掉星号即可，一个字不用删。
SENTENCE_BOLD_MAX = 1.0

def limits(narrative=False, prose_cn=None):
    k = 1.0 if narrative else 2.0
    lim = {"句长CV": (0.55, "min"), "短句占比": (0.04, "min"),
           "加粗/千字": (10.0, "max")}
    # 散文太少时不查加粗密度：分母小，密度虚高。
    # 10-藏书索引 那种数据表，散文只有几句，而 `**5,668 篇**` 这类数字强调
    # 是正当的短标签型加粗，硬按 10/千字 查它是拿错尺子。
    # 整句加粗（把整句话捧成警句）不受此限，那个才是真病，照查。
    if prose_cn is not None and prose_cn < 1000:
        lim.pop("加粗/千字")
    for key, v in HUMAN_P90.items():
        if key in REFERENCE_ONLY:
            continue
        # 「特殊用法引号」只在叙事文里算 AI 腔。百科给术语加引号（「妻主」「np洁癖」）
        # 是体例要求，本库有 350 条术语，按小说标准查它必然满屏误报。
        if key == "特殊用法引号/千字" and not narrative:
            continue
        lim[key] = (round(v * (1.0 if key == "不是X是Y/千字" else k), 2), "max")
    for key, v in HUMAN_ZERO.items():
        lim[key] = (v, "max")
    lim["整句加粗/千字"] = (SENTENCE_BOLD_MAX, "max")
    return lim


def verdict(m, narrative=False):
    bad = []
    for k, (lim, kind) in limits(narrative, m.get("汉字")).items():
        v = m.get(k)
        if v is None:
            continue
        if kind == "min" and v < lim:
            bad.append(f"{k} {v}<{lim}")
        if kind == "max" and v > lim:
            bad.append(f"{k} {v}>{lim}")
    return bad



def card_texts(lib):
    """把卡里的**叙事字段**抽出来单独查。

    开场白与备选开场是纯小说，读者一打开卡就看到它；
    而 description 是设定表、system_prompt 是指令，两者都不按叙事标准算。
    所以这里只取 first_mes / alternate_greetings / mes_example。
    """
    import json
    for d in ("角色卡", "情景卡", "角色卡-长文本"):
        for f in sorted((lib / "11-模板包" / d).glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8")).get("data", {})
            except Exception:
                continue
            t = "\n\n".join([data.get("first_mes", ""), data.get("mes_example", "")]
                             + list(data.get("alternate_greetings") or []))
            if zh(t) >= 300:
                yield f, t


def main():
    narr = "--narrative" in sys.argv
    if "--cards" in sys.argv:
        rows = [(f, measure(t), verdict(measure(t), True)) for f, t in card_texts(LIB)]
        bad = [(f, b) for f, _, b in rows if b]
        for f, b in bad[:25]:
            print(f"  {f.parent.name}/{f.stem[:28]:30} {'；'.join(b)}")
        print(f"\n卡的叙事字段 {len(rows)} 份，{len(bad)} 份触线（按小说标准）")
        return 1 if bad else 0
    if "-" in sys.argv:                      # 管道输入
        t = sys.stdin.read()
        m = measure(t)
        bad = verdict(m, narr)
        print(f"{m['汉字']} 汉字，{m.get('句数', 0)} 句")
        for k in ("句长CV", "短句占比", "不是X是Y/千字", "物理隐喻/千字",
                  "整句加粗/千字", "情绪点名/千字", "小说套话/千字"):
            if k in m:
                print(f"  {k:16} {m[k]}")
        print("\n" + ("✗ " + "；".join(bad) if bad else "✓ 未触线"))
        return 1 if bad else 0
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    # 仓库元文件不按内容卷标准查：它们要引用词表与坏例子来说明规则本身
    # （CHANGELOG 里写「把思考写成物理动作（落地／对齐／接住）」，
    #  那是在讲这个病，不是在犯它）。与 check_compliance 的豁免名单保持一致。
    META = {"CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "CLAUDE.md"}
    if "--lib" in sys.argv:
        files = [p for p in LIB.rglob("*.md")
                 if "_整理后" not in str(p) and ".github" not in p.parts
                 and p.name not in META
                 and zh(p.read_text(encoding="utf-8", errors="ignore")) > 800]
    else:
        files = []
        for a in args:
            p = Path(a)
            # 收 .txt：创作者的稿子多是 txt，只收 .md 会打印「0 篇，0 篇触线」
            # 并返回 0——看着全绿，其实一个字都没查。这是唯一一个会
            # 主动制造虚假安全感的坑。
            files += (sorted(x for x in p.rglob("*")
                             if x.suffix.lower() in (".md", ".txt"))
                      if p.is_dir() else [p])
    if not files:
        print("没有可查的文件（只认 .md 与 .txt）")
        return 1
    rows = []
    for f in files:
        m = measure(f.read_text(encoding="utf-8", errors="ignore"))
        rows.append((f, m, verdict(m, narr)))
    rows.sort(key=lambda r: -len(r[2]))
    for f, m, bad in rows[:40]:
        rel = f.relative_to(LIB) if str(f).startswith(str(LIB)) else f
        flag = "✗ " + "；".join(bad) if bad else "✓"
        print(f"{str(rel)[:44]:46} CV{m.get('句长CV','-'):>5} 短{m.get('短句占比','-'):>5} "
              f"高危{m['高危词']:>3} {flag}")
    n_bad = sum(1 for _, _, b in rows if b)
    print(f"\n{len(rows)} 篇，{n_bad} 篇触线")
    if rows:
        cvs = [m["句长CV"] for _, m, _ in rows if "句长CV" in m]
        if cvs:
            print(f"全库句长 CV 中位数 {statistics.median(cvs):.2f}"
                  f"（越高越像人写的；<0.55 视为过齐）")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
