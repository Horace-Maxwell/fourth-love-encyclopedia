#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 00-编纂规约 的硬规矩变成**机器可查的检查项**。

为什么需要它：
  质量审计查出 48 条问题，其中最严重的一类是「规约自己写了、但库里没做到」——
  五处高风险内容缺安全框架（规约 3.2 的字面要求）、66 个结构单元缺「写崩的三种方式」
  （写作硬规矩第 4 条）、四篇卷首分级低于卷内实际条目（「就高不就低」）。
  这些都不是「想不到」，是**没人逐条核过**。核一次要一小时，写成脚本就零成本。

检查项（每一条都对应规约里的一句明文，不是我另立的标准）：
  A 三行头     每篇卷首要有 分级 + 预警 + 亚型
  B 分级就高    卷首分级不得低于卷内任一条目
  C 安全框架    带 ⚠️主奴/非自愿/囚禁/重口 预警的文件必须点名 SSC/RACK/PRICK
                并写出虚构与现实的区分声明；E 级文件同样强制（含全员成年声明）
  D 写崩三条    结构性条目要带「写崩的三种方式」，且标题字符串统一
  E 来源声明    每篇要有来源声明的载体（警告级；逐断言四档标注仍属人工规范，
                见 00-编纂规约/01。此前 docstring 声称 E 已自动化，不实——已改）
  F 链接        相对链接不得失效
  G 双链        写法要与实际标题一致；悬空占比超 25% 报警
  H 引用配额    本地精读笔记标注出处的成句引用单篇 ≤1（红线 1.3；该目录不入库，
                fresh clone 上不存在即跳过）
  I 成句引用    ≥25 字引号内容要么有出处、要么可辨识为社群言论/本库自撰
  J 去AI化      铁律 2 加粗 / 3 元评论 / 4 第二人称 / 5 破折号 / 6「不是X是Y」/
                7 自我加冕 / 8 虚词（00-编纂规约/05；6 与 8 为本轮新增实现）
  K 卡片        角色卡/情景卡/世界书 JSON 的字段、体量、安全框架、元评论、rating
  L 桥段栏目    14 卷条目六栏目齐全、双向写法两个方向都覆盖
  N 分布层     句长节奏、模式化句式、高危词的密度对齐真人语料实测
  M 渲染种子    _脚本/*.py 的中文字符串不得携带元评论/自我加冕/虚词——
                机器生成卷的文风病根在种子层，产物层查不住（重跑就回灌）

警告通道（⚠ 前缀，不计入返回码）：贴线预警（达到上限 90%）、表格密度下限、
价值断言、祈使指导、「显然」、E 来源声明。

行内豁免：在该行加 `<!-- 例外:规则号 理由 -->`（如 `<!-- 例外:J6 题眼 -->`），
该行对该规则不计。全库豁免会在报告末尾列出，防滥用。

用法：python3 check_compliance.py          全部检查
      python3 check_compliance.py -q       只报不合规项
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

from paths import LIB
from card_format import importable
from quote_strip import strip_quotes

QUIET = "-q" in sys.argv

# 不参与 A–D 内容检查的目录。逐项理由：
#   00-编纂规约   规约把坏写法当反例列出，按成稿标准查必然误报
#                 （J 项单独收窄：只豁免 04/05 两篇，其余照查）
#   10-藏书索引   机器生成 + gitignore（本机私有）；其文风由 M 项在种子层把关。
#                 注意「10-藏书索引-公开」是不同的 parts 字符串，不被本集合命中，
#                 属有意设计——它进仓库，要按内容卷查
#   11-模板包     提示词层，规矩不同（铁律 §文档≠提示词），由 K 项按提示词标准查
#   12-导出       编译产物，查源不查产物
#   13-语料挖掘   机器渲染卷，A–D 三行头体例不适用；文风仍被 J 全量扫（它进仓库）
#   _脚本         代码；其中文字符串由 M 项查
SKIP_DIRS = {"00-编纂规约", "10-藏书索引", "11-模板包", "12-导出", "13-语料挖掘", "_脚本",
             ".github",      # issue/PR 模板与 CI，不是百科条目
             "09-拆解卡"}    # 精读笔记已下架（.gitignore），本机才有，不按入库标准查
RATING = ["G", "T", "M", "E"]
RISK_WARN = ("⚠️主奴", "⚠️非自愿", "⚠️囚禁", "⚠️重口", "⚠️调教", "⚠️训诫")
SAFETY_WORDS = ("SSC", "RACK", "PRICK")

FAIL = defaultdict(list)
WARN = defaultdict(list)

# ── 行内豁免 ──
EXEMPT_RE = re.compile(r"<!-- ?例外[:：]([A-Za-z0-9]+)([^>]*?)-->")


def strip_exempt(text, rid):
    """去掉带 <!-- 例外:rid --> 标记的行——该行对该规则不计。"""
    if "例外" not in text:
        return text
    return "\n".join(l for l in text.split("\n")
                     if not any(m.group(1) == rid for m in EXEMPT_RE.finditer(l)))


# ── J/K/M 共用的文风词表 ──
# 「窗口」必须排除逗号/顿号/冒号/表格分隔符，否则会跨小句误伤
# （「本卷做法：先给主流最通行的一派」不是元评论，是内容陈述）。
_WIN = r"[^\n。！？，,：:、｜|]{0,12}?"
_META_PRED = (r"(?:最(?!后|终|新|初)|唯一|价值|值钱|意义|存在的理由|之所以|恰恰|正是|"
              r"必读|核心|精华|重要|实用|必须给出|要回答|要解决|想说|不反对|分工|暴露)")
# 「全书/全文/全篇」指**被分析的作品**，永远不进这张表（精读笔记「全书最精确的一笔」是内容）。
_SELF_FULL = r"(?:本卷|本篇|本节|本表|本条|本卡|这一节|这一卷|这一格|这张表|这张卡|全卷)"
# 精读笔记里的「本篇」指被拆的那本小说（09 卷标准指代法），对该卷放行「本篇」。
#
# 09 卷（逐部作品的精读笔记）已下架：本地保留、.gitignore 排除、不入库
# （理由见 00-编纂规约/03-版权与内容红线 1.4）。这套豁免留着不删，
# 因为笔记在本机还要继续记、还要继续被这个检查器扫；fresh clone 上
# 那个目录不存在，下面的 is_card 恒为 False，这几条正则自然不参与判定。
_SELF_CARD = r"(?:本卷|本节|本表|本条|本卡|这一节|这一卷|这一格|这张表|这张卡|全卷)"
META_FULL = re.compile(_SELF_FULL + _WIN + _META_PRED)
META_CARD = re.compile(_SELF_CARD + _WIN + _META_PRED)
META2_FULL = re.compile(r"为什么" + _SELF_FULL + r"[^\n。！？]{0,16}?(?:写在|放在|收在|另开|单列|存在)")
META2_CARD = re.compile(r"为什么" + _SELF_CARD + r"[^\n。！？]{0,16}?(?:写在|放在|收在|另开|单列|存在)")
P2ND = re.compile(r"(?:你可以|你会|你该|你需要|你要|你得|想写|如果你|建议你|不妨|问自己)"
                  r"(?![^\n]{0,6}[」』”])")
# 编者对**本库自己产物**的褒贬。判据来自萌娘百科的编写规范：
# 「编辑本人不可以对所编辑的条目做出个人评价和褒贬，而应该以客观第三者的视角」。
# 比铁律 7 宽——7 只禁「本库最／唯一」的字面，这条禁的是整类自评。
#
# 三条不算，都写在这里免得下一轮被误清：
#   ① 「这条最好的一句」——同一条内部在几个变体里指出该用哪个，是工具书的
#      用法指点，像菜谱说「这一步最关键」。所以 SELF 里不含「这条」。
#   ② 精读笔记的「本篇／全书 + 最」指被拆的那部小说，是对研究对象的分析。
#   ③ 「必读附件」这类合规指引不是推荐语。
_SELF_LIB = r"(全库|本库|本卷|本篇|本表|本节|这张表|这一卷|这一节|这一格|这一条|本条)"
SELF_PRAISE = re.compile(
    # 窗口排除括号与竖线：表格里「就是这一格：威胁她等于最有效的胁迫手段」
    # 说的是被拆作品里那个角色的功能，「这一格」指表格分类，不是本库自评。
    _SELF_LIB + r"[^\n。！？，,：:（）()｜|]{0,14}(维护得最好|最好的一|最完整|最扎实|最有价值|"
    r"最实用|做得最好|写得最好|质量最高|最值得|最该看|必读)"
    r"|(?:是|算)" + _SELF_LIB + r"[^\n。！？，,：:（）()｜|]{0,10}(最|唯一|之冠|之最)")
CROWN = re.compile(r"(?:全库|全卷|本卷|全谱|本库)(?:目前|里)?(?:最(?!后|终|新|初)|唯一)")
# 「事实上的婚姻」是法律术语不是虚词；「不可以说/谁都可以说」是内容不是口头禅。
# 「可以说」还有一个更常见的实义用法：**能够说出口**——
#   「她可以说『你跟我去』，什么都能说，就是不能说谢」
#   「他可以说『我不喜欢你去见他』，但不能说『你敢去试试』」
# 口头禅那一路后面永远跟着「是」或逗号（「可以说是一个转折点」「可以说，这就是全部」），
# 实义那一路后面跟的是宾语、引号或「不」。用后视断开，比列一串白名单可靠。
FILLER = re.compile(r"(?:(?:实际上|事实上)(?!的)|换句话说|(?<![不都也])可以说(?=是|[，,])|"
                    r"值得注意|值得一提|毫无疑问|不难发现)")
NOTX = re.compile(r"不是[^。！？\n]{1,24}?[，,]\s*(?:而是|是)")
VALUE_CLAIM = re.compile(r"(?:最有分量|最值钱|理论含量最高|理论密度最高|含金量|"
                         r"投入产出比最高|尤其锋利|极其经济)")
IMPER = re.compile(r"^(?:记住|注意|别忘|试着|数一数)[，,：:]", re.M)


def content_files():
    for p in sorted(LIB.rglob("*.md")):
        if any(d in p.parts for d in SKIP_DIRS) or "_整理后" in str(p):
            continue
        if p.name in ("README.md", "INDEX.md", "LICENSE.md", "速查入口.md",
                      "CLAUDE.md", "CONTRIBUTING.md", "SECURITY.md",
                      "CHANGELOG.md") or "_模板" in str(p):
            continue  # 模板是待填骨架，不按成稿标准查；CLAUDE.md 是提示词层（铁律 §文档≠提示词）
        yield p


def rating_of(text_head):
    """从卷首取分级。库内合法写法有四种，都要认：
       `E`  ／  `G–M`（区间）  ／  | **分级** | **M** |（精读笔记的表格头）
       ／  `分级见各条`（逐条自带分级的卷）"""
    if re.search(r"分级见各条|各条另标|逐条标注", text_head):
        return 99, True, True          # 合法的「不在卷首下判断」写法
    m = re.findall(r"[`*]([GTME])[`*]|`([GTME])[–\-—]([GTME])`", text_head)
    flat = [x for tup in m for x in tup if x]
    best = max((RATING.index(x) for x in flat), default=-1)
    return best, ("⚠️" in text_head or "预警" in text_head), ("亚型" in text_head or "｜" in text_head)


def main():
    files = list(content_files())

    for p in files:
        t = p.read_text(encoding="utf-8", errors="ignore")
        head = "\n".join(t.split("\n")[:14])
        rel = str(p.relative_to(LIB))

        # ── A 三行头 ──
        r, has_warn, has_sub = rating_of(head)
        if r < 0:
            FAIL["A 缺卷首分级"].append(rel)

        # ── B 分级就高不就低 ──
        body_rates = [RATING.index(x) for x in re.findall(r"`([GTME])`", t[len(head):])]
        if 0 <= r < 90 and body_rates and max(body_rates) > r:
            # 卷首已显式声明「按更高级对待」的算合规
            if not re.search(r"就高不就低|整卷按 *`?[GTME]`? *对待", head):
                FAIL["B 卷首分级低于卷内条目"].append(
                    f"{rel}（卷首 {RATING[r]}，卷内最高 {RATING[max(body_rates)]}）")

        # ── C 安全框架 ──
        # 预警必须出现在分级行上才算本文件承载该内容。
        # 否则术语卷「解释⚠️主奴这个标签是什么意思」也会被判为高风险文件。
        rating_lines = [l for l in t.split("\n")
                        if re.search(r"`[GTME]`", l) and "⚠️" in l]
        if any(w in l for l in rating_lines for w in RISK_WARN):
            miss = [w for w in SAFETY_WORDS if w not in t]
            has_distinction = bool(re.search(r"幻想装置|虚构与现实|不是现实(实践)?指南", t))
            if miss:
                FAIL["C 高风险文件未点名安全框架"].append(f"{rel}（缺 {'/'.join(miss)}）")
            elif not has_distinction:
                FAIL["C 高风险文件缺虚构/现实区分声明"].append(rel)

        # ── C 扩展：E 级文件必须附安全框架 ──
        # 条目级分级行出现 `E`、或卷首声明「分级上限 `E`」的文件，
        # 强制 SSC/RACK/PRICK + 虚构/现实区分 + 全员成年声明（14 卷 E 级族政策的机器化）。
        if re.search(r"^`E` *｜", t, re.M) or re.search(r"分级上限 *`E`", head):
            missE = [w for w in SAFETY_WORDS if w not in t]
            okd = re.search(r"幻想装置|虚构与现实|不是现实(实践)?指南", t)
            oka = "成年" in t
            if missE or not okd or not oka:
                need = "/".join(missE) or ("虚构区分" if not okd else "成年声明")
                FAIL["C E级文件未附安全框架"].append(f"{rel}（缺 {need}）")

        # ── D 写崩三条：标题字符串统一 ──
        for l in t.split("\n"):
            if not re.match(r"^#{2,6} ", l):
                continue
            for variant in ("写崩三种", "最容易写崩", "写崩的3种"):
                if variant in l:
                    FAIL["D 写崩标题写法不统一"].append(f"{rel}｜{l.strip()[:44]}")

        # ── E 来源声明（窄化，警告级）──
        # 「逐断言四档标注」不可机判；可机判的是「有没有来源声明的载体」。
        # 精读笔记的载体是信息框作者行；速查/总表类聚合成品豁免。
        if not any(k in p.name for k in ("速查", "总表", "总览")):
            if not (re.search(r"来源[：:]", t) or "**来源约定**" in t
                    or re.search(r"\| *\*\*作者\*\* *\|", t)):
                WARN["E 缺来源声明（窄化判据）"].append(rel)

    # ── F 链接 ──
    for p in LIB.rglob("*.md"):
        if "_整理后" in str(p):
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"\[([^\]\n|`]{1,80})\]\((?!https?:|mailto:)([^)#\n|`]{2,120})\)", t):
            try:
                if not (p.parent / m.group(2)).resolve().exists():
                    FAIL["F 相对链接失效"].append(f"{p.relative_to(LIB)} → {m.group(2)}")
            except OSError:
                pass

    # ── K 卡片（11-模板包/角色卡 与 情景卡）──
    # 检查器原来只扫 .md，卡的合规全靠人工把关，结果漏过 5 张带 ⚠️ 预警
    # 却没有 SSC/RACK/PRICK 的卡。卡也是对外交付物，纳入检查。
    import json as _json
    CARD_RISK = ("⚠️主奴", "⚠️非自愿", "⚠️训诫", "⚠️囚禁", "⚠️重口", "⚠️调教")
    CARD_REQ = ("name", "description", "personality", "scenario", "mes_example", "first_mes")
    CARD_META = re.compile(r"(?:这张卡|本卡)" + _WIN + _META_PRED + r"|(?:这张卡|本卡)(?:的全部价值|必读)")
    # 两类卡的体量要求不同：角色卡要立一个人（长），情景卡只架一个时刻（短）。
    # 用同一个 600 字门槛会逼着情景卡注水，那正是它要避免的东西。
    # 长文本卡的 description 是英文，汉字门槛不适用，改按字符数
    CARD_DIRS = [("角色卡", 600), ("情景卡", 200), ("角色卡-长文本", 0)]
    for sub, min_cn in CARD_DIRS:
        d0 = LIB / "11-模板包" / sub
        if not d0.exists():
            continue
        for cf in sorted(d0.glob("*.json")):
            raw = cf.read_text(encoding="utf-8")
            try:
                obj = _json.loads(raw)
            except Exception as e:
                FAIL[f"K {sub} JSON 结构异常"].append(f"{cf.name}：{e}")
                continue
            # 能不能被 SillyTavern 导入，是卡的第一条判据。
            # 474 张卡曾因外层多包了一层 {"project","card"} 而全部导不进去，
            # 且那次交付验证只查了「JSON 可解析」——可解析不等于可导入。
            ok, why = importable(obj)
            if not ok:
                FAIL[f"K {sub}无法导入 SillyTavern"].append(f"{cf.stem}：{why}")
                continue
            data = obj.get("data") or obj
            # 长文本卡把设定统一放 description（参考卡与现行 ST 卡的通行做法）：
            # personality/scenario 分列会让同一信息两处维护，正是本库最擅长的失败模式。
            req = ("name", "description", "first_mes") if not min_cn else CARD_REQ
            missing = [k for k in req if not data.get(k)]
            if missing:
                FAIL[f"K {sub}字段缺失"].append(f"{cf.stem}：缺 {'/'.join(missing)}")
            desc = data.get("description", "")
            if min_cn and len(re.findall(r"[一-鿿]", desc)) < min_cn:
                FAIL[f"K {sub} description 过短（<{min_cn} 汉字）"].append(cf.stem)
            if not min_cn and len(desc) < 3000:
                FAIL[f"K {sub} description 过短（<3000 字符）"].append(cf.stem)
            # 规约 3.2：带高风险预警的卡必须有完整安全框架
            if any(r in raw for r in CARD_RISK) and not all(
                    k in raw for k in ("SSC", "RACK", "PRICK")):
                FAIL[f"K 高风险{sub}缺 SSC/RACK/PRICK"].append(cf.stem)
            # 提示词里谈论卡本身：白占上下文，还会把模型带进元叙述
            if CARD_META.search(raw):
                FAIL[f"K {sub}提示词含元评论"].append(cf.stem)
            # E 级条目的卡按元层级降级标 M——开局卡不含描写，rating 不得为 E
            if re.search(r'"rating"\s*:\s*"E"', raw) or re.search(r"rating[=:] ?[\"']E", raw):
                FAIL[f"K {sub} rating 不得为 E（开局卡按元层级降级标 M）"].append(cf.stem)
            # 扮演方向必须在开头声明
            head = "\n".join(data.get("description", "").split("\n")[:4])
            if not re.search(r"(扮演方向|AI 扮|我扮)", head):
                FAIL[f"K {sub}未声明扮演方向"].append(cf.stem)

    # ── K 扩展：世界书（11-模板包/世界书/*.json）──
    # 与 L 项旧 glob 病同构的遗漏：CARD_DIRS 只列了两类卡，五个世界书包无人查。
    # 世界书是提示词层：不查加粗/第二人称（铁律 §文档≠提示词），查结构、元评论、安全框架。
    WB_META = re.compile(r"(?:这张卡|本卡|本包|这条世界书|本表|本节)" + _WIN + _META_PRED)
    # 两处世界书：11-模板包/世界书/ 与 11-模板包/去AI味/。
    # 而且两种格式并存——书房导出的 entries 是数组，SillyTavern 的是字典。
    # 早先只 for e in entries，遇到字典会拿到键名字符串再 .get() 抛异常。
    wbfiles = []
    for sub in ("世界书", "去AI味"):
        d = LIB / "11-模板包" / sub
        if d.exists():
            wbfiles += sorted(f for f in d.glob("*.json"))
    if wbfiles:
        for wf in wbfiles:
            raw = wf.read_text(encoding="utf-8")
            try:
                obj = _json.loads(raw)
            except Exception as e:
                FAIL["K 世界书 JSON 结构异常"].append(f"{wf.name}：{e}")
                continue
            entries = obj.get("entries") or []
            if isinstance(entries, dict):      # ST 格式：{"0": {...}, "1": {...}}
                entries = list(entries.values())
            if not entries:
                FAIL["K 世界书 entries 为空"].append(wf.stem)
                continue
            empty = [e.get("name", "?") for e in entries if not (e.get("content") or "").strip()]
            if empty:
                FAIL["K 世界书条目 content 为空"].append(f"{wf.stem}：{'/'.join(empty[:4])}")
            blob = "\n".join(e.get("content", "") for e in entries)
            for mm in WB_META.finditer(blob):
                FAIL["K 世界书含元评论"].append(f"{wf.stem}「{mm.group(0)[:20]}」")
            if any(r in raw for r in CARD_RISK) and not all(k in raw for k in SAFETY_WORDS):
                FAIL["K 高风险世界书缺 SSC/RACK/PRICK"].append(wf.stem)

    # ── L 桥段库（14 卷）──
    # 本库同时服务四爱女与四爱男，「双向写法」不是装饰而是硬要求：
    # 同一场戏从哪一边写，选的细节完全不同（她视角写玄关的灯，他视角写第三次端下来）。
    # 靠人工盯 90 条必然漏，所以做成检查项。
    # 例外：明写「不是一场戏」的判据条不需要这一格。
    VIG_SLOTS = ["节拍链", "可用细节", "变体轴", "双向写法", "写崩的三种方式", "可串接"]
    vdir = LIB / "14-桥段库"
    if vdir.exists():
        for vf in sorted(vdir.glob("[0-9]*.md")):   # 曾写作 0[1-9]-*，11 之后的卷全部漏检
            body = vf.read_text(encoding="utf-8")
            for blk in re.split(r"^## ", body, flags=re.M)[1:]:
                title = blk.split("\n", 1)[0].strip()
                if " · " not in title:          # 非条目小节
                    continue
                # 判据条与装置条豁免。认标记，不认措辞——
                # 曾经只认「不是一场戏」这句话，2026-08 那轮全库改写把它改成了
                # 「这条不算具体场景」，检查器当场报缺栏目。一句正文当机器判据用，
                # 迟早会被谁顺手改掉。措辞留作老条目的兜底，新条目一律写标记。
                if "<!-- gb-nonscene -->" in blk or re.search(r"不是一场戏|不独立成场", blk):
                    continue
                miss = [s for s in VIG_SLOTS if f"#### {s}" not in blk]
                if miss:
                    FAIL["L 桥段条目缺栏目"].append(
                        f"{vf.name}｜{title}｜缺 {'/'.join(miss)}")
                # 双向写法必须两栏都填，只填一边等于没填
                m = re.search(r"#### 双向写法\n\n((?:\|[^\n]*\n)+)", blk)
                if m and ("四爱女" not in m.group(1) or "四爱男" not in m.group(1)):
                    FAIL["L 双向写法未覆盖两个方向"].append(f"{vf.name}｜{title}")

    # ── J 去 AI 化铁律（00-编纂规约/05）──
    # 阈值来自与萌娘百科「ABO设定」条目的实测对照，不是审美偏好。
    # 预处理次序（每条规则各自过一遍，因为行内豁免是按规则号计的）：
    #   删该规则的豁免行 → 删代码块（```内是模板语法示例）→
    #   删引号内容（引文与社群原话**必须一字不动**，红线 1.3；
    #     曾有一次为满足「第二人称 0」而裁剪引文，那是把优先级搞反了）→
    #   删反引号（语料实例与代码）→（散文口径再删表格行：
    #     格内破折号是分隔符不是追加解释；加粗则相反——表格已提供结构，
    #     格内加粗是重复，所以加粗规则要管表格）
    for p3 in sorted(LIB.rglob("*.md")):
        # 规约文件本身要把坏写法当反例列出来，按成稿标准查它没有意义；
        # CLAUDE.md 是给模型的提示词层，祈使与第二人称是它的正确语域（铁律 §文档≠提示词）
        if (any(d in p3.parts for d in ("10-藏书索引", "_整理后"))
                or ".github" in p3.parts
                or p3.name in ("04-质量审计报告.md", "05-去AI化写作铁律.md", "CLAUDE.md",
                               "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md")):
            continue
        t3_raw = p3.read_text(encoding="utf-8", errors="ignore")

        def prep(rid, prose=False):
            t_ = strip_exempt(t3_raw, rid)
            t_ = re.sub(r"```[\s\S]*?```", "", t_)
            t_ = strip_quotes(t_)
            t_ = re.sub(r"`[^`\n]+`", "", t_)
            if prose:
                t_ = "\n".join(l for l in t_.split("\n") if not l.lstrip().startswith("|"))
            return t_

        base = prep("J")
        cn3 = len(re.findall(r"[一-鿿]", base))
        if cn3 < 500:
            continue          # LICENSE.md 与模板骨架靠这道门槛豁免——扩写它们时要留意
        rel3 = str(p3.relative_to(LIB))
        # 该目录不入库，fresh clone 上没有文件会命中这一支（见 _SELF_CARD 处的说明）
        is_card = "09-拆解卡" in p3.parts
        META = META_CARD if is_card else META_FULL
        META2 = META2_CARD if is_card else META2_FULL

        # 铁律 2：加粗 ≤10/千字（表格内加粗也计）
        v_bold = len(re.findall(r"\*\*[^*\n]{1,40}\*\*", prep("J2"))) / cn3 * 1000
        if v_bold > 10.0:
            FAIL["J 加粗过密（上限 10.0处/千字）"].append(f"{rel3}：{v_bold:.1f}")
        elif v_bold >= 9.0:
            WARN["贴线预警：加粗已达上限 90%"].append(f"{rel3}：{v_bold:.1f}/10.0")

        # 铁律 5：破折号追加解释 ≤1/千字（只算散文）
        v_dash = len(re.findall(r"——[^\n]{6,}", prep("J5", prose=True))) / cn3 * 1000
        if v_dash > 1.0:
            FAIL["J 破折号追加解释过多（上限 1.0处/千字）"].append(f"{rel3}：{v_dash:.1f}")
        elif v_dash >= 0.90:
            WARN["贴线预警：破折号已达上限 90%"].append(f"{rel3}：{v_dash:.2f}/1.0")

        # 铁律 3：元评论 0
        t_j3 = prep("J3")
        hits = [m.group(0) for m in META.finditer(t_j3)] + \
               [m.group(0) for m in META2.finditer(t_j3)]
        if hits:
            FAIL["J 元评论（应为 0）"].append(f"{rel3}：{len(hits)} 处（如「{hits[0][:20]}」）")

        # 铁律 4：第二人称指导 0
        hits = [m.group(0) for m in P2ND.finditer(prep("J4"))]
        if hits:
            FAIL["J 第二人称指导（应为 0）"].append(f"{rel3}：{len(hits)} 处（如「{hits[0][:14]}」）")

        # 编者对本库自己产物的褒贬（萌娘百科编写规范）
        t_sp = prep("J7")
        if is_card:      # 09 卷（本地精读笔记）的「本篇」指被拆小说，整条跳过
            t_sp = ""
        hits = [m.group(0) for m in SELF_PRAISE.finditer(t_sp)]
        if hits:
            FAIL["J 编者自评（应为 0）"].append(
                f"{rel3}：{len(hits)} 处（如「{hits[0][:18]}」）")

        # 铁律 7：自我加冕最高级 0
        hits = [m.group(0) for m in CROWN.finditer(prep("J7"))]
        if hits:
            FAIL["J 自我加冕最高级（应为 0）"].append(f"{rel3}：{len(hits)} 处（如「{hits[0][:14]}」）")

        # 铁律 6：「不是X，是Y」每篇 ≤3（散文口径；题眼句可行内豁免）
        n6 = len(NOTX.findall(prep("J6", prose=True)))
        if n6 > 3:
            FAIL["J 「不是X，是Y」超限（每篇 ≤3）"].append(f"{rel3}：{n6} 处")

        # 铁律 8（扩展）：虚词 0（删掉信息不减的那批）
        hits = [m.group(0) for m in FILLER.finditer(prep("J8", prose=True))]
        if hits:
            FAIL["J 虚词（应为 0）"].append(f"{rel3}：{len(hits)} 处（如「{hits[0]}」）")

        # 警告级文风观察项
        n = len(re.findall(r"显然", prep("J8", prose=True)))
        if n:
            WARN["「显然」（观察项）"].append(f"{rel3}：{n} 处")
        hits = [m.group(0) for m in VALUE_CLAIM.finditer(prep("J7", prose=True))]
        if hits:
            WARN["价值断言（人工过目）"].append(f"{rel3}：{len(hits)} 处（如「{hits[0]}」）")
        n = len(IMPER.findall(prep("J4", prose=True)))
        if n:
            WARN["行首祈使指导（人工过目）"].append(f"{rel3}：{n} 处")

    # ── N 分布层：与真人写作的统计差距（ai_taste.py）──
    # J 项查的是「规约说好不这么写」，N 项查的是「人不这么写」。
    # 阈值全部来自 5,668 篇真人小说的实测分布，不是拍脑袋定的
    # （复算：python3 ai_taste.py --baseline）。
    # 2026-08 起为 FAIL 级。此前挂警告是因为存量 121 篇里有 100+ 篇触线，
    # 一次性升级会让 pre-commit 全红；改完之后（全库 0 触线）才升。
    # 行内豁免 `<!-- 例外:规则号 理由 -->` 仍然生效，报告末尾会列出全库豁免。
    from ai_taste import measure as _m, verdict as _v, card_texts as _ct
    # 卡的开场白与备选开场是纯叙事，读者一开卡就看到，按小说标准查（narrative=True）。
    # description 是设定表、system_prompt 是指令，都不算叙事，不在此列。
    # 有的卡，记账就是那个人的性格——「男主-美强惨」的设定是他把每一份善意
    # 都折算成债，开场白里的「折算／记账／结算」是人物在做的事，不是编者的行话。
    # 判据分不出这个差别，人分得出：卡自己在 creator_notes 里声明即豁免。
    for cf, ct in _ct(LIB):
        import json as _j
        _notes = _j.loads(cf.read_text(encoding="utf-8")).get("data", {}).get("creator_notes", "")
        if "行话豁免" in _notes:
            continue
        bad = _v(_m(ct), True)
        if bad:
            FAIL["N 卡的开场白：与真人写作的统计差距"].append(
                f"{cf.parent.name}/{cf.stem}：{'；'.join(bad)}")
    for p5 in content_files():
        t5 = p5.read_text(encoding="utf-8", errors="ignore")
        if len(re.findall(r"[一-鿿]", t5)) < 800:
            continue
        bad = _v(_m(t5))
        if bad:
            FAIL["N 分布层：与真人写作的统计差距"].append(
                f"{p5.relative_to(LIB)}：{'；'.join(bad)}")

    # ── 表格密度下限（铁律 1「结构化信息进表格」的可测代理，警告级）──
    # 对照值：萌娘百科 8.6 表格行/千字，本库达标卷 5.6+。门槛 3.0 只点名真正的散文病。
    for p4 in content_files():
        t4 = p4.read_text(encoding="utf-8", errors="ignore")
        cn4 = len(re.findall(r"[一-鿿]", t4))
        if cn4 < 2000:
            continue
        rows = len(re.findall(r"^ *\|", t4, re.M))
        d = rows / cn4 * 1000
        if d < 3.0:
            WARN["表格密度过低（<3.0 行/千字，铁律 1 代理）"].append(
                f"{p4.relative_to(LIB)}：{d:.1f}")

    # ── M 渲染种子（_脚本/*.py 的中文字符串字面量）──
    # 病根在种子：AI 腔写在渲染模板里，产物层怎么查都会在下次 mine 时回灌。
    # 用 ast 取字符串常量（注释天然不进；f-string 的常量段也覆盖）。
    # 豁免：本文件（词表即正则）、scene_cards_data/（提示词层，产物由 K 项查）、
    #       行尾注 `# 例外:M`（如 _HINT 清洗正则——那是药不是病）。
    import ast
    SEED_RULES = [("M 渲染种子：元评论", META_FULL),
                  ("M 渲染种子：自我加冕", CROWN),
                  ("M 渲染种子：虚词", FILLER)]
    for pf in sorted((LIB / "_脚本").glob("*.py")):
        if pf.name == "check_compliance.py":
            continue
        src = pf.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            FAIL["M 脚本语法错误"].append(f"{pf.name}：{e}")
            continue
        lines = src.split("\n")
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if not re.search(r"[一-鿿]", node.value):
                continue
            # 豁免标记可能写在常量所在行，也可能写在它所属的列表/字典的开头行
            # （词表就是这种情况：标记在 `AI_WORDS_HIGH = [` 那一行，词在下面几行）。
            # 所以向上找 6 行。
            lo = max(0, node.lineno - 6)
            near = "\n".join(lines[lo:node.lineno])
            if "例外:M" in near or "例外：M" in near:
                continue
            for label, pat in SEED_RULES:
                for mm in pat.finditer(node.value):
                    FAIL[label].append(f"{pf.name}:{node.lineno}「{mm.group(0)[:22]}」")

    # ── I 版权：全库成句引用扫描（红线 1.2「不搬运表达」）──
    # 判定思路：引号内 ≥25 字视为「成句」。三类要区分开，混在一起会淹没真问题：
    #   ① 作品原文  —— 受红线 1.3 约束（单篇一句 + 注明出处）
    #   ② 社群言论  —— 论坛发言、tag 说明、平台规则。是**研究对象**不是文学作品，
    #                  为记录与评述而引用是正当的，但同样要能看出它来自社群
    #   ③ 本库自撰  —— 示范句、分析句、口诀。带「示范／自写／AI 版」等标记
    SENT = re.compile(r"[「『“]([^」』”\n]{25,})[」』”]")
    CITED = re.compile(r"——《|——\s*\S{2,20}第\s*\d+\s*[章节]|（《[^》]+》第|"
                       r"原文|出处|引自|作者写|书中|官方原文")
    # 真正的风险是**作品的叙事文字**，不是社群发言也不是本库自撰的示范。
    # 所以判据不看「有没有标记」（那会淹没在上百条误报里），而看「这句像不像叙事散文」：
    #   叙事散文 = 有第三人称主语 + 具体动作/知觉动词，且不含元话语词汇。
    #   社群发言与本库自撰几乎必然带元话语（tag／读者／示范／技法／结构……）。
    NARRATIVE = re.compile(r"(?:他|她)[^\n]{0,12}"
                           r"(?:看|望|笑|说|走|站|坐|跪|抬|低|伸|抱|握|推|拉|转身|皱眉|开口|"
                           r"闭上|松开|放下|拿起|靠近|退后|attempt)")
    META_TALK = re.compile(r"tag|TAG|标签|读者|网友|评论|豆瓣|贴吧|微博|晋江|长佩|海棠|AO3|平台|"
                           r"社群|圈内|避雷|求文|文案|示范|自写|自拟|自撰|改写|结构|骨架|技法|"
                           r"句式|模板|配方|示例|口诀|拍|节奏|原型|设定|写法|崩法|AI |人味")
    unattributed = []
    meta_pass = defaultdict(int)              # 单文件被 META_TALK 放行的引语计数
    for p2 in LIB.rglob("*.md"):
        if "_整理后" in str(p2) or p2.name == "04-质量审计报告.md":
            continue
        t2 = p2.read_text(encoding="utf-8", errors="ignore")
        for m in SENT.finditer(t2):
            # 「例句自写」这类标记常在小节开头，离引号可能有两三百字，窗口要够宽
            ctx = t2[max(0, m.start() - 450): m.end() + 200]
            q = m.group(1)
            if CITED.search(ctx):
                continue                      # 已注明出处，合规
            if META_TALK.search(q) or META_TALK.search(ctx):
                meta_pass[str(p2.relative_to(LIB))] += 1
                continue                      # 元话语：社群发言或本库自撰
            if not NARRATIVE.search(q):
                continue                      # 不像叙事散文，不构成表达搬运风险
            unattributed.append(f"{p2.relative_to(LIB)}: {m.group(1)[:38]}…")
    if unattributed:
        FAIL["I 成句引用既无出处也无来源标记"].extend(unattributed)
    # 体量闸：META_TALK 是逐条豁免，不管总量。单文件放行量暴涨多半不是在写分析，
    # 而是把社媒采集的帖子成批贴进了正文——红线 1.2 禁的正是「从多篇各摘一段拼成素材」。
    # 阈值 = 存量最大 + 2（2026-08-09 实测分布：39 开场白库（全自撰示范）、
    # 27 社群画像、21 术语卷；34 个文件命中，其余 ≤16）。观察项，不进返回码。
    for rel2, n in meta_pass.items():
        if n > 41:
            WARN["I 单文件社群/自撰引语体量（观察项）"].append(f"{rel2}：{n} 条")

    # ── H 引用配额（红线 1.3：单篇不超过一句）──
    # 逐部作品的精读笔记是最容易越界的地方（规约 1.4 明说）。这里按
    # 「≥25 字的成句引号」计数，因为更短的多是术语或称谓，不构成表达搬运。
    #
    # 该目录（原 09 卷）已下架：本地保留、.gitignore 排除、不入库。
    # 本机上它还在，规则照查——红线 1.4 对本地笔记同样适用；
    # fresh clone 上目录不存在，glob 返回空，本项自然跳过，不报错也不误判。
    for p in (LIB / "09-拆解卡").glob("*.md"):
        if "_模板" in str(p):
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        quotes = re.findall(r"[「『“]([^」』”\n]{25,})[」』”]", t)
        # 卡自己的分析语句也会带引号，只算**明确标了出处**的那些
        real = [q for q in quotes
                if re.search(r"——《|——\s*\S+第\s*\d+\s*章|原文|出处",
                             t[t.find(q): t.find(q) + len(q) + 60])]
        if len(real) > 1:
            FAIL["H 拆解卡引用超出「单篇一句」配额"].append(
                f"{p.relative_to(LIB)}（{len(real)} 处标注出处的成句引用）")

    # ── G 双链健康度 ──
    # 悬空双链按规约是「待办便签」不是错误，但**写法对不上实际标题**的那种是错误。
    # 这里只报总数与比例，让它可被观察；超过 25% 说明写法开始失控。
    ok_targets = set()
    for p in LIB.rglob("*.md"):
        if "_整理后" in str(p):
            continue
        ok_targets.add(p.stem)
        ok_targets.add(re.sub(r"^\d+-", "", p.stem))
        for m in re.finditer(r"^#{1,6} +(.+?)\s*$", p.read_text(encoding="utf-8", errors="ignore"), re.M):
            h = re.sub(r"^(?:[〇一二三四五六七八九十]+|\d+|[A-Z]\d*)[、.．·]\s*", "", m.group(1))
            h = re.sub(r"[↺★☆✅⚠️📌]", "", h).strip()
            for part in re.split(r"\s*[/／]\s*", re.sub(r"[（(][^)）]*[)）]", "", h)):
                if part.strip():
                    ok_targets.add(part.strip())
            if h:
                ok_targets.add(h)
    wl, dangling = set(), set()
    for p in LIB.rglob("*.md"):
        if "_整理后" in str(p):
            continue
        for m in re.finditer(r"\[\[([^\]\n|]{1,60})\]\]", p.read_text(encoding="utf-8", errors="ignore")):
            k = m.group(1).strip()
            wl.add(k)
            if k and k not in ok_targets:
                dangling.add(k)
    # 带卷前缀却能去前缀命中的，是**写法错误**而非待办便签——这类要报
    bad_form = [k for k in dangling if "/" in k and k.rsplit("/", 1)[1] in ok_targets]
    if bad_form:
        FAIL["G 双链写法与实际标题不符"].extend(bad_form)
    pct = len(dangling) / max(len(wl), 1) * 100
    if pct > 25:
        FAIL["G 悬空双链占比过高"].append(
            f"{len(dangling)}/{len(wl)} = {pct:.0f}%（>25% 说明写法失控，不是待办变多）")

    # ── 行内豁免清单（可见性，防滥用）──
    exempts = []
    for p in LIB.rglob("*.md"):
        if "_整理后" in str(p):
            continue
        for i, l in enumerate(p.read_text(encoding="utf-8", errors="ignore").split("\n"), 1):
            for m in EXEMPT_RE.finditer(l):
                exempts.append(f"{p.relative_to(LIB)}:{i} [{m.group(1)}]{m.group(2).strip()[:30]}")

    # ── 报告 ──
    print(f"检查 {len(files)} 篇内容卷（规约/数据/成品/导出/机器生成卷不计）\n")
    for k in sorted(WARN):
        v = WARN[k]
        print(f"⚠ {k}：{len(v)} 处")
        for x in v[:8]:
            print(f"    {x}")
        if len(v) > 8:
            print(f"    …另 {len(v)-8} 处")
        print()
    if exempts:
        print(f"◦ 行内豁免 {len(exempts)} 处：")
        for x in exempts[:10]:
            print(f"    {x}")
        if len(exempts) > 10:
            print(f"    …另 {len(exempts)-10} 处")
        print()
    total = sum(len(v) for v in FAIL.values())
    if not total:
        print("✅ 全部检查项通过" + ("（警告不计入返回码）" if WARN else ""))
        return 0
    for k in sorted(FAIL):
        v = FAIL[k]
        print(f"✗ {k}：{len(v)} 处")
        for x in v[:12]:
            print(f"    {x}")
        if len(v) > 12:
            print(f"    …另 {len(v)-12} 处")
        print()
    print(f"合计 {total} 处不合规")
    return 1


if __name__ == "__main__":
    sys.exit(main())
